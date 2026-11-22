"""KA-money annual accounting periods. Election years have one report per term."""
import re


def report_info(report):
    match = re.fullmatch(r"ka:(\d{4})(?:-(\d{2}))?", report or "")
    if not match:
        return None
    year = int(match[1])
    if year < 2023:
        return None
    term = 22 + (year - 2024) // 4
    split = (year - 2024) % 4 == 0
    if split:
        if match[2] not in (str(term - 1), str(term)):
            return None
        term = int(match[2])
    elif match[2] and match[2] != str(term):
        return None
    return year, f"제{term}대"


def workbook(name):
    match = re.fullmatch(r"(\d{4})_KAPF(?:-(\d+))?(_수입지출)?\.xlsx", name)
    if not match:
        return None
    year, split, detailed = match.groups()
    rid = "ka:" + year + ("-" + split if split else "")
    if year != "2023" and not split:
        rid += "-" + str(22 + (int(year)-2024)//4)
    info = report_info(rid)
    if not info:
        return None
    return {"id": rid, "year": info[0], "assembly": info[1], "detailed": bool(detailed),
            "expense_src": name.replace("_수입지출", "") if detailed and int(year) >= 2025 else None,
            "key": split if year == "2024" else (year[-2:] if not split else rid[3:]),
            "src_name": name, "file": name.replace("_수입지출", "_income_expense"),
            "period": (year + "-01-01", year + "-12-31")}
