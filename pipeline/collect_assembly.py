"""열린국회정보(국회사무처) Open API 수집 → data/raw/assembly/

- 국회의원 인적사항 (nwvrqwxyaytdsfvhu): 현직 의원
- 국회의원 발의법률안 (nzmimeepazxkubdpn): 제21대·제22대
인증키는 credentials.yaml(SOPS)에서 메모리로만 읽고, 파일·로그·manifest에 남기지 않는다.
개인정보 최소화: 생년월일·전화·이메일·보좌진·약력·사무실 주소 필드는 저장하지 않는다.
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

import credentials
from common import RAW, ROOT

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
        r = session.get(BASE + service, params={"KEY": key, "Type": "json", "pIndex": page, "pSize": page_size, **params}, timeout=60)
        r.raise_for_status()
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
    return rows, total


def save(name, rows, service, params, total):
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(rows, ensure_ascii=False).encode()
    (OUT / f"{name}.json").write_bytes(data)
    return {"file": f"{name}.json", "service": service, "params": params, "rows": len(rows), "list_total_count": total,
            "sha256": hashlib.sha256(data).hexdigest(), "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            "url": BASE + service}


def main():
    try:
        key = credentials.get("assembly_api_key")
    except credentials.MissingCredential as e:
        print(f"열린국회정보 수집 건너뜀: {e}", file=sys.stderr)
        return
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"
    manifest = []
    members, total = fetch_all(s, key, "nwvrqwxyaytdsfvhu", MEMBER_FIELDS, page_size=300)
    manifest.append(save("members_current", members, "nwvrqwxyaytdsfvhu", {}, total))
    for age in (21, 22):
        bills, total = fetch_all(s, key, "nzmimeepazxkubdpn", BILL_FIELDS, AGE=age)
        manifest.append(save(f"bills_{age}", bills, "nzmimeepazxkubdpn", {"AGE": age}, total))
    (OUT / "manifest.json").write_text(json.dumps({
        "source": "국회사무처 열린국회정보 Open API (https://open.assembly.go.kr)",
        "excluded_fields": ["BTH_DATE", "TEL_NO", "E_MAIL", "STAFF", "SECRETARY", "SECRETARY2", "MEM_TITLE", "ASSEM_ADDR",
                            "ENG_NM", "SEX_GBN_NM", "BTH_GBN_NM", "PUBL_PROPOSER", "MEMBER_LIST"],
        "files": manifest}, ensure_ascii=False, indent=1))
    print(f"saved {len(manifest)} files to {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
