from __future__ import annotations

import json
import math
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from zipfile import ZipFile


END_OF_CHAIN = 0xFFFFFFFE
FREE_SECTOR = 0xFFFFFFFF


@dataclass
class DirEntry:
    name: str
    entry_type: int
    left_sibling: int
    right_sibling: int
    child: int
    start_sector: int
    size: int


class CompoundFileBinary:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
        self.first_dir_sector = struct.unpack_from("<I", data, 48)[0]
        self.mini_stream_cutoff = struct.unpack_from("<I", data, 56)[0]
        self.first_mini_fat_sector = struct.unpack_from("<I", data, 60)[0]
        self.num_mini_fat_sectors = struct.unpack_from("<I", data, 64)[0]
        self.first_difat_sector = struct.unpack_from("<I", data, 68)[0]
        self.num_difat_sectors = struct.unpack_from("<I", data, 72)[0]
        self.difat = list(struct.unpack_from("<109I", data, 76))
        self.fat: list[int] = []
        self.directory_entries: list[DirEntry] = []
        self.root_entry: DirEntry | None = None
        self.mini_fat: list[int] = []
        self.mini_stream: bytes = b""
        self._load()

    def _sector_offset(self, sector_id: int) -> int:
        return (sector_id + 1) * self.sector_size

    def _read_sector(self, sector_id: int) -> bytes:
        offset = self._sector_offset(sector_id)
        return self.data[offset : offset + self.sector_size]

    def _iter_chain(self, start_sector: int, fat: list[int]) -> Iterator[int]:
        seen: set[int] = set()
        sector = start_sector
        while sector not in (END_OF_CHAIN, FREE_SECTOR):
            if sector in seen or sector >= len(fat):
                break
            seen.add(sector)
            yield sector
            sector = fat[sector]

    def _load(self) -> None:
        difat = [sector for sector in self.difat if sector not in (FREE_SECTOR, END_OF_CHAIN)]
        next_sector = self.first_difat_sector
        for _ in range(self.num_difat_sectors):
            if next_sector in (FREE_SECTOR, END_OF_CHAIN):
                break
            sector_data = self._read_sector(next_sector)
            entries = struct.unpack_from(f"<{(self.sector_size // 4) - 1}I", sector_data, 0)
            difat.extend([entry for entry in entries if entry not in (FREE_SECTOR, END_OF_CHAIN)])
            next_sector = struct.unpack_from("<I", sector_data, self.sector_size - 4)[0]

        fat_bytes = b"".join(self._read_sector(sector) for sector in difat)
        self.fat = list(struct.unpack(f"<{len(fat_bytes) // 4}I", fat_bytes))

        dir_stream = self._read_stream_normal(self.first_dir_sector)
        for offset in range(0, len(dir_stream), 128):
            entry_data = dir_stream[offset : offset + 128]
            if len(entry_data) < 128:
                continue
            name_len = struct.unpack_from("<H", entry_data, 64)[0]
            raw_name = entry_data[: max(name_len - 2, 0)]
            name = raw_name.decode("utf-16le", errors="ignore")
            entry = DirEntry(
                name=name,
                entry_type=entry_data[66],
                left_sibling=struct.unpack_from("<I", entry_data, 68)[0],
                right_sibling=struct.unpack_from("<I", entry_data, 72)[0],
                child=struct.unpack_from("<I", entry_data, 76)[0],
                start_sector=struct.unpack_from("<I", entry_data, 116)[0],
                size=struct.unpack_from("<Q", entry_data, 120)[0],
            )
            self.directory_entries.append(entry)

        self.root_entry = self.directory_entries[0]
        if self.root_entry:
            self.mini_stream = self._read_stream_normal(self.root_entry.start_sector, self.root_entry.size)

        if self.first_mini_fat_sector not in (END_OF_CHAIN, FREE_SECTOR):
            mini_fat_bytes = self._read_stream_normal(
                self.first_mini_fat_sector,
                self.num_mini_fat_sectors * self.sector_size,
            )
            self.mini_fat = list(struct.unpack(f"<{len(mini_fat_bytes) // 4}I", mini_fat_bytes))

    def _read_stream_normal(self, start_sector: int, size: int | None = None) -> bytes:
        if start_sector in (END_OF_CHAIN, FREE_SECTOR):
            return b""
        data = b"".join(self._read_sector(sector) for sector in self._iter_chain(start_sector, self.fat))
        return data[:size] if size is not None else data

    def _read_stream_mini(self, start_sector: int, size: int) -> bytes:
        if start_sector in (END_OF_CHAIN, FREE_SECTOR):
            return b""
        chunks: list[bytes] = []
        sector = start_sector
        seen: set[int] = set()
        while sector not in (END_OF_CHAIN, FREE_SECTOR) and sector < len(self.mini_fat):
            if sector in seen:
                break
            seen.add(sector)
            offset = sector * self.mini_sector_size
            chunks.append(self.mini_stream[offset : offset + self.mini_sector_size])
            sector = self.mini_fat[sector]
        return b"".join(chunks)[:size]

    def list_streams(self) -> list[tuple[str, bytes]]:
        names = self._build_paths()
        streams: list[tuple[str, bytes]] = []
        for index, entry in enumerate(self.directory_entries):
            if entry.entry_type != 2:
                continue
            path = "/".join(names.get(index, [entry.name]))
            if entry.size < self.mini_stream_cutoff:
                data = self._read_stream_mini(entry.start_sector, entry.size)
            else:
                data = self._read_stream_normal(entry.start_sector, entry.size)
            streams.append((path, data))
        return streams

    def _build_paths(self) -> dict[int, list[str]]:
        paths: dict[int, list[str]] = {}

        def walk(index: int, parent_path: list[str]) -> None:
            if index in (0xFFFFFFFF, FREE_SECTOR) or index >= len(self.directory_entries):
                return
            entry = self.directory_entries[index]
            walk(entry.left_sibling, parent_path)
            current_path = parent_path + [entry.name]
            paths[index] = current_path
            if entry.child != 0xFFFFFFFF:
                walk(entry.child, current_path)
            walk(entry.right_sibling, parent_path)

        if self.root_entry and self.root_entry.child != 0xFFFFFFFF:
            walk(self.root_entry.child, [])
        return paths


