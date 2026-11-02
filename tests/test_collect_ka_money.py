"""A corrected workbook can have the same byte length as the previous one."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import collect_ka_money as collector


def test_same_size_changed_blob_is_downloaded(tmp_path, monkeypatch):
    out = tmp_path / 'ka-money'
    out.mkdir()
    (out / '2024_KAPF-22.xlsx').write_bytes(b'old')
    (out / 'manifest.json').write_text(json.dumps([{'filename': '2024_KAPF-22.xlsx', 'blob_sha': 'before'}]))
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, content=b'new', json=lambda: [
            {'name': '2024_KAPF-22.xlsx', 'sha': 'after', 'size': 3, 'html_url': 'https://example.com/file'}])
    monkeypatch.setattr(collector, 'RAW', tmp_path)
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    monkeypatch.setattr(collector.requests, 'get', get)
    collector.main()
    assert len(calls) == 2
    assert (out / '2024_KAPF-22.xlsx').read_bytes() == b'new'
    collector.main()
    assert len(calls) == 3  # list refreshed, unchanged blob reused
