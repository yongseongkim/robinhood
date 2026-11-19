"""Normalize public Assembly and boundary labels while preserving the province."""
import re

FULL_NAMES = {
    "전남광주통합특별시": "전남광주", "서울특별시": "서울", "세종특별자치시": "세종",
    "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "전남광주",
    "대전광역시": "대전", "울산광역시": "울산", "경기도": "경기", "강원특별자치도": "강원",
    "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
    "전라북도": "전북", "전라남도": "전남광주", "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주", "제주도": "제주",
}
PROVINCES = re.compile("|".join(sorted(set(FULL_NAMES) | set(FULL_NAMES.values()) | {"전남", "광주"}, key=len, reverse=True)))


def region_label(label):
    value = (label or "").strip()
    match = PROVINCES.match(value)
    if not match:
        return value
    province = FULL_NAMES.get(match[0], match[0])
    if province in ("전남", "광주"):
        province = "전남광주"
    return (province + " " + value[match.end():].strip()).strip()


def seat_key(label):
    value = region_label(label)
    province, _, rest = value.partition(" ")
    if not PROVINCES.fullmatch(province):
        return "비례대표" if value == "비례" else value
    rest = rest.removesuffix("선거구")
    if province == "세종":
        rest = rest.removeprefix("세종").removeprefix("특별자치시")
    return province + " " + re.sub(r"[시군구\s]", "", rest)
