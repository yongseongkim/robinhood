"""A temporary council-site outage must not erase already collected documents."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline/districts'))
import g1


def test_empty_listing_retains_published_sources(tmp_path, monkeypatch):
    directory = tmp_path / 'gangbuk'
    directory.mkdir()
    posts = [{'post_url': 'https://example.com/post', 'attachments': [{'url': 'https://example.com/file'}]}]
    path = directory / 'manifest.json'
    path.write_text(json.dumps(posts))
    monkeypatch.setattr(g1, 'RAW', tmp_path)
    monkeypatch.setattr(g1, 'Fetcher', lambda base: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(g1, 'list_costbbs', lambda *args: [])
    assert g1.collect('gangbuk') == posts
    assert json.loads(path.read_text()) == posts
    path.write_text('[]')
    with pytest.raises(RuntimeError, match='empty collection'):
        g1.collect('gangbuk')


def test_coverage_uses_source_period_after_2026_and_excludes_date_errors(tmp_path, monkeypatch):
    import g1_parse

    source = tmp_path / "example"
    source.mkdir()
    posts = [{"post_url": "/post", "post_title": "업무추진비", "period": "2027-Q1",
              "attachments": [{"url": "/file", "filename": "원장.xlsx", "local_path": "원장.xlsx", "sha256": "0123456789ab"}]}]
    (source / "manifest.json").write_text(json.dumps(posts))
    rows = [{"date": d, "amount": 10} for d in ["2027-01-02", "2027-03-31", "2097-03-20", "2021-01-02"]]
    monkeypatch.setattr(g1_parse, "STAGING", tmp_path)
    monkeypatch.setattr(g1_parse, "RAW", tmp_path)
    monkeypatch.setattr(g1_parse, "parse_file", lambda *args: ((rows, 0), None))
    g1_parse.parse_council("example", {"name": "의회", "region": "서울", "base": "https://example.com"})
    registry = json.loads((tmp_path / "councils/example.json").read_text())
    assert (registry["collected_from"], registry["collected_to"]) == ("2027-01-02", "2027-03-31")
    assert len((tmp_path / "example.jsonl").read_text().splitlines()) == len(rows)
