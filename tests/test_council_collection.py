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
