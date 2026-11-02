"""탐지 규칙을 작은 가상 데이터로 검증한다 (숫자는 설명용 가상값)."""
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
        tx(1, "2024-09-20", 180000, attendees=4),  # 45,000/인 > 40,000 (개정 전)
        tx(2, "2024-09-23", 180000, attendees=4),  # 45,000/인 ≤ 50,000 (개정 후)
        tx(3, "2024-09-24", 120000, attendees=None),  # 인원 없음 → 계산 안 함
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
        tx(1, "2025-04-01", 66500, time="12:55"), tx(2, "2025-04-01", 3000, time="13:00"),  # 소액 추가 주문 → 제외
        tx(3, "2025-04-02", 300000, time="19:00"), tx(4, "2025-04-02", 250000, time="19:20"),  # 50만원 걸침
    ]
    f, _ = run(rows, "same_day_split")
    assert len(f) == 1
    assert f[0]["observed"]["occurrences"] == 1 and f[0]["observed"]["crosses500kCount"] == 1


def test_reversal_pairing_and_settlement_exclusion():
    rows = [
        tx(1, "2025-05-01", 80000), tx(2, "2025-05-03", -80000),  # 짝 있음
        tx(3, "2025-05-04", -50000, description="보증금 반환"),  # 정산성 반환 → 표시 안 함
        tx(4, "2025-05-05", -40000, description="결제 취소"),  # 짝 없음 → 표시
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
