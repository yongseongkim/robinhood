"""A fresh deployment must fetch valid map inputs before publishing a map."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build_geo as geo


class Response:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, **kwargs):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def test_missing_sources_are_downloaded_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(geo, "RAW", tmp_path)
    monkeypatch.setattr(geo, "SOURCES", [
        {"file": "map.json", "url": "https://github.com/org/repo/blob/main/map.json"},
        {"file": "LICENSE", "url": "https://github.com/org/repo/blob/main/LICENSE"},
    ])
    feature = json.dumps({"type": "FeatureCollection", "features": [{}]}).encode()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response([feature if url.endswith("map.json") else b"MIT license"])

    monkeypatch.setattr(geo.requests, "get", get)
    assert geo.fetch_missing_sources() == 2
    assert (tmp_path / "map.json").read_bytes() == feature
    assert calls == [
        "https://raw.githubusercontent.com/org/repo/main/map.json",
        "https://raw.githubusercontent.com/org/repo/main/LICENSE",
    ]
    assert geo.fetch_missing_sources() == 0
    assert len(calls) == 2
    assert not list(tmp_path.glob(".geo-*.part"))


@pytest.mark.parametrize("chunks", [
    [b""],
    [b"<html>unavailable</html>"],
    [b'{"type":"FeatureCollection","features":[]}'],
    [b'{"type":"FeatureCollection","features":"invalid"}'],
    [b"partial", RuntimeError("network interrupted")],
])
def test_invalid_or_interrupted_downloads_are_not_published(tmp_path, monkeypatch, chunks):
    monkeypatch.setattr(geo, "RAW", tmp_path)
    monkeypatch.setattr(geo, "SOURCES", [{"file": "map.json", "url": "https://example.com/map.json"}])
    monkeypatch.setattr(geo.requests, "get", lambda *args, **kwargs: Response(chunks))
    with pytest.raises((ValueError, RuntimeError)):
        geo.fetch_missing_sources()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("no_fetch", [False, True])
def test_pipeline_respects_fetch_mode_for_collectors_and_maps(tmp_path, no_fetch):
    root = Path(__file__).resolve().parents[1]
    command_log = tmp_path / "commands.jsonl"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "with open(os.environ['ROBINHOOD_TEST_COMMAND_LOG'],'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:])+'\\n')\n"
    )
    fake_python.chmod(0o700)
    env = {
        **os.environ,
        "ROBINHOOD_PIPELINE_PYTHON": str(fake_python),
        "ROBINHOOD_TEST_COMMAND_LOG": str(command_log),
    }
    env.pop("ROBINHOOD_OCR_CORRECTION_PYTHON", None)
    subprocess.run(
        ["bash", str(root / "pipeline/run_all.sh")] + (["--no-fetch"] if no_fetch else []),
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    commands = [json.loads(line) for line in command_log.read_text().splitlines()]
    map_command = next(command for command in commands if command[0] == "pipeline/build_geo.py")
    assert map_command == ["pipeline/build_geo.py"] + (["--no-fetch"] if no_fetch else [])
    assert any(command[0].startswith("pipeline/collect_") for command in commands) is not no_fetch
