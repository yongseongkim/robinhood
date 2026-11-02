import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from build_site import djb2, encode  # noqa: E402
from common import (address_region, council_category, day_info, display_bizno, mask_contacts, merchant_key,  # noqa: E402
                    parse_bizno, parse_period, period_range)


def test_parse_bizno_kinds():
    assert parse_bizno("120-81-12345") == ("120-81-12345", "CORPORATION")
    assert parse_bizno("1148112345") == ("114-81-12345", "CORPORATION")
    assert parse_bizno("114-22-76801") == ("114-22-76801", "SOLE_PROPRIETOR")
    assert parse_bizno("999-99-99999") == (None, None)


def test_parse_bizno_birthdate_means_individual():
    assert parse_bizno("1971-02-08 00:00:00") == (None, "INDIVIDUAL")
    assert parse_bizno("1960-06-04") == (None, "INDIVIDUAL")


def test_display_bizno_masks_sole_proprietors_only():
    assert display_bizno("114-22-76801", "SOLE_PROPRIETOR") == "114-22-*****"
    assert display_bizno("120-81-12345", "CORPORATION") == "120-81-12345"


def test_address_region_keeps_only_sigungu():
    assert address_region("서울특별시 관악구 관악로 145 (봉천동)") == "서울 관악구"
    assert address_region("서울 영등포구 도림천로 377") == "서울 영등포구"
    assert address_region("경상남도 창원시 성산구 대암로") == "경남 창원시"
    assert address_region("서울특별시영등포구의사당대로1") == "서울 영등포구"
    assert address_region(None) is None


def test_merchant_key_absorbs_notation_differences():
    assert merchant_key("(주)아성다이소") == merchant_key("주식회사 아성다이소") == merchant_key("아성다이소")
    assert merchant_key("고기킹（봉천점）") == merchant_key("고기킹(봉천점)")
    assert merchant_key("１４４１카페로스터스") == "1441카페로스터스"


def test_period_parsing():
    assert parse_period("2026년 7월 관악구의회 업무추진비") == "2026-07"
    assert parse_period("2022년 1/4분기 의정운영공통경비") == "2022-Q1"
    assert parse_period("2021년도 의회사무국 부서업무추진비") == "2021"
    assert period_range("2024-02") == ("2024-02-01", "2024-02-29")
    assert period_range("2021-Q4") == ("2021-10-01", "2021-12-31")
    assert period_range("2021") == ("2021-01-01", "2021-12-31")


def test_holidays_include_2026_new_public_holidays():
    assert day_info(date(2026, 5, 1))["holiday"]  # 노동절
    assert day_info(date(2026, 7, 17))["holiday"]  # 제헌절
    assert day_info(date(2024, 4, 10))["holiday"]  # 국회의원 선거일
    assert day_info(date(2024, 4, 13))["is_weekend"]


def test_mask_contacts():
    assert mask_contacts("9월 휴대폰 요금(010-1234-5678)") == "9월 휴대폰 요금(010-****-****)"
    assert mask_contacts("유선전화(031-763-1397)") == "유선전화(031-****-****)"
    assert mask_contacts("문의 a.b@example.com") == "문의 (이메일 비공개)"
    assert mask_contacts("2024-05-29 지급") == "2024-05-29 지급"


def test_council_category():
    assert council_category("남원골추어탕", "의정활동 및 의회운영 관련 업무유대 경비") == "식사"
    assert council_category("스타벅스", "간담회") == "카페·다과"
    assert council_category("하이보", "제315회 임시회 간담회") == "간담회(업종 미확인)"
    assert council_category(None, "의장 의회운영업무추진 이재민 위문금 지급") == "성금·회비·격려금"
    assert council_category("도○청과", "부속실 직원 격려") == "물품·구매"
    assert council_category(None, "경조사비") == "경조사"


def test_djb2_matches_browser_implementation():
    ids = ["b1168300083", "n5a2f482b9f", "b2138152063"]
    js = ("const f=(id)=>{let h=5381;for(let i=0;i<id.length;i++)h=((h*33)^id.charCodeAt(i))>>>0;return h%256};"
          f"console.log(JSON.stringify({ids!r}.map(f)))").replace("'", '"')
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert [int(x) for x in out.strip()[1:-1].split(",")] == [djb2(i) for i in ids]


