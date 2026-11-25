"""열린국회정보에서 현직 국회의원 명부와 제21·22대 발의 법률안을 수집해 data/raw/assembly/에 보관한다.

명부는 nwvrqwxyaytdsfvhu, 발의 법률안은 nzmimeepazxkubdpn 서비스를 사용한다.
인증키는 credentials.get으로 읽고 파일·로그·manifest에 기록하지 않는다.
명부에서 생년월일·전화번호·이메일·보좌진·약력·사무실 주소는 저장하지 않는다.
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

import credentials
from common import RAW, ROOT
from source_status import atomic_bytes, check_source

BASE = "https://open.assembly.go.kr/portal/openapi/"
KST = timezone(timedelta(hours=9))
OUT = RAW / "assembly"
MEMBER_FIELDS = ("MONA_CD", "HG_NM", "HJ_NM", "POLY_NM", "ORIG_NM", "ELECT_GBN_NM", "CMIT_NM", "CMITS", "REELE_GBN_NM",
                 "UNITS", "JOB_RES_NM", "HOMEPAGE")
BILL_FIELDS = ("BILL_ID", "BILL_NO", "BILL_NAME", "AGE", "COMMITTEE", "PROPOSE_DT", "PROC_DT", "PROC_RESULT", "PROPOSER",
               "RST_PROPOSER", "RST_MONA_CD", "PUBL_MONA_CD", "DETAIL_LINK")


def fetch_all(session, key, service, fields, page_size=1000, **params):
    rows, page, total = [], 1, None
    while True:
        for attempt in range(3):
            try:
                r = session.get(BASE + service, params={"KEY": key, "Type": "json", "pIndex": page, "pSize": page_size, **params}, timeout=45)
                r.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        body = r.json().get(service)
        if not body:
            msg = json.dumps(r.json(), ensure_ascii=False)[:200].replace(key, "***")
            raise RuntimeError(f"{service} 응답 오류: {msg}")
        total = body[0]["head"][0]["list_total_count"]
        batch = body[1]["row"] if len(body) > 1 else []
        rows += [{k: row.get(k) for k in fields} for row in batch]
        print(f"  {service} {params} page {page}: {len(rows)}/{total}", file=sys.stderr)
        if not batch or len(rows) >= total:
            break
        page += 1
        time.sleep(0.3)
    if len(rows) != total or not rows:
        raise ValueError(f"{service}: 불완전한 수집")
    if fields == BILL_FIELDS and len({r["BILL_ID"] for r in rows}) != total:
        raise ValueError("중복된 법안 페이지")
    return rows, total


def save(name, rows, service, params, total):
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(rows, ensure_ascii=False).encode()
    atomic_bytes(OUT / f"{name}.json", data)
    return {"file": f"{name}.json", "service": service, "params": params, "rows": len(rows), "list_total_count": total,
            "sha256": hashlib.sha256(data).hexdigest(), "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            "url": BASE + service}


def refresh(name, service, fields, **params):
    key = credentials.get("assembly_api_key")
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"
    rows, total = fetch_all(session, key, service, fields, **params)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"source": BASE, "files": []}
    old = next((f for f in manifest["files"] if f["file"] == name + ".json"), None)
    if name == "members_current":
        if len({m["MONA_CD"] for m in rows if m["MONA_CD"]}) != len(rows):
            raise ValueError("의원 코드 중복 또는 누락")
        if old and (OUT / old["file"]).exists():
            atomic_bytes(OUT / "rosters" / (old["fetched_at"][:10] + "-" + old["sha256"] + ".json"),
                         (OUT / old["file"]).read_bytes())
    entry = save(name, rows, service, params, total)
    files = {f["file"]: f for f in manifest["files"]}
    files[entry["file"]] = entry
    manifest["files"] = sorted(files.values(), key=lambda f: (f["file"] != "members_current.json", f["file"]))
    atomic_bytes(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=1).encode())


def main():
    check_source("roster", lambda: refresh("members_current", "nwvrqwxyaytdsfvhu", MEMBER_FIELDS, page_size=300))
    for age in (22, 21):
        check_source(f"bills-{age}", lambda: refresh(f"bills_{age}", "nzmimeepazxkubdpn", BILL_FIELDS, AGE=age))


if __name__ == "__main__":
    main()
