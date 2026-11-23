"""Collect Assembly members' dated filing notices from PETI's public search form."""
from datetime import date, timedelta
import json
import re

import requests

from common import RAW
from source_status import atomic_bytes, check_source

BASE = "https://www.peti.go.kr"
SEARCH = BASE + "/peOptpListVie.do"


def iso(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return date.fromisoformat(digits).isoformat() if len(digits) == 8 else None


def collect():
    dest = RAW / "peti" / "filings.json"
    annual = json.loads((RAW / "assets/manifest.json").read_text())
    start = date.fromisoformat(max(i["date"] for i in annual if "정기재산공개" in i["title"]))
    today = date.today()
    existing = json.loads(dest.read_text()) if dest.exists() else []
    records = {r["id"]: r for r in existing if r["published"] < start.isoformat()}
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (compatible; robinhood-collector)"
        page = session.get(SEARCH, timeout=45)
        page.raise_for_status()
        token = re.search(r'id="csrfToken"[^>]*value="([^"]+)', page.text)[1]
        while start <= today:
            end = min(start + timedelta(days=179), today)
            first = 1
            while True:
                res = session.post(BASE + "/peoptp/getListOptpListVie.do", timeout=60,
                    headers={"Referer": SEARCH, "X-Requested-With": "XMLHttpRequest"},
                    data={"fromOptpDt": start.strftime("%Y%m%d"), "toOptpDt": end.strftime("%Y%m%d"),
                          "firstCount": first, "lastCount": first + 99, "ornm": "국회",
                          "rgsDtrNm": "", "srchSe": "dtrSrch", "csrfToken": token})
                res.raise_for_status()
                body = res.json()
                rows, total = body["result"], int(body["totalCount"])
                if len(rows) != min(100, max(0, total - first + 1)):
                    raise ValueError("불완전한 공직윤리시스템 목록")
                for row in rows:
                    position = row.get("ofpsNm") or ""
                    if not any(role in position for role in ("국회의원", "국회의장", "국회부의장")):
                        continue
                    key = str(row["rgsMno"])
                    records[key] = {"id": key, "name": row["rgsDtrNm"], "office": position,
                                    "published": iso(row["optpDt"]), "basis": iso(row.get("rgsSrDt")),
                                    "kind": row.get("optpShpNm") or "재산공개", "url": SEARCH}
                first += len(rows)
                if first > total:
                    break
            start = end + timedelta(days=1)
    atomic_bytes(dest, json.dumps(sorted(records.values(), key=lambda r: (r["published"], r["id"])),
                                 ensure_ascii=False).encode())


if __name__ == "__main__":
    check_source("peti", collect)
