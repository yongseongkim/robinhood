"""Changed blobs, invalid upstream replacements and damaged caches."""
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import collect_ka_money as collector


def workbook(marker):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', marker)
        archive.writestr('xl/workbook.xml', marker)
    return stream.getvalue()


def item(data, name='2024_KAPF-22.xlsx', ref='master'):
    sha = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
    return {'name': name, 'path': name, 'sha': sha, 'size': len(data),
            'html_url': f'https://github.com/OhmyNews/KA-money/blob/{ref}/{name}'}


def response(data=None, content=b''):
    return SimpleNamespace(raise_for_status=lambda: None, content=content, json=lambda: data)


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, 'RAW', tmp_path)
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    return tmp_path / 'ka-money'


def test_same_size_changed_blob_and_corrupt_cache_are_downloaded(tmp_path, monkeypatch):
    out = setup(tmp_path, monkeypatch)
    out.mkdir()
    old, new = workbook('old'), workbook('new')
    source = item(new)
    path = out / source['name']
    path.write_bytes(old)
    (out / 'manifest.json').write_text(json.dumps([{'filename': path.name, 'blob_sha': 'before'}]))
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return response(content=new) if '/git/blobs/' in url else response([source])
    monkeypatch.setattr(collector.requests, 'get', get)
    collector.main()
    assert len(calls) == 2 and path.read_bytes() == new
    collector.main()
    assert len(calls) == 3
    path.write_bytes(b'x' * len(new))
    collector.main()
    assert len(calls) == 5 and path.read_bytes() == new


def test_invalid_replacement_recovers_historical_workbook_and_pins_provenance(tmp_path, monkeypatch):
    out = setup(tmp_path, monkeypatch)
    invalid, valid = b'upstream description, not a workbook', workbook('valid')
    current, historical = item(invalid), item(valid, ref='original-commit')
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        if '/commits' in url:
            return response([{'sha': 'bad-commit'}, {'sha': 'original-commit'}])
        if '/contents/' in url:
            return response(current if kwargs['params']['ref'] == 'bad-commit' else historical)
        if '/git/blobs/' in url:
            return response(content=invalid if url.endswith(current['sha']) else valid)
        return response([current])
    monkeypatch.setattr(collector.requests, 'get', get)
    collector.main()
    manifest = json.loads((out / 'manifest.json').read_text())[0]
    assert manifest['blob_sha'] == historical['sha']
    assert manifest['upstream_blob_sha'] == current['sha']
    assert '/original-commit/' in manifest['github_url']
    assert (out / current['name']).read_bytes() == valid
    before = len(calls)
    collector.main()
    assert len(calls) == before + 1


def test_unrecoverable_download_preserves_previous_workbook_and_manifest(tmp_path, monkeypatch):
    out = setup(tmp_path, monkeypatch)
    out.mkdir()
    old, invalid = workbook('old'), b'broken'
    path = out / '2024_KAPF-22.xlsx'
    path.write_bytes(old)
    manifest_path = out / 'manifest.json'
    manifest_path.write_text('[]')
    source = item(invalid)
    def get(url, **kwargs):
        if '/commits' in url:
            return response([])
        return response(content=invalid) if '/git/blobs/' in url else response([source])
    monkeypatch.setattr(collector.requests, 'get', get)
    with pytest.raises(ValueError, match='No valid published workbook'):
        collector.main()
    assert path.read_bytes() == old and manifest_path.read_text() == '[]'


def test_blob_hash_mismatch_rejected(monkeypatch):
    monkeypatch.setattr(collector.requests, 'get', lambda *a, **kw: response(content=b'wrong'))
    with pytest.raises(ValueError, match='size/hash mismatch'):
        collector.blob(item(b'valid'))