def decompress_vba_stream(data: bytes) -> bytes:
    if not data:
        return b""
    if data[0] != 0x01:
        return data

    output = bytearray()
    pos = 1
    while pos + 2 <= len(data):
        header = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        chunk_size = (header & 0x0FFF) + 3
        chunk_signature = (header >> 12) & 0x07
        chunk_flag = (header >> 15) & 0x01
        if chunk_signature != 0x03:
            break

        chunk_end = min(len(data), pos + chunk_size - 2)
        chunk_start_out = len(output)

        if chunk_flag == 0:
            output.extend(data[pos:chunk_end])
            pos = chunk_end
            continue

        while pos < chunk_end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= chunk_end:
                    break
                if (flags & (1 << bit)) == 0:
                    output.append(data[pos])
                    pos += 1
                    continue

                if pos + 2 > chunk_end:
                    pos = chunk_end
                    break

                token = struct.unpack_from("<H", data, pos)[0]
                pos += 2

                decompressed_chunk_size = len(output) - chunk_start_out
                bit_count = max(4, math.ceil(math.log2(max(decompressed_chunk_size, 1))))
                bit_count = min(bit_count, 12)
                length_mask = 0xFFFF >> bit_count
                offset = (token >> (16 - bit_count)) + 1
                length = (token & length_mask) + 3

                copy_start = len(output) - offset
                for _ in range(length):
                    if copy_start < 0 or copy_start >= len(output):
                        output.append(0)
                    else:
                        output.append(output[copy_start])
                    copy_start += 1

    return bytes(output)


def analyze_vba(project_path: Path) -> dict:
    with ZipFile(project_path) as workbook:
        vba_data = workbook.read("xl/vbaProject.bin")

    compound = CompoundFileBinary(vba_data)
    streams = compound.list_streams()
    vba_streams = []
    for stream_name, stream_data in streams:
        if not stream_name.startswith("VBA/"):
            continue
        if stream_name.split("/")[-1] in {"dir", "_VBA_PROJECT"} or "__SRP_" in stream_name:
            continue

        text = ""
        offsets_checked: list[int] = []
        for offset in range(len(stream_data) - 2):
            if stream_data[offset] != 0x01:
                continue
            header = stream_data[offset + 1] | (stream_data[offset + 2] << 8)
            signature = (header >> 12) & 0x07
            if signature != 0x03:
                continue
            offsets_checked.append(offset)
            decompressed = decompress_vba_stream(stream_data[offset:])
            candidate = decompressed.decode("latin1", errors="ignore")
            if "Attribute VB_Name" in candidate:
                text = candidate
                break

        if "Attribute VB_Name" not in text:
            continue

        vba_streams.append(
            {
                "stream": stream_name,
                "line_count": len(text.splitlines()),
                "contains_workbook_events": "Workbook_" in text,
                "contains_worksheet_events": "Worksheet_" in text,
                "contains_buttons": "CommandButton" in text,
                "subs": [line.strip() for line in text.splitlines() if line.strip().startswith(("Sub ", "Private Sub ", "Function ", "Private Function ", "Public Function "))],
                "offset_candidates": offsets_checked[:20],
                "source": text,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stream_count": len(streams),
        "vba_modules": vba_streams,
    }


def write_report(report_path: Path, analysis: dict) -> None:
    lines = [
        "# VBA-Analyse",
        "",
        f"- Generiert am: `{analysis['generated_at']}`",
        f"- Erkannte VBA-Module: `{len(analysis['vba_modules'])}`",
        "",
    ]
    for module in analysis["vba_modules"]:
        lines.append(f"## {module['stream']}")
        lines.append("")
        lines.append(f"- Zeilen: `{module['line_count']}`")
        if module["contains_workbook_events"]:
            lines.append("- Enthält Workbook-Events")
        if module["contains_worksheet_events"]:
            lines.append("- Enthält Worksheet-Events")
        if module["contains_buttons"]:
            lines.append("- Enthält CommandButton-/Form-Steuerungslogik")
        if module["subs"]:
            lines.append(f"- Prozeduren: `{'; '.join(module['subs'])}`")
        lines.append("")
        lines.append("```vb")
        lines.append(module["source"].strip())
        lines.append("```")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    workbook_path = project_root / "Rezepte_Kolping_mit_Makros.xlsm"
    analysis = analyze_vba(workbook_path)
    docs_dir = project_root / "docs"
    docs_dir.mkdir(exist_ok=True)
    write_report(docs_dir / "vba_analysis.md", analysis)
    (docs_dir / "vba_analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"VBA-Module erkannt: {len(analysis['vba_modules'])}")
    for module in analysis["vba_modules"]:
        print(module["stream"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
