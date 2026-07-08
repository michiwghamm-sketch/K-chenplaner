from pathlib import Path

from scripts.inspect_excel import find_excel_file


def test_find_excel_file_prefers_single_candidate(tmp_path) -> None:
    workbook = tmp_path / "demo.xlsx"
    workbook.write_bytes(b"placeholder")
    assert find_excel_file(tmp_path, None) == workbook


def test_find_excel_file_honors_explicit_path(tmp_path) -> None:
    workbook = tmp_path / "data" / "demo.xlsx"
    workbook.parent.mkdir(parents=True, exist_ok=True)
    workbook.write_bytes(b"placeholder")
    explicit = Path("data/demo.xlsx")
    assert find_excel_file(tmp_path, str(explicit)) == workbook
