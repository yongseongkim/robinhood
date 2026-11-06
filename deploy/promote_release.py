#!/usr/bin/env python3
"""Promote a published release snapshot to the branch watched by ArgoCD."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


RELEASE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
RECORD = "deploy/release.json"


def version(tag):
    match = RELEASE.fullmatch(tag)
    if not match:
        raise ValueError("Release tags must use vMAJOR.MINOR.PATCH, for example v0.3.0")
    return tuple(map(int, match.groups()))


def git(*arguments, data=None, environment=None, check=True):
    result = subprocess.run(
        ["git", *arguments], input=data, text=True, capture_output=True,
        env=environment, timeout=120,
    )
    if check and result.returncode:
        # Git 오류에 인증된 remote URL이 포함될 수 있어 원문은 출력하지 않는다.
        raise RuntimeError(f"git {arguments[0]} failed (exit {result.returncode})")
    return result


def production_revision(remote, branch):
    result = git("ls-remote", "--exit-code", "--heads", remote, f"refs/heads/{branch}", check=False)
    if result.returncode == 2:
        return None
    if result.returncode:
        raise RuntimeError("Could not read the production branch")
    git("fetch", "--no-tags", remote, f"refs/heads/{branch}")
    return git("rev-parse", "FETCH_HEAD").stdout.strip()


def stamp_values(text, release):
    lines, inside, replaced = text.splitlines(keepends=True), False, 0
    for index, line in enumerate(lines):
        if line.startswith("images:"):
            inside = True
        elif line.strip() and not line.startswith((" ", "#")):
            inside = False
        if inside and re.match(r"^  tag:", line):
            lines[index] = f'  tag: "{release}"\n'
            replaced += 1
    if replaced != 1:
        raise ValueError("Expected exactly one images.tag in the release chart")
    return "".join(lines)


def stamp_chart(text, release):
    for key in ("version", "appVersion"):
        text, replaced = re.subn(rf"^{key}:.*$", f'{key}: "{release}"', text, flags=re.MULTILINE)
        if replaced != 1:
            raise ValueError(f"Expected exactly one {key} in Chart.yaml")
    return text


def promote(tag, remote="origin", branch="deploy/production"):
    requested = version(tag)
    release = ".".join(map(str, requested))
    git("check-ref-format", "--branch", branch)
    source = git("rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").stdout.strip()
    if git("rev-parse", "HEAD").stdout.strip() != source:
        raise ValueError("Promotion must run from the tagged commit")
    parent = production_revision(remote, branch)
    if parent:
        record = json.loads(git("show", f"{parent}:{RECORD}").stdout)
        current = version(record["tag"])
        if requested < current:
            return {"status": "skipped-older-release", "tag": tag, "current": record["tag"]}
        if requested == current:
            if record["sourceRevision"] != source:
                raise ValueError("Published release tags cannot be moved to another commit")
            return {"status": "already-promoted", "tag": tag, "commit": parent}

    updates = {
        "deploy/helm/values.yaml": stamp_values(git("show", f"{source}:deploy/helm/values.yaml").stdout, release),
        "deploy/helm/Chart.yaml": stamp_chart(git("show", f"{source}:deploy/helm/Chart.yaml").stdout, release),
        RECORD: json.dumps({"tag": tag, "sourceRevision": source}, indent=2) + "\n",
    }
    # 독립 index로 태그의 tree를 구성해 호출자의 checkout과 staged 변경을 건드리지 않는다.
    with tempfile.TemporaryDirectory(prefix="robinhood-release-") as directory:
        environment = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", source, environment=environment)
        for path, contents in updates.items():
            blob = git("hash-object", "-w", "--stdin", data=contents).stdout.strip()
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", environment=environment)
        tree = git("write-tree", environment=environment).stdout.strip()
        parents = ["-p", parent or source]
        if parent and parent != source:
            parents += ["-p", source]
        commit = git("commit-tree", tree, *parents,
                     data=f"Deploy {tag}\n\nSource: {source}\n").stdout.strip()
    # fast-forward push만 허용하므로 동시 변경을 덮어쓰지 않는다.
    git("push", remote, f"{commit}:refs/heads/{branch}")
    return {"status": "promoted", "tag": tag, "version": release,
            "sourceRevision": source, "commit": commit, "branch": branch}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "promote"])
    parser.add_argument("tag")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="deploy/production")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            print(".".join(map(str, version(args.tag))))
        else:
            print(json.dumps(promote(args.tag, args.remote, args.branch)))
    except (ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
