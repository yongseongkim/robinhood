"""OhmyNews KA-money (국회의원 정치자금 지출내역) 지원 보고분 수집기.

GitHub 저장소의 파일명은 NFD로 인코딩되어 있어 raw URL을 손으로 만들면 404가 난다.
contents API 목록에서 blob SHA를 얻어 그대로 내려받는다.
"""
import hashlib
import io
import json
import sys
import unicodedata
import zipfile
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

import requests

from common import RAW, ROOT

REPO = "OhmyNews/KA-money"
WANTED = {
    "2024_KAPF-21.xlsx": "2024_KAPF-21.xlsx",
    "2024_KAPF-22.xlsx": "2024_KAPF-22.xlsx",
    "2024_KAPF-21_수입지출.xlsx": "2024_KAPF-21_income_expense.xlsx",
    "2024_KAPF-22_수입지출.xlsx": "2024_KAPF-22_income_expense.xlsx",
    "2023_KAPF_수입지출.xlsx": "2023_KAPF_income_expense.xlsx",
    "2025_KAPF.xlsx": "2025_KAPF.xlsx",
    "2025_KAPF_수입지출.xlsx": "2025_KAPF_income_expense.xlsx",
    "README.md": "README.md",
}
KST = timezone(timedelta(hours=9))


def valid_workbook(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return {"[Content_Types].xml", "xl/workbook.xml"} <= set(archive.namelist()) and archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def blob(item):
    response = requests.get(f"https://api.github.com/repos/{REPO}/git/blobs/{item['sha']}",
                            headers={"Accept": "application/vnd.github.raw"}, timeout=120)
    response.raise_for_status()
    data = response.content
    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if len(data) != item["size"] or digest != item["sha"]:
        raise ValueError("KA-money blob size/hash mismatch")
    return data


def historical_workbook(item):
    # 게시자가 XLSX를 설명문으로 덮어쓴 경우 마지막 정상 공개본과 그 출처를 보존한다.
    response = requests.get(f"https://api.github.com/repos/{REPO}/commits",
                            params={"path": item["path"], "per_page": 20}, timeout=30)
    response.raise_for_status()
    for commit in response.json():
        response = requests.get(f"https://api.github.com/repos/{REPO}/contents/{quote(item['path'])}",
                                params={"ref": commit["sha"]}, timeout=30)
        response.raise_for_status()
        candidate = response.json()
        if candidate["sha"] == item["sha"]:
            continue
        data = blob(candidate)
        if valid_workbook(data):
            return candidate, data
    raise ValueError(f"No valid published workbook: {unicodedata.normalize('NFC', item['name'])}")


def main():
    out = RAW / "ka-money"
    out.mkdir(parents=True, exist_ok=True)
    api = requests.get(f"https://api.github.com/repos/{REPO}/contents", timeout=30)
    api.raise_for_status()
    previous_path = out / 'manifest.json'
    previous = {m['filename']: m for m in json.loads(previous_path.read_text())} if previous_path.exists() else {}
    manifest = []
    for item in api.json():
        name = unicodedata.normalize("NFC", item["name"])
        if name not in WANTED:
            continue
        local = out / WANTED[name]
        prior = previous.get(name, {})
        cached = local.read_bytes() if local.exists() else b""
        workbook = name.endswith(".xlsx")
        unchanged = prior.get("upstream_blob_sha", prior.get("blob_sha")) == item["sha"]
        intact = cached and hashlib.sha256(cached).hexdigest() == prior.get("sha256")
        selected = item
        if unchanged and intact and (not workbook or valid_workbook(cached)):
            data = cached
            selected = {"sha": prior["blob_sha"], "html_url": prior["github_url"]}
        else:
            data = blob(item)
            if workbook and not valid_workbook(data):
                selected, data = historical_workbook(item)
                print(f"using last valid published revision: {name}", file=sys.stderr)
            temporary = local.with_suffix(local.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(local)
            print(f"downloaded {name}", file=sys.stderr)
        manifest.append({
            "filename": name,
            "github_url": selected["html_url"],
            "blob_sha": selected["sha"],
            "upstream_blob_sha": item["sha"],
            "local_path": str(local.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        })
    temporary = out / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    temporary.replace(out / "manifest.json")
    print(f"{len(manifest)} files in manifest", file=sys.stderr)


if __name__ == "__main__":
    main()
