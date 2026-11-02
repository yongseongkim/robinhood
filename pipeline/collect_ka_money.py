"""OhmyNews KA-money (국회의원 정치자금 지출내역) 2024년 파일 수집기.

GitHub 저장소의 파일명은 NFD로 인코딩되어 있어 raw URL을 손으로 만들면 404가 난다.
contents API 목록에서 blob SHA를 얻어 그대로 내려받는다.
"""
import hashlib
import json
import sys
import unicodedata
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
    "README.md": "README.md",
}
KST = timezone(timedelta(hours=9))


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
        blob_url = f"https://api.github.com/repos/{REPO}/git/blobs/{item['sha']}"
        if not local.exists() or local.stat().st_size != item["size"] or previous.get(name, {}).get('blob_sha') != item['sha']:
            r = requests.get(blob_url, headers={"Accept": "application/vnd.github.raw"}, timeout=120)
            r.raise_for_status()
            local.write_bytes(r.content)
            print(f"downloaded {name}", file=sys.stderr)
        data = local.read_bytes()
        manifest.append({
            "filename": name,
            "github_url": item["html_url"],
            "blob_sha": item["sha"],
            "local_path": str(local.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        })
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{len(manifest)} files in manifest", file=sys.stderr)


if __name__ == "__main__":
    main()
