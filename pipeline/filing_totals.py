"""Resolve PETI event notices to the matching signed Assembly gazette and its printed net total."""
import hashlib
import json
import re
import time

import pdfplumber
import requests

from collect_assets import list_issues
from common import RAW
from parse_assets import amount
from source_status import atomic_bytes, check_source


def totals(path):
    result = []
    owner = None
    thousand = False
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for row in table:
                    cells = [str(cell or "").strip() for cell in row]
                    if "소속" in cells and "성명" in cells and "직위" in cells:
                        name = next((v for v in cells[cells.index("성명")+1:] if v), "")
                        office = next((v for v in cells[cells.index("직위")+1:] if v), "")
                        owner = (name.replace(" ", ""), number) if any(v in office for v in ("국회의원", "국회의장", "국회부의장")) else None
                        thousand = False
                    label = re.sub(r"\s+", "", cells[0])
                    if "단위" in label:
                        thousand = "천원" in label
                    if owner and thousand and label == "총계":
                        numbers = [re.sub(r"\s+", "", v) for v in cells[1:]]
                        amounts = [amount(v) for v in numbers if re.fullmatch(r"-?[\d,]+", v)]
                        if len(amounts) in (1, 4):
                            result.append({"name": owner[0], "page": owner[1], "totalPage": number,
                                           "amount": amounts[-1] * 1000})
                        owner = None
    return result


def retry(fn):
    for attempt in range(3):
        try:
            return fn()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def collect():
    notices = json.loads((RAW / "peti/filings.json").read_text())
    events = [r for r in notices if r["kind"] == "수시"]
    folder = RAW / "assets/events"
    path = folder / "gazettes.json"
    editions = json.loads(path.read_text()) if path.exists() else {}
    for doc in editions.values():
        if (folder / doc["file"]).exists():
            doc["totals"] = totals(folder / doc["file"])
    if editions:
        atomic_bytes(path, json.dumps(editions, ensure_ascii=False).encode())
    needed = {r["published"] for r in events if not any(
        doc["date"] == r["published"] and any(t["name"] == r["name"] for t in doc["totals"])
        for doc in editions.values())}
    if not needed:
        return
    with requests.Session() as session:
        session.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"
        page = 1
        while needed:
            issues = retry(lambda: list_issues(session, page, ""))
            if not issues or max(i["date"] for i in issues) < min(needed):
                break
            for issue in issues:
                if issue["date"] not in needed:
                    continue
                name = re.search(r"제(\d{4}-\d+)호", issue["title"])[1]
                pdf = folder / ("gongbo_" + name + ".pdf")
                if not pdf.exists():
                    def download():
                        r = session.get(issue["url"], timeout=60)
                        r.raise_for_status()
                        if not r.content.startswith(b"%PDF"):
                            raise ValueError("잘못된 국회공보 파일")
                        return r.content
                    atomic_bytes(pdf, retry(download))
                rows = totals(pdf)
                editions[name] = {**issue, "file": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                  "totals": rows}
                atomic_bytes(path, json.dumps(editions, ensure_ascii=False).encode())
                if {r["name"] for r in events if r["published"] == issue["date"]} <= {
                        t["name"] for doc in editions.values() if doc["date"] == issue["date"] for t in doc["totals"]}:
                    needed.remove(issue["date"])
            if min(i["date"] for i in issues) < min(needed, default=""):
                break
            page += 1
    if needed:
        raise ValueError("일부 수시공개 총계 미확인")


if __name__ == "__main__":
    check_source("filing-totals", collect)
