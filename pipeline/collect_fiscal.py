"""열린재정(기획재정부·한국재정정보원) Open API 수집 → data/raw/fiscal/, data/normalized/fiscal.json

사용 서비스 (https://openapi.openfiscaldata.go.kr/<서비스>, 응답은 JSON 문자열을 한 번 더 감싼 형태)
  OPFI156            재정수입구조(본예산 총수입 기준)      ACNT_YR   단위 조원
  OPFI157            국세수입추이(세목별, 예산/결산)        ACNT_YR   단위 조원
  OPFI165            16대 분야별 재원배분(총지출 기준)      ACNT_YR   단위 조원
  OPFI166            중앙관서별 총지출 추이                 ACNT_YR   단위 억원
  TotalExpenditure5  세부사업 예산편성현황(총지출 기준)     FSCL_YY   단위 천원
  GovernmentDebtYear 국가채무(D1)                           (전체)    단위 조원
  TotalIncome / GrossExpend / BudgetBalance  월별 총수입·총지출·재정수지(누계)  OJ_YY  단위 조원
인증키는 credentials.yaml(SOPS)에서 메모리로만 읽고 파일·로그·manifest에 남기지 않는다.
"""
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import requests

import credentials
from common import NORMALIZED, RAW, ROOT

BASE = "https://openapi.openfiscaldata.go.kr/"
OUT = RAW / "fiscal"
KST = timezone(timedelta(hours=9))
NOW = datetime.now(KST)
THIS_YEAR = NOW.year
PAUSE = 0.6
PAGE = 1000

JO, EOK, CHEON = 10 ** 12, 10 ** 8, 1000  # 조원·억원·천원 → 원

DATASETS = {
    "OPFI156": {"name": "재정수입구조(본예산총수입기준)", "odtId": "0754F30NJD22E4T047346LC08", "unit": "조원", "year_param": "ACNT_YR", "years": range(2010, THIS_YEAR + 2)},
    "OPFI157": {"name": "국세수입추이", "odtId": "6K2VC056U3I7G523Q5JP7QQT7", "unit": "조원", "year_param": "ACNT_YR", "years": range(2010, THIS_YEAR + 2)},
    "OPFI165": {"name": "16대분야별재원배분(총지출기준)", "odtId": "5JVB22KUDE71A1SMR67O50R63", "unit": "조원", "year_param": "ACNT_YR", "years": range(2010, THIS_YEAR + 2)},
    "OPFI166": {"name": "중앙관서별총지출추이", "odtId": "WHFDLEJ0WYTNZ1RJ1Z466IH61", "unit": "억원", "year_param": "ACNT_YR", "years": range(2010, THIS_YEAR + 2)},
    "GovernmentDebtYear": {"name": "국가채무(D1)", "odtId": "11UN000D6M7UJ2LFRO76OG35Y", "unit": "조원", "year_param": None, "years": [None]},
    "TotalIncome": {"name": "총수입(월별 누계)", "odtId": "507GT417LA1CN304P6FQ6VLVF", "unit": "조원", "year_param": "OJ_YY", "years": range(2014, THIS_YEAR + 1)},
    "GrossExpend": {"name": "총지출(월별 누계)", "odtId": "KXB8M1QM10T1V8XNA43KY7M07", "unit": "조원", "year_param": "OJ_YY", "years": range(2014, THIS_YEAR + 1)},
    "BudgetBalance": {"name": "재정수지(월별 누계)", "odtId": "45DHAZ24H7WWJ0VG03Q666V46", "unit": "조원", "year_param": "OJ_YY", "years": range(2014, THIS_YEAR + 1)},
    "TotalExpenditure5": {"name": "세부사업 예산편성현황(총지출)", "odtId": "5Y5A50K2L4CW2IRKI2J0F2C8T", "unit": "천원", "year_param": "FSCL_YY",
                          "years": range(max(2010, THIS_YEAR - 4), THIS_YEAR + 2), "extra": {"BDG_FND_DIV_CD": "0", "ANEXP_INQ_STND_CD": "1"}},
}
SOURCE_PAGE = "https://www.openfiscaldata.go.kr/op/ko/sd/UOPKOSDA01?odtId="


