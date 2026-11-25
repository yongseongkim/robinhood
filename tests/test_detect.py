"""가상 거래로 탐지 규칙의 경계값과 예외를 검증한다."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from common import day_info  # noqa: E402
from detect import Detector  # noqa: E402

SUBJECTS = [
    {"id": "gw-1", "type": "COUNCIL_ROLE", "name": "가상구의회 의장", "org": "가상구의회", "term_end": "2026-06-30"},
    {"id": "na-1", "type": "LEGISLATOR", "name": "가상", "terms": {"제21대": {}}},
]
MERCHANTS = [{"id": "m1", "name": "가상식당", "id_confidence": "HIGH"}, {"id": "m2", "name": "쿠팡", "id_confidence": "HIGH"}]


def tx(i, d, amount, **kw):
    e = {
        "id": f"t{i}", "source_id": "gwanak", "subject_id": "gw-1", "doc_id": "doc1", "funding_type": "COUNCIL_OPERATION",
        "date": d, "time": "12:00", "amount": amount, "description": "업무 간담회", "category": "식사",
        "payee_raw": "가상식당", "payee_display": "가상식당", "payee_type": "BUSINESS", "merchant_id": "m1",
        "attendees": 4, "payment_method": "신용카드", "quality": {"flags": []}, "payee_region": "서울 관악구",
    }
    e.update(kw)
    e.update(day_info(date.fromisoformat(e["date"])))
    return e


def run(rows, method, *args):
    d = Detector(rows, SUBJECTS, MERCHANTS)
    out = getattr(d, method)(*args)
    return d.findings, out


def test_meal_standard_uses_date_of_amendment():
    rows = [
        tx(1, "2024-09-20", 180000, attendees=4),  # 1인당 45,000원으로 개정 전 기준(40,000원)을 초과한다.
        tx(2, "2024-09-23", 180000, attendees=4),  # 같은 1인당 금액이 개정일에는 새 기준(50,000원) 이하다.
        tx(3, "2024-09-24", 120000, attendees=None),  # 인원이 없으면 1인당 금액을 계산할 수 없다.
    ]
    f, _ = run(rows, "meal_over_standard")
    assert len(f) == 1 and f[0]["evidenceIds"] == ["t1"]


def test_restricted_hours_and_days_skip_condolence_and_online():
    rows = [
        tx(1, "2025-03-04", 50000, time="23:30"),
        tx(2, "2025-03-08", 50000),  # 토요일
        tx(3, "2025-03-09", 50000, category="경조사"),  # 일요일 경조사 → 제외
        tx(4, "2025-03-09", 50000, payee_raw="쿠팡", merchant_id="m2", category="물품·구매"),  # 온라인 → 제외
    ]
    f, _ = run(rows, "restricted_hours_days")
    by_rule = {x["ruleId"]: x["evidenceIds"] for x in f}
    assert by_rule["RESTRICTED_HOURS"] == ["t1"]
    assert by_rule["RESTRICTED_DAYS"] == ["t2"]


def test_same_day_split_requires_similar_amounts_or_500k_crossing():
    rows = [
        tx(1, "2025-04-01", 66500, time="12:55"), tx(2, "2025-04-01", 3000, time="13:00"),  # 3,000원은 66,500원의 절반에 못 미치고 합계도 50만 원 미만이라 추가 주문으로 본다.
        tx(3, "2025-04-02", 300000, time="19:00"), tx(4, "2025-04-02", 250000, time="19:20"),  # 각 결제는 50만 원 미만이지만 같은 날 같은 가게에서 결제한 합계는 55만 원이다.
    ]
    f, _ = run(rows, "same_day_split")
    assert len(f) == 1
    assert f[0]["observed"]["occurrences"] == 1 and f[0]["observed"]["crosses500kCount"] == 1


def test_reversal_pairing_and_settlement_exclusion():
    rows = [
        tx(1, "2025-05-01", 80000), tx(2, "2025-05-03", -80000),  # 반환일 이틀 전 같은 주체가 같은 거래처에 지급한 8만 원과 짝이 맞는다.
        tx(3, "2025-05-04", -50000, description="보증금 반환"),  # 보증금 반환은 원거래를 찾지 못해도 정산성 반환으로 제외한다.
        tx(4, "2025-05-05", -40000, description="결제 취소"),  # 같은 금액의 원거래가 없는 결제 취소만 표시한다.
    ]
    f, pairs = run(rows, "reversals")
    assert pairs == {"t2": "t1"}
    assert len(f) == 1 and f[0]["evidenceIds"] == ["t4"]


def test_duplicates_ignore_masked_individuals():
    rows = [
        tx(1, "2025-06-01", 70000), tx(2, "2025-06-01", 70000),
        tx(3, "2025-06-02", 2500000, payee_type="INDIVIDUAL", payee_raw=None, payee_display="개인(비공개)", merchant_id=None),
        tx(4, "2025-06-02", 2500000, payee_type="INDIVIDUAL", payee_raw=None, payee_display="개인(비공개)", merchant_id=None),
    ]
    f, _ = run(rows, "duplicates")
    assert len(f) == 1 and sorted(f[0]["evidenceIds"]) == ["t1", "t2"]


def test_no_finding_carries_a_score():
    rows = [tx(i, f"2025-07-{i:02d}", 60000) for i in range(1, 25)]
    d = Detector(rows, SUBJECTS, MERCHANTS)
    d.run([])
    for f in d.findings:
        assert "score" not in f and "riskScore" not in f


def test_disclosure_gap_reports_unreconciled_attachment_and_missing_month(tmp_path, monkeypatch):
    import json
    import detect

    monkeypatch.setattr(detect, "COUNCILS", {"sample": "의회"})
    monkeypatch.setattr(detect, "RAW", tmp_path)
    monkeypatch.setattr(detect, "STAGING", tmp_path)
    (tmp_path / "sample").mkdir()
    manifest = [{"post_title": "2027년 1월"}, {"post_title": "2027년 3월"}]
    (tmp_path / "sample/manifest.json").write_text(json.dumps(manifest))
    item = {"file": "원장.pdf", "period": "2027-03", "status": "unparsed", "reason": "OCR 필요"}
    (tmp_path / "sample_parse_report.json").write_text(json.dumps([dict(item, doc_id=k) for k in ("a", "b", "c", "d")]))
    attempts = [dict(item, doc_id="a", reason="금액 합계 불일치"), dict(item, doc_id="b", status="parsed"),
                dict(item, doc_id="d", status="parsed", lastAttempt={"reason": "인쇄 합계 없음"})]
    (tmp_path / "sample_ocr_report.json").write_text(json.dumps({"files": attempts}))
    detector = Detector([], [], [])
    detector.disclosure_gap([])
    finding, = detector.findings
    assert finding["fundingType"] is None and finding["observed"]["missingMonths"] == ["2027-02"]
    assert finding["observed"]["problemFileCount"] == 3
    assert [f["issue"] for f in finding["observed"]["problemFiles"]] == [
        "금액 합계 불일치", "OCR 필요", "기존 OCR 결과 유지 · 재검증 보류(인쇄 합계 없음)"]
