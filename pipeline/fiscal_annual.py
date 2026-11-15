"""월별 API에 12월이 없는 해의 공식 국가결산 연간 표를 수집한다."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import re

import pdfplumber
import requests

from common import RAW, ROOT

REPORTS = {
    2025: {
        "name": "한국재정정보원 · 통계로 보는 국가결산 2025",
        "url": "https://www.fis.kr/ko/notification/data/financial_stat?articleSeq=5186",
        "download": "https://www.fis.kr/egf/bp/board/article/download?fileSeq=4152",
        "pages": [20, 23],
    },
}
FIELDS = {"총수입": "total_revenue", "총지출": "total_expenditure",
          "통합재정수지": "integrated_balance", "관리재정수지": "managed_balance"}


def parse_tables(texts, year):
    values = {}
    for text in texts:
        lines = text.splitlines()
        header = next((line.split() for line in lines if re.fullmatch(r"20\d{2}(?:\s+20\d{2})+", line.strip())), None)
        if not header or str(year) not in header or len(set(header)) != len(header):
            raise ValueError("Annual fiscal table year header not found")
        for line in lines:
            parts = line.split()
            if parts and parts[0] in FIELDS:
                numbers = parts[1:]
                if len(numbers) != len(header) or not all(re.fullmatch(r"-?\d+(?:\.\d+)?", n) for n in numbers):
                    continue
                values[FIELDS[parts[0]]] = int(Decimal(numbers[header.index(str(year))]) * 10**12)
    if set(values) != set(FIELDS.values()):
        raise ValueError("Annual fiscal settlement totals are incomplete")
    if abs(values["total_revenue"] - values["total_expenditure"] - values["integrated_balance"]) > 10**11:
        raise ValueError("Annual fiscal settlement totals do not reconcile")
    return values


def collect():
    directory = RAW / "fiscal-annual"
    directory.mkdir(parents=True, exist_ok=True)
    for year, report in REPORTS.items():
        path = directory / f"{year}.pdf"
        if path.exists():
            content = path.read_bytes()
        else:
            response = requests.get(report["download"], headers={"User-Agent": "Mozilla/5.0", "Referer": report["url"]}, timeout=120)
            response.raise_for_status()
            content = response.content
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            values = parse_tables([pdf.pages[page - 1].extract_text() or "" for page in report["pages"]], year)
        source = {**report, "sha256": hashlib.sha256(content).hexdigest(),
                  "local_path": str(path.relative_to(ROOT)), "fetched_at": datetime.now(timezone.utc).isoformat()}
        temporary_pdf = path.with_suffix(".pdf.tmp")
        temporary_pdf.write_bytes(content)
        temporary_pdf.replace(path)
        temporary = directory / f"{year}.json.tmp"
        temporary.write_text(json.dumps({"year": year, "values": values, "source": source}, ensure_ascii=False))
        temporary.replace(directory / f"{year}.json")


def settlements():
    return [json.loads(path.read_text()) for path in sorted((RAW / "fiscal-annual").glob("*.json"))]