class Api:
    def __init__(self, key):
        self.key = key
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"

    def _get(self, svc, params):
        for attempt in range(4):
            try:
                r = self.s.get(BASE + svc, params={"Key": self.key, "Type": "json", **params}, timeout=90)
                r.raise_for_status()
                d = json.loads(r.text)
                if isinstance(d, str):  # 열린재정 응답은 JSON 문자열을 한 번 더 감싸서 준다
                    d = json.loads(d)
                return d
            except (requests.RequestException, ValueError) as e:
                msg = str(e).replace(self.key, "***")
                print(f"  재시도 {svc} {attempt + 1}: {msg[:120]}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"{svc} 요청 실패")

    def fetch_all(self, svc, params):
        rows, page, total = [], 1, None
        while True:
            d = self._get(svc, {**params, "pIndex": page, "pSize": PAGE})
            body = d.get(svc) if isinstance(d, dict) else None
            if not body:
                code = (d.get("RESULT") or {}).get("CODE") if isinstance(d, dict) else None
                return rows, 0, code or "NO_DATA"
            head = body[0].get("head", [])
            total = head[0].get("list_total_count", 0) if head else 0
            batch = body[1].get("row", []) if len(body) > 1 else []
            rows += batch
            if not batch or len(rows) >= total:
                return rows, total, "INFO-000"
            page += 1
            time.sleep(PAUSE)


def collect(api):
    manifest_path = OUT / "manifest.json"
    manifest = {m["file"]: m for m in json.loads(manifest_path.read_text())["files"]} if manifest_path.exists() else {}
    for svc, ds in DATASETS.items():
        for y in ds["years"]:
            params = dict(ds.get("extra", {}))
            if ds["year_param"]:
                params[ds["year_param"]] = str(y)
            fname = f"{svc}/{y or 'all'}.json"
            path = OUT / fname
            # 지난 해 이전 자료는 확정이라 다시 받지 않는다 (올해·작년·전체 시계열은 매번 갱신)
            if path.exists() and y is not None and y < THIS_YEAR - 1:
                continue
            rows, total, code = api.fetch_all(svc, params)
            time.sleep(PAUSE)
            if not rows:
                print(f"  {svc} {y}: 자료 없음({code})", file=sys.stderr)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(rows, ensure_ascii=False).encode()
            path.write_bytes(data)
            manifest[fname] = {"file": fname, "service": svc, "dataset": ds["name"], "params": params, "unit": ds["unit"],
                               "rows": len(rows), "list_total_count": total, "sha256": hashlib.sha256(data).hexdigest(),
                               "fetched_at": datetime.now(KST).isoformat(timespec="seconds"), "source_page": SOURCE_PAGE + ds["odtId"],
                               "url": BASE + svc}
            print(f"  {svc} {y}: {len(rows)}행", file=sys.stderr)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"source": "기획재정부 열린재정 Open API (https://www.openfiscaldata.go.kr)",
                                         "files": sorted(manifest.values(), key=lambda m: m["file"])}, ensure_ascii=False, indent=1))
    return manifest


# ---------------------------------------------------------------- 정규화
def load(svc):
    out = {}
    for p in sorted((OUT / svc).glob("*.json")) if (OUT / svc).exists() else []:
        out[p.stem] = json.loads(p.read_text())
    return out


def won(v, unit):
    if v is None:
        return None
    return int(round(float(v) * unit))


