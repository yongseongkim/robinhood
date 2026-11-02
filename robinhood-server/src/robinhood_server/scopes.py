from calendar import monthrange
from datetime import date

REPORTS = {"ka:2023": (2023, "제21대"), "ka:2024-21": (2024, "제21대"), "ka:2024-22": (2024, "제22대")}
FUNDS = {"POLITICAL_FUND", "COUNCIL_OPERATION", "COUNCIL_COMMON", "INSTITUTION_OPERATION", "POLICY_PROMOTION", "DEPARTMENT_OPERATION", "NEGOTIATION_GROUP", "OTHER_COUNCIL"}


def period(start: str, end: str, funding: str, report: str | None = None, **extra):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if s > e:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")
    if funding not in FUNDS:
        raise ValueError("지원하지 않는 재원입니다.")
    if report and (report not in REPORTS or funding != "POLITICAL_FUND"):
        raise ValueError("정치자금 보고서를 확인해 주세요.")
    if report:
        year, term = REPORTS[report]
        if s.year != year or e.year != year:
            raise ValueError("선택한 보고연도 안에서 기간을 지정해 주세요.")
        kind = "report"
        full_year = s.month == s.day == 1 and e.month == 12 and e.day == 31
        label = f"{year}년 {term} 보고분 합계" if full_year else f"{s:%Y.%m.%d}–{e:%Y.%m.%d} {term} 보고분 합계"
        note = "선택한 회계보고분에 수록된 거래입니다. 의원의 전체 연간 지출과 다를 수 있습니다."
    elif s.month == s.day == 1 and e.year == s.year and e.month == 12 and e.day == 31:
        kind, label, note = "annual", f"{s.year}년 연간 합계", "자료가 없는 달을 지출 0원으로 해석하지 않습니다."
    elif s.day == 1 and s.year == e.year and s.month == e.month and e.day == monthrange(e.year, e.month)[1]:
        kind, label, note = "monthly", f"{s.year}년 {s.month}월 합계", "선택한 달에 기록된 거래만 집계합니다."
    else:
        kind, label, note = "range", f"{s:%Y.%m.%d}–{e:%Y.%m.%d} 기간 합계", "선택한 기간의 합계이며 월평균과 구분합니다."
    return {"kind": kind, "label": label, "start": start, "end": end, "fundingType": funding, "reportId": report, "unit": "KRW", "note": note, **extra}


def report_period(report="ka:2024-22", start=None, end=None):
    if report not in REPORTS:
        raise ValueError("지원하지 않는 보고서입니다.")
    year = REPORTS[report][0]
    return period(start or f"{year}-01-01", end or f"{year}-12-31", "POLITICAL_FUND", report)


def month_series(start, end, values):
    lookup = {r["month"]: dict(r) for r in values}
    y, m = int(start[:4]), int(start[5:7])
    result = []
    while f"{y:04}-{m:02}" <= end[:7]:
        key = f"{y:04}-{m:02}"
        result.append({"month": key, "amount": None, "count": 0, "payments": 0, "hasRecords": key in lookup, **lookup.get(key, {})})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return result
