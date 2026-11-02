"""지방의회 출처 레지스트리와 관할 지역.

기본 3곳(서울특별시의회·관악·마포) + data/staging/councils/<slug>.json (구의회 수집기가 추가).
관할 지역은 site/data/geo.js의 시·군·구 경계 인접 정보로 계산한다 (없으면 기본값).
"""
import json
import re

from common import SITE, STAGING

BUILTIN = {
    "seoul": {"name": "서울특별시의회", "region": "서울", "level": "광역", "term_base_2018": 10,
              "board": "https://www.smc.seoul.kr/board/BoardList.do?boardTypeId=158&menuId=001007013001"},
    "gwanak": {"name": "관악구의회", "region": "서울 관악구", "level": "기초", "term_base_2018": 8,
               "board": "https://www.ga21c.seoul.kr/kr/costBBS.do"},
    "mapo": {"name": "마포구의회", "region": "서울 마포구", "level": "기초", "term_base_2018": 8,
             "board": "https://council.mapo.seoul.kr/kr/news/bbsCost.do"},
}

# geo.js가 없을 때 쓰는 기본 관할 (근무지 + 경계를 접한 시·군·구)
FALLBACK_AREA = {
    "gwanak": {"서울 관악구", "서울 동작구", "서울 서초구", "서울 금천구", "서울 구로구", "서울 영등포구", "경기 안양시", "경기 과천시"},
    "seoul": {"서울", "경기 고양시", "경기 김포시", "경기 부천시", "경기 광명시", "경기 안양시", "경기 과천시", "경기 성남시", "경기 하남시",
              "경기 구리시", "경기 남양주시", "경기 의정부시", "경기 양주시", "인천 계양구"},
}


def load_registry():
    reg = {k: dict(v, source_id=k) for k, v in BUILTIN.items()}
    folder = STAGING / "councils"
    if folder.exists():
        for p in sorted(folder.glob("*.json")):
            d = json.loads(p.read_text())
            sid = d["source_id"]
            reg.setdefault(sid, {"source_id": sid, "level": "기초"}).update({
                "name": d["name"], "region": d["region"], "board": d.get("board_url"),
                "term_base_2018": d.get("term_base_2018", 8), "formats": d.get("formats"), "notes": d.get("notes"),
                "collected_from": d.get("collected_from"), "collected_to": d.get("collected_to"),
            })
    return reg


def load_geo():
    path = SITE / "data" / "geo.js"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    body = text[text.index(",") + 1: text.rstrip().rstrip(";").rstrip().rindex(")")]
    return json.loads(body)


def region_key(sido_short, sgg):
    """'경기', '수원시장안구' → '경기 수원시' (주소에서 뽑는 address_region과 같은 단위)."""
    m = re.match(r"^([가-힣]+?시)[가-힣]+구$", sgg or "")
    return f"{sido_short} {m.group(1) if m else sgg}"


def jurisdiction_areas(registry):
    """의회별로 '근무지와 경계를 접한 시·군·구까지'(회계관리 훈령)에 해당하는 지역 키 집합.
    광역의회는 훈령에 범위가 명시되어 있지 않아 같은 방식(시·도 + 경계를 접한 시·군)을 준용한다."""
    geo = load_geo()
    if not geo or not geo.get("sigungu"):
        return dict(FALLBACK_AREA)
    feats = geo["sigungu"]
    by_code = {f["code"]: f for f in feats}
    key = {f["code"]: region_key(f.get("sido_short"), f.get("sgg")) for f in feats}
    areas = {}
    for sid, c in registry.items():
        region = c["region"]
        if " " in region:  # 기초: 같은 시·군·구(일반구 포함) 폴리곤과 그 이웃
            own = [f for f in feats if key[f["code"]] == region]
        else:  # 광역: 시·도 전체와 그 바깥 이웃
            own = [f for f in feats if f.get("sido_short") == region]
        if not own:
            if sid in FALLBACK_AREA:
                areas[sid] = FALLBACK_AREA[sid]
            continue
        area = {region}
        for f in own:
            area.add(key[f["code"]])
            # 한 점으로만 맞닿은 경우(touches)도 '경계를 접한' 것으로 본다 — 표시를 덜 하는 쪽(보수적) 해석
            for a in f.get("adjacent", []) + f.get("touches", []):
                if a in by_code:
                    area.add(key[a])
        areas[sid] = area
    return areas