def normalize(manifest):
    notes = []
    fetched = max((m["fetched_at"] for m in manifest.values()), default=None)
    out = {"source": {"name": "기획재정부 열린재정", "url": "https://www.openfiscaldata.go.kr", "fetched_at": fetched},
           "units_note": "모든 금액은 원 단위로 변환했다. 원자료 단위: 재정수입구조·국세수입·16대 분야·국가채무·월별 총수입/총지출/재정수지는 조원(소수 첫째 자리), "
                         "중앙관서별 총지출은 억원, 세부사업 예산은 천원."}

    # 국세 세목별 (OPFI157): 세목(수입항) 기준으로 회계를 합친다
    tax = {}
    for y, rows in load("OPFI157").items():
        by = defaultdict(float)
        basis = sorted({r.get("BC_DIV_NM") for r in rows if r.get("BC_DIV_NM")})
        for r in rows:
            by[r.get("IHANG_NM") or r.get("IKWAN_NM")] += r.get("SUM_RCVMT_AMT") or 0
        tax[y] = {"basis": "/".join(basis), "items": sorted(({"name": k, "amount": won(v, JO)} for k, v in by.items() if v), key=lambda x: -x["amount"])}
    out["national_tax_by_item"] = {"years": tax}

    # 재정수입구조 (OPFI156, 본예산 총수입)
    rev = {}
    for y, rows in load("OPFI156").items():
        groups = {"국세": defaultdict(float), "세외수입": defaultdict(float), "기금수입": defaultdict(float)}
        for r in rows:
            amt = r.get("SUM_NASS_TREV_BDG_AMT") or 0
            kind, acct = r.get("SMOK_DIV_NM"), r.get("ACNT_DIV_NM")
            if r.get("BDG_FND_DIV_NM") == "기금":
                groups["기금수입"][kind] += amt
            elif kind == "국세수입":
                groups["국세"][acct] += amt
            else:
                groups["세외수입"][acct] += amt
        items = []
        for name, children in groups.items():
            total = sum(children.values())
            if not total:
                continue
            kids = [{"name": k, "amount": won(v, JO)} for k, v in sorted(children.items(), key=lambda kv: -kv[1]) if v]
            items.append({"name": name, "amount": won(total, JO), "children": kids})
        if items:  # 아직 국회를 통과하지 않은 해는 0으로만 채워져 온다
            rev[y] = items
    out["revenue"] = {"basis": "본예산 총수입 (일반회계·특별회계·기금 합계에서 내부거래·보전거래 제외)", "years": rev}

    # 16대 분야 (OPFI165)
    sect = {}
    for y, rows in load("OPFI165").items():
        basis = sorted({r.get("DIV_NM") for r in rows if r.get("DIV_NM")})
        sect[y] = {"basis": "/".join(basis), "items": [{"name": r["FLD_NM"], "code": r.get("FLD_CD"), "amount": won(r.get("SUM_AMT"), JO)}
                                                       for r in sorted(rows, key=lambda r: r.get("FLD_CD") or "")]}
    out["expenditure_by_sector"] = {"basis": "총지출 기준, 연도별로 예산 또는 결산(각 연도의 basis 참고)", "years": sect}

    # 중앙관서별 (OPFI166) 시계열
    hist = {}
    for y, rows in load("OPFI166").items():
        basis = sorted({r.get("STL_BDG_DIV_NM") for r in rows if r.get("STL_BDG_DIV_NM")})
        hist[y] = {"basis": "/".join(basis), "items": sorted(({"name": r["OFFC_NM"], "amount": won(r.get("SUM_EP_AMT"), EOK)} for r in rows),
                                                             key=lambda x: -(x["amount"] or 0))}

    # 확정 예산과 정부안을 연도별로 보존해야 과거 결산과 섞지 않고 편성 추이를 비교할 수 있다.
    te = load("TotalExpenditure5")
    budget_years, proposal_years = {}, {}
    sector_budgets, sector_proposals = {}, {}

    def budget_sections(rows, field, label):
        by_off = defaultdict(lambda: {"amount": 0, "programs": defaultdict(int)})
        by_sector = defaultdict(lambda: {"name": "", "amount": 0})
        for r in rows:
            amt = won(r.get(field) or 0, CHEON)
            o = by_off[r.get("OFFC_NM") or "미분류"]
            o["amount"] += amt
            o["programs"][(r.get("SACTV_NM"), r.get("PGM_NM"), r.get("FLD_NM"))] += amt
            sector_name = r.get("FLD_NM") or "미분류"
            code = str(r.get("FLD_CD") or sector_name)
            by_sector[code]["name"] = sector_name
            by_sector[code]["amount"] += amt
        items = []
        for name, o in sorted(by_off.items(), key=lambda kv: -kv[1]["amount"]):
            top = sorted(o["programs"].items(), key=lambda kv: -kv[1])[:10]
            items.append({"name": name, "amount": o["amount"],
                          "top_programs": [{"name": k[0], "program": k[1], "sector": k[2], "amount": v} for k, v in top]})
        return ({"basis": label, "items": items},
                {"basis": label, "items": [{"code": code, **value} for code, value in sorted(by_sector.items())]})

    for year, rows in te.items():
        if any(r.get("Y_YY_DFN_MEDI_KCUR_AMT") for r in rows):
            budget_years[year], sector_budgets[year] = budget_sections(
                rows, "Y_YY_DFN_MEDI_KCUR_AMT", "국회 확정 예산, 총지출 기준(세부사업 합계, 추경 미반영)")
        if any(r.get("Y_YY_MEDI_KCUR_AMT") for r in rows):
            proposal_years[year], sector_proposals[year] = budget_sections(
                rows, "Y_YY_MEDI_KCUR_AMT", "정부 예산안(국회 확정 예산과 별도)")
    ministry = None
    if budget_years:
        year = max(budget_years, key=int)
        ministry = {"year": year, **budget_years[year], "history": hist}
        later = [y for y in proposal_years if int(y) > int(year)]
        if later:
            py = max(later, key=int)
            ministry["proposal"] = {"year": py, **proposal_years[py]}
    elif hist:
        y = max(hist, key=int)
        ministry = {"year": y, "basis": hist[y]["basis"], "items": hist[y]["items"], "history": hist}
        notes.append("세부사업 자료를 받지 못해 부처별 상위 사업은 없다.")
    if ministry:
        ministry["budget_years"] = budget_years
        ministry["proposal_years"] = proposal_years
        out["expenditure_by_ministry"] = ministry
    out["expenditure_by_sector"]["budget_years"] = sector_budgets
    out["expenditure_by_sector"]["proposal_years"] = sector_proposals

    # 국가채무 + 재정수지
    debt = {}
    for rows in load("GovernmentDebtYear").values():
        for r in rows:
            debt[r["OJ_YY"]] = {"national_debt": won(r.get("GOD_SUM_AMT"), JO), "gdp_ratio_pct": r.get("GOD_GDP_CMPRT"),
                                "central": won(r.get("CENTRAL_DEPT_AMT"), JO), "local": won(r.get("LOCAL_DEPT_AMT"), JO),
                                "managed_balance": None, "integrated_balance": None}
    actual = {}
    for svc, fields in (("TotalIncome", {"total_revenue": "TOT_RV_AMT", "national_tax": "NTAX_RV_SUM_AMT", "non_tax": "TAX_EXPT_SUM_AMT", "fund_revenue": "FND_RV_SUM_AMT"}),
                        ("GrossExpend", {"total_expenditure": "TOT_EP_AMT", "budget_expenditure": "BDG_EP_SUM_AMT", "fund_expenditure": "FND_EP_AMT"}),
                        ("BudgetBalance", {"integrated_balance": "ITG_PFIN_RAD_AMT", "managed_balance": "MG_PFIN_RAD_AMT"})):
        for y, rows in load(svc).items():
            if not rows:
                continue
            last = max(rows, key=lambda r: int(r.get("OJ_M") or 0))  # 월별 누계 → 가장 늦은 달이 그해 누계
            a = actual.setdefault(y, {"through_month": int(last.get("OJ_M") or 0)})
            a["through_month"] = min(a["through_month"], int(last.get("OJ_M") or 0))
            for k, f in fields.items():
                a[k] = won(last.get(f), JO)
    for y, a in actual.items():
        if y in debt and a.get("through_month") == 12:
            debt[y]["managed_balance"] = a.get("managed_balance")
            debt[y]["integrated_balance"] = a.get("integrated_balance")
    out["debt"] = {"basis": "국가채무(D1) 연말 기준, 재정수지는 월간 재정동향 12월 누계", "years": debt}
    out["actuals"] = {"basis": "월간 재정동향 누계(집행 실적). through_month가 12가 아니면 그해 해당 월까지 누계", "years": actual}

    notes += [
        "예산과 결산은 다르다: 재정수입구조는 본예산, 16대 분야·국세수입·중앙관서별은 연도마다 예산 또는 결산(basis 참고), 월별 총수입·총지출은 실제 집행 누계다.",
        "총수입·총지출은 일반회계·특별회계·기금을 모두 더한 뒤 회계 사이 내부거래와 보전거래(국채 발행·상환 등)를 뺀 금액이라, 단순 세입·세출 합계보다 작다.",
        "국채로 빌린 돈은 총수입에 들어가지 않는다. 부족분은 국가채무(D1) 증가로 나타난다.",
        "세부사업 예산은 국회 확정 본예산 기준이라 추가경정예산이 반영되지 않았다.",
        "원자료가 조원 단위 소수 첫째 자리라 원 단위로 바꾼 금액도 1,000억원 단위로 반올림된 값이다.",
    ]
    out["notes"] = notes
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    (NORMALIZED / "fiscal.json").write_text(json.dumps(out, ensure_ascii=False))
    return out


def main():
    try:
        key = credentials.get("openfiscal_api_key")
    except credentials.MissingCredential as e:
        print(f"열린재정 수집 건너뜀: {e}", file=sys.stderr)
        manifest = {m["file"]: m for m in json.loads((OUT / "manifest.json").read_text())["files"]} if (OUT / "manifest.json").exists() else {}
    else:
        manifest = collect(Api(key))
    if manifest:
        normalize(manifest)
        print(f"wrote {(NORMALIZED / 'fiscal.json').relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