def test_encode_roundtrip():
    cols = ["id", "cat", "amt", "flags"]
    rows = [["a", "식사", 100, []], ["b", "식사", 200, ["X"]], ["c", None, 300, None]]
    enc = encode(rows, cols, ["cat", "flags"])
    dec = []
    for r in enc["rows"]:
        o = {}
        for i, c in enumerate(cols):
            v = r[i] if i < len(r) else None
            o[c] = enc["dict"][c][v] if c in enc["dict"] and v is not None else v
        dec.append(o)
    assert dec[0] == {"id": "a", "cat": "식사", "amt": 100, "flags": None}
    assert dec[1]["flags"] == ["X"]
    assert dec[2]["cat"] is None


def test_role_holder_periods_leave_gaps_unknown(tmp_path, monkeypatch):
    import json
    import normalize
    holders = [
        {"source_id": "gw", "role": "의장", "term_label": "제9대 후반기", "name": "가", "start": "2024-10-04",
         "confidence": "HIGH", "source_url": "u"},
        {"source_id": "gw", "role": "의장", "term_label": "제9대 후반기", "name": "나", "start": "2025-07-01",
         "confidence": "HIGH", "source_url": "u"},
    ]
    (tmp_path / "role_holders.json").write_text(json.dumps(holders, ensure_ascii=False))
    monkeypatch.setattr(normalize, "STAGING", tmp_path)
    subjects = {"s": {"type": "COUNCIL_ROLE", "org_source": "gw", "role": "의장", "term": "제9대 후반기",
                      "term_start": "2024-07-01", "term_end": "2026-06-30"}}
    assert normalize.attach_role_holders(subjects) == 1
    got = [(h["name"], h["period_start"], h["period_end"]) for h in subjects["s"]["holders"]]
    assert got == [(None, "2024-07-01", "2024-10-03"), ("가", "2024-10-04", "2025-06-30"), ("나", "2025-07-01", "2026-06-30")]


def test_meeting_expense_wording_is_not_dues():
    assert council_category("창고43시청점", "상임위원회 소관 연구 및 정책개발을 위한 간담회비 지급") == "간담회(업종 미확인)"
    assert council_category("폴 바셋 서소문점", "대표의원 의정활동 관련 차담회비 지급") == "카페·다과"
    assert council_category(None, "2024년도 적십자 특별회비 납부") == "성금·회비·격려금"


def test_split_name_address():
    from common import split_name_address
    assert split_name_address("브이아이피참치서울특별시 중구 세종대로") == ("브이아이피참치", "서울특별시 중구 세종대로")
    assert split_name_address("서울시청매점") == ("서울시청매점", None)


def test_region_key_folds_general_districts():
    from councils import region_key
    assert region_key("경기", "수원시장안구") == "경기 수원시"
    assert region_key("서울", "관악구") == "서울 관악구"
    assert region_key("경북", "울릉군") == "경북 울릉군"


def test_jurisdiction_includes_point_contact_neighbors():
    from councils import jurisdiction_areas, load_registry
    area = jurisdiction_areas(load_registry())["gwanak"]
    assert {"서울 관악구", "서울 동작구", "서울 영등포구", "경기 안양시", "경기 과천시"} <= area
    assert "서울 강남구" not in area


def test_cross_document_duplicates_are_marked_once():
    import normalize
    base = {"source_id": "gw", "subject_id": "s", "date": "2023-01-06", "time": None, "amount": 85000, "payee_raw": None,
            "description": "간담회"}
    rows = [dict(base, id="a", doc_id="d1", quality={"flags": []}),
            dict(base, id="b", doc_id="d2", quality={"flags": []}),   # 다른 파일에 다시 실림 → 합계 제외
            dict(base, id="c", doc_id="d1", quality={"flags": []})]   # 같은 파일 안 반복 → 실제 반복일 수 있어 유지
    normalize.mark_cross_document_duplicates(rows)
    assert [r.get("duplicate_of") for r in rows] == [None, "a", None]


def test_credential_env_override_skips_sops(monkeypatch):
    import credentials
    monkeypatch.setenv("ASSEMBLY_API_KEY", "from-env")
    assert credentials.get("assembly_api_key") == "from-env"


def test_assembly_matching_helpers():
    from assembly import base_name, district_rest, result_group
    assert base_name("김병욱(성)") == "김병욱"
    assert district_rest("전남광주통합특별시 해남군완도군진도군") == district_rest("전남 해남군완도군진도군")
    assert result_group("대안반영폐기") == "대안에 반영"
    assert result_group(None) == "심사 중"
