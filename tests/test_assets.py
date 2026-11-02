import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from parse_assets import amount, areas, location  # noqa: E402


def test_location_keeps_only_up_to_eupmyeondong():
    # 지번·건물명·동호수는 버린다
    assert location("서울특별시 노원구 하계1동 이코아빌 건물 146.69㎡") == ("서울", "노원구", "하계1동")
    assert location("경기도 양평군 단월면 봉상리 산 102-1번지 18,471.00㎡") == ("경기", "양평군", "단월면")
    assert location("경기도 용인시 처인구 포곡읍 신원리 임대보증금") == ("경기", "용인시 처인구", "포곡읍")
    assert location("세종특별자치시 대평동 해들마을3단지 건물 50.34㎡") == ("세종", None, "대평동")
    assert location("서울시 송파구 올림픽로33길 17 건물 0.00㎡")[:2] == ("서울", "송파구")
    assert location("일본 치바현 나가레야마시 건물 28.05㎡")[0] == "해외·기타"


def test_amount_reads_first_line_only():
    assert amount("1,332,968") == 1332968
    assert amount("-30,501") == -30501
    assert amount("10,370\n(3,000)") == 10370  # 괄호는 실거래가격
    assert amount("-") is None and amount(None) is None


def test_areas():
    assert areas("서울특별시 노원구 중계동 건영아파트상가 대지 259.32㎡ 건물 370.60㎡") == ["대지 259.32㎡", "건물 370.60㎡"]
