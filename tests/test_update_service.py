import json
import urllib.error

import pytest

from app.services.update_service import UpdateCheckError, check_for_update


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_check_for_update_returns_newer_release(monkeypatch) -> None:
    def fake_urlopen(_request, timeout: int):
        assert timeout == 5
        return _Response({"tag_name": "v1.2.4", "html_url": "https://example.test/release"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = check_for_update("1.2.3")

    assert result is not None
    assert result.latest_version == "v1.2.4"
    assert result.download_url == "https://example.test/release"


def test_check_for_update_returns_none_for_current_release(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda _request, timeout: _Response({"tag_name": "v1.2.3", "html_url": "https://example.test/release"}),
    )

    assert check_for_update("1.2.3") is None


def test_check_for_update_can_raise_for_manual_check(monkeypatch) -> None:
    def fake_urlopen(_request, timeout: int):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert check_for_update("1.2.3") is None
    with pytest.raises(UpdateCheckError):
        check_for_update("1.2.3", raise_on_error=True)
