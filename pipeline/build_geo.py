"""행정구역·국회의원 선거구 경계 → site/data/geo.js (미리 투영한 SVG path)

브라우저에서 지도 라이브러리 없이 <path d=...>만 그리도록, 경계를 EPSG:5179(UTM-K)로 투영한 뒤
고정 viewBox 좌표로 바꿔 저장한다. 이웃 경계가 벌어지지 않도록 위상(topology)을 보존하며 단순화한다.

원자료 (data/raw/geo/, manifest.json에 URL·라이선스·sha256 기록)
  admdongkor_HangJeongDong_ver20261001.geojson  행정동 경계 2026-10-01 (vuski/admdongkor, CC BY 4.0 + 공공누리 1유형, 원자료 통계청 SGIS)
  ohmynews_2024_22_Elec_simplify.json          제22대 국회의원 지역구 254 (OhmyNews/2024_22_elec_map, MIT)
  ohmynews_2020_21_elec_253_simple.json        제21대 국회의원 지역구 253 (OhmyNews/2020_21_elec_map, MIT)

출력 RH.data("geo", {...})
  projection   투영·viewBox 설명
  sido         시·도 (현재 행정구역 기준)
  sigungu      시·군·구(일반구 포함) + 경계를 접한 시·군·구 목록(adjacent)
  seoul        서울 25개 구 (별도 확대 viewBox)
  districts    제22대 지역구 / seoulDistricts: 서울 지역구(확대 viewBox) / districts21: 제21대 지역구
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import topojson as tp
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
import numpy as np
import requests
import shapely
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "geo"
OUT = ROOT / "site" / "data" / "geo.js"
KST = timezone(timedelta(hours=9))

ADMDONG = RAW / "admdongkor_HangJeongDong_ver20261001.geojson"
ELEC22 = RAW / "ohmynews_2024_22_Elec_simplify.json"
ELEC21 = RAW / "ohmynews_2020_21_elec_253_simple.json"

SOURCES = [
    {"file": ADMDONG.name, "url": "https://raw.githubusercontent.com/vuski/admdongkor/master/ver20261001/HangJeongDong_ver20261001.geojson",
     "license": "CC BY 4.0 (가공: vuski/admdongkor) + 공공누리 제1유형(원자료: 통계청 SGIS)",
     "attribution": "본 데이터는 통계청 통계지리정보서비스(SGIS, https://sgis.kostat.go.kr)에서 공공누리 제1유형으로 개방한 행정동 경계를 가공한 것이며"
                    "(가공: vuski/admdongkor, https://github.com/vuski/admdongkor), CC BY 4.0으로 배포됩니다."},
    {"file": "admdongkor_LICENSE-DATA", "url": "https://github.com/vuski/admdongkor/blob/master/LICENSE-DATA", "license": "라이선스 원문"},
    {"file": ELEC22.name, "url": "https://github.com/OhmyNews/2024_22_elec_map/blob/main/2024_22_Elec_simplify.json",
     "license": "MIT (Copyright (c) 2024 오마이뉴스)",
     "attribution": "제22대 총선 선거구 지도: 오마이뉴스 (https://github.com/OhmyNews/2024_22_elec_map), 통계청 행정동 경계를 254개 선거구로 dissolve"},
    {"file": "ohmynews_22_Elec_SGG.csv", "url": "https://github.com/OhmyNews/2024_22_elec_map/blob/main/22_Elec_SGG.csv", "license": "MIT"},
    {"file": "ohmynews_2024_22_README.md", "url": "https://github.com/OhmyNews/2024_22_elec_map/blob/main/README.md", "license": "MIT"},
    {"file": "ohmynews_2024_22_LICENSE", "url": "https://github.com/OhmyNews/2024_22_elec_map/blob/main/LICENSE", "license": "라이선스 원문"},
    {"file": ELEC21.name, "url": "https://github.com/OhmyNews/2020_21_elec_map/blob/master/2020_21_elec_253_simple.json",
     "license": "MIT (Copyright (c) 2020 오마이뉴스)",
     "attribution": "제21대 총선 선거구 지도: 오마이뉴스 (https://github.com/OhmyNews/2020_21_elec_map)"},
    {"file": "ohmynews_2020_21_README.md", "url": "https://github.com/OhmyNews/2020_21_elec_map/blob/master/readme.md", "license": "MIT"},
    {"file": "ohmynews_2020_21_LICENSE", "url": "https://github.com/OhmyNews/2020_21_elec_map/blob/master/LICENSE", "license": "라이선스 원문"},
]

SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북",
    "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주", "전남광주통합특별시": "전남광주",
}
# 2026-07-01 광주광역시·전라남도 통합. 통합 시·도 안에서 옛 광주광역시 자치구 (2024년 선거구·주소 표기와 맞추기 위한 옛 이름)
MERGED_SIDO = "전남광주통합특별시"
FORMER_GWANGJU_GU = {"동구", "서구", "남구", "북구", "광산구"}

NATIONAL_WIDTH = 1000
SEOUL_WIDTH = 1000
PAD = 12
TOL_NATIONAL = 300    # m, 위상 보존 단순화 허용오차 (전국 축척)
TOL_SEOUL = 18        # m (서울 확대)
MIN_PART_NATIONAL = 1.2  # viewBox 단위² 미만의 작은 섬 조각은 제외 (울릉군=독도 포함은 항상 유지)
MIN_PART_SEOUL = 0.5

_tr = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_to4326 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)


def to5179(coords):
    x, y = _tr.transform(coords[:, 0], coords[:, 1])
    return np.column_stack([x, y])


def download_url(url):
    """GitHub blob pages in provenance metadata need raw content for downloads."""
    prefix = "https://github.com/"
    if url.startswith(prefix):
        return "https://raw.githubusercontent.com/" + url[len(prefix):].replace("/blob/", "/", 1)
    return url


def fetch_missing_sources():
    """Bootstrap map inputs on an empty deployment; retain existing originals."""
    RAW.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for source in SOURCES:
        target = RAW / source["file"]
        if target.is_file() and target.stat().st_size:
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=RAW, prefix=".geo-", suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                with requests.get(download_url(source["url"]), stream=True, timeout=120) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        output.write(chunk)
            if not temporary.stat().st_size:
                raise ValueError(f"Empty map source: {source['file']}")
            if target.suffix in {".json", ".geojson"}:
                data = json.loads(temporary.read_text())
                if (
                    not isinstance(data, dict)
                    or data.get("type") != "FeatureCollection"
                    or not isinstance(data.get("features"), list)
                    or not data["features"]
                ):
                    raise ValueError(f"Invalid map source: {source['file']}")
            os.replace(temporary, target)
            downloaded += 1
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return downloaded


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_manifest():
    out = []
    for s in SOURCES:
        p = RAW / s["file"]
        if not p.exists():
            continue
        out.append({**s, "local_path": str(p.relative_to(ROOT)), "sha256": sha256(p), "bytes": p.stat().st_size,
                    "fetched_at": datetime.fromtimestamp(p.stat().st_mtime, KST).isoformat(timespec="seconds")})
    (RAW / "manifest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


def clean(g):
    g = g if g.is_valid else g.buffer(0)
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    if isinstance(g, MultiPolygon):
        return g
    polys = [p for p in getattr(g, "geoms", []) if isinstance(p, (Polygon, MultiPolygon))]
    return MultiPolygon([q for p in polys for q in (p.geoms if isinstance(p, MultiPolygon) else [p])])


def project(geojson_geom):
    return clean(shapely.transform(shape(geojson_geom), to5179))


def topo_simplify(geoms, tol):
    """이웃이 공유하는 경계선을 한 번만 단순화해 틈·겹침이 생기지 않게 한다."""
    feats = [{"type": "Feature", "properties": {"i": i}, "geometry": mapping(g)} for i, g in enumerate(geoms)]
    topo = tp.Topology({"type": "FeatureCollection", "features": feats}, prequantize=False, toposimplify=tol,
                       simplify_algorithm="dp", prevent_oversimplify=True)
    out = [None] * len(geoms)
    for f in json.loads(topo.to_geojson())["features"]:
        out[f["properties"]["i"]] = clean(shape(f["geometry"])) if f["geometry"] else MultiPolygon()
    return out


class Frame:
    """EPSG:5179 미터 좌표 → SVG viewBox 좌표 (y축 뒤집기)."""

    def __init__(self, bounds, width):
        minx, miny, maxx, maxy = bounds
        self.s = (width - 2 * PAD) / (maxx - minx)
        self.minx, self.maxy = minx, maxy
        self.w = width
        self.h = round((maxy - miny) * self.s + 2 * PAD, 1)

    def xy(self, x, y):
        return round(PAD + (x - self.minx) * self.s, 1), round(PAD + (self.maxy - y) * self.s, 1)

    def viewbox(self):
        return f"0 0 {self.w} {self.h}"


def fmt(v):
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return s.replace("0.", ".", 1) if s.startswith("0.") else s.replace("-0.", "-.", 1)


def ring_path(coords, fr):
    pts = []
    for x, y in coords:
        p = fr.xy(x, y)
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return ""
    out = [f"M{fmt(pts[0][0])} {fmt(pts[0][1])}l"]
    deltas = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        deltas.append(f"{fmt(round(bx - ax, 1))} {fmt(round(by - ay, 1))}")
    out.append(" ".join(deltas).replace(" -", "-"))
    out.append("z")
    return "".join(out)


def geom_path(g, fr, min_part, keep_all=False):
    parts = []
    for poly in sorted(g.geoms, key=lambda p: -p.area):
        if not keep_all and poly.area * fr.s * fr.s < min_part and parts:
            continue
        rings = [poly.exterior] + [r for r in poly.interiors if Polygon(r).area * fr.s * fr.s >= min_part]
        parts.extend(p for p in (ring_path(r.coords, fr) for r in rings) if p)
    return "".join(parts)


def label_point(g, fr):
    largest = max(g.geoms, key=lambda p: p.area)
    pt = largest.representative_point()
    return fr.xy(pt.x, pt.y)


def adjacency(items, touches=None):
    """경계를 접한 시·군·구 (선 접촉: 20m 버퍼끼리 겹친 면적 > 2,000㎡).
    점으로만 맞닿은 경우(예: 관악구-영등포구)는 touches에 따로 담는다."""
    geoms = [it["geom"] for it in items]
    tree = STRtree(geoms)
    adj = defaultdict(set)
    for i, g in enumerate(geoms):
        gb = g.buffer(20)
        for j in tree.query(gb):
            j = int(j)
            if j <= i:
                continue
            overlap = gb.intersection(geoms[j].buffer(20)).area
            if overlap > 2000:
                adj[i].add(j)
                adj[j].add(i)
            elif overlap > 0 and touches is not None:
                touches[i].add(j)
                touches[j].add(i)
    return adj


SIDO_PREFIX = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\s*(.*)$")


def district_key(sido, name):
    """선거구 이름 비교용 키: '경기 동두천시양주시연천군갑' == '경기 동두천양주연천갑', '세종특별자치시갑' == '세종 세종갑'."""
    name = re.sub(r"선거구$", "", re.sub(r"^(세종)?특별자치시", "세종", name.strip()))
    return sido + " " + re.sub(r"[시군구\s]", "", name)


def split_district(d):
    """'경기안양시만안구'처럼 시·도 뒤 공백이 없는 표기도 나눈다."""
    m = SIDO_PREFIX.match(d.strip())
    return (m.group(1), m.group(2)) if m and m.group(2) else (None, None)


def legislator_districts():
    p = ROOT / "data" / "normalized" / "subjects.json"
    if not p.exists():
        return {}, {}
    by = {"제22대": {}, "제21대": {}}
    for s in json.loads(p.read_text()):
        if s.get("type") != "LEGISLATOR":
            continue
        for term, info in (s.get("terms") or {}).items():
            d = (info or {}).get("district")
            if term in by and d and d != "비례대표":
                sido, rest = split_district(d)
                if sido:
                    by[term].setdefault(district_key(sido, rest), d)
    return by["제22대"], by["제21대"]


def main(*, fetch_missing=True):
    if fetch_missing:
        fetch_missing_sources()
    write_manifest()

    # ---- 시·군·구: 행정동 → 시·군·구 dissolve
    print("loading admdong…", file=sys.stderr)
    adm = json.loads(ADMDONG.read_text())
    groups, meta = defaultdict(list), {}
    for f in adm["features"]:
        p = f["properties"]
        groups[p["sgg"]].append(project(f["geometry"]))
        meta[p["sgg"]] = (p["sido"], p["sidonm"], p["sggnm"])
    sgg_items = []
    for code in sorted(groups):
        sido_code, sidonm, sggnm = meta[code]
        short = SIDO_SHORT[sidonm]
        legacy = short
        if sidonm == MERGED_SIDO:
            legacy = "광주" if sggnm in FORMER_GWANGJU_GU else "전남"
        sgg_items.append({"code": code, "sido_code": sido_code, "sidonm": sidonm, "sido_short": short, "sgg": sggnm,
                          "name": f"{short} {sggnm}", "legacy_name": f"{legacy} {sggnm}",
                          "geom": clean(unary_union(groups[code]))})
    print(f"sigungu: {len(sgg_items)}", file=sys.stderr)

    # ---- 시·도
    sido_groups = defaultdict(list)
    for it in sgg_items:
        sido_groups[(it["sido_code"], it["sidonm"])].append(it["geom"])
    sido_items = [{"code": c, "name": n, "short": SIDO_SHORT[n], "geom": clean(unary_union(gs))}
                  for (c, n), gs in sorted(sido_groups.items())]

    # ---- 인접
    touch = defaultdict(set)
    adj = adjacency(sgg_items, touch)

    # ---- 선거구
    k22, k21 = legislator_districts()
    e22 = json.loads(ELEC22.read_text())["features"]
    d22 = []
    for f in e22:
        p = f["properties"]
        sido, sgg = p["SIDO"], p["SGG"]
        key = district_key(sido, sgg)
        d22.append({"code": str(p["SGG_Code"]), "short": p["SIDO_SGG"], "sido": sido, "key": key,
                    "name": k22.get(key, p["SIDO_SGG"]), "matched": key in k22, "geom": project(f["geometry"])})
    e21 = json.loads(ELEC21.read_text())["features"]
    d21 = []
    for f in e21:
        p = f["properties"]
        sido, rest = split_district(p["SGG_3"])
        key = district_key(sido, rest)
        d21.append({"code": str(p["SGG_Code"]), "short": p["SGG_3"], "sido": sido, "key": key,
                    "name": k21.get(key, p["SGG_3"]), "matched": key in k21, "geom": project(f["geometry"])})

    # ---- 단순화 (위상 보존)
    print("simplifying…", file=sys.stderr)
    nat_sgg = topo_simplify([it["geom"] for it in sgg_items], TOL_NATIONAL)
    nat_sido = topo_simplify([it["geom"] for it in sido_items], TOL_NATIONAL)
    nat_d22 = topo_simplify([it["geom"] for it in d22], TOL_NATIONAL)
    nat_d21 = topo_simplify([it["geom"] for it in d21], TOL_NATIONAL)
    seoul_sgg_items = [it for it in sgg_items if it["sido_short"] == "서울"]
    seoul_d22_items = [it for it in d22 if it["sido"] == "서울"]
    seo_sgg = topo_simplify([it["geom"] for it in seoul_sgg_items], TOL_SEOUL)
    seo_d22 = topo_simplify([it["geom"] for it in seoul_d22_items], TOL_SEOUL)

    # ---- 투영 틀
    allb = unary_union([it["geom"] for it in sido_items]).bounds
    nat = Frame(allb, NATIONAL_WIDTH)
    seo = Frame(unary_union([it["geom"] for it in seoul_sgg_items]).bounds, SEOUL_WIDTH)

    def entry(it, g, fr, min_part, extra):
        cx, cy = label_point(it["geom"], fr)
        keep_all = it.get("sgg") == "울릉군"  # 독도처럼 작은 섬도 반드시 표시
        point = max(it["geom"].geoms, key=lambda part: part.area).representative_point()
        lng, lat = _to4326.transform(point.x, point.y)
        return {**extra, "d": geom_path(g, fr, min_part, keep_all), "cx": cx, "cy": cy,
                "lat": round(lat, 6), "lng": round(lng, 6)}

    idx = {i: it["code"] for i, it in enumerate(sgg_items)}
    out = {
        "projection": {
            "crs": "EPSG:5179 (Korea 2000 / Unified CS, UTM-K)",
            "national": {"viewBox": nat.viewbox(), "metersPerUnit": round(1 / nat.s, 2)},
            "seoul": {"viewBox": seo.viewbox(), "metersPerUnit": round(1 / seo.s, 2)},
            "boundaryDate": "2026-10-01",
            "notes": [
                "행정구역은 2026-10-01 기준입니다. 2026-07-01 광주광역시와 전라남도가 전남광주통합특별시로 통합되었고, "
                "인천 중구·동구·서구가 영종구·제물포구·서해구·검단구로 개편되었습니다.",
                "legacy_name은 2024년 선거구·주소 표기(광주/전남)와 맞추기 위한 옛 시·도 약칭입니다.",
                "adjacent는 실제 경계를 접한 시·군·구입니다(바다 건너는 제외).",
                f"단순화 허용오차: 전국 {TOL_NATIONAL}m, 서울 확대 {TOL_SEOUL}m. 위상 보존 단순화로 이웃 경계가 일치합니다.",
            ],
            "sources": [{k: s[k] for k in ("url", "license", "attribution") if k in s} for s in SOURCES if "attribution" in s],
        },
        "sido": [entry(it, g, nat, MIN_PART_NATIONAL, {"code": it["code"], "name": it["name"], "short": it["short"],
                                                        **({"legacy": ["광주", "전남"]} if it["name"] == MERGED_SIDO else {})})
                 for it, g in zip(sido_items, nat_sido)],
        "sigungu": [entry(it, g, nat, MIN_PART_NATIONAL, {
            "code": it["code"], "name": it["name"], "legacy_name": it["legacy_name"], "sido_short": it["sido_short"],
            "sgg": it["sgg"], "adjacent": sorted(idx[j] for j in adj[i]),
            "touches": sorted(idx[j] for j in touch[i])})
            for i, (it, g) in enumerate(zip(sgg_items, nat_sgg))],
        "seoul": [entry(it, g, seo, MIN_PART_SEOUL, {"code": it["code"], "name": it["name"], "sgg": it["sgg"]})
                  for it, g in zip(seoul_sgg_items, seo_sgg)],
        "districts": [entry(it, g, nat, MIN_PART_NATIONAL, {"code": it["code"], "name": it["name"], "short": it["short"],
                                                             "key": it["key"], "matched": it["matched"]})
                      for it, g in zip(d22, nat_d22)],
        "seoulDistricts": [entry(it, g, seo, MIN_PART_SEOUL, {"code": it["code"], "name": it["name"], "short": it["short"]})
                           for it, g in zip(seoul_d22_items, seo_d22)],
        "districts21": [entry(it, g, nat, MIN_PART_NATIONAL, {"code": it["code"], "name": it["name"], "short": it["short"],
                                                               "key": it["key"], "matched": it["matched"]})
                        for it, g in zip(d21, nat_d21)],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(f'RH.data("geo",{body});\n', encoding="utf-8")
    print(f"geo.js {len(body) / 1e6:.2f} MB: sido {len(out['sido'])}, sigungu {len(out['sigungu'])}, seoul {len(out['seoul'])}, "
          f"districts {len(out['districts'])} (matched {sum(d['matched'] for d in out['districts'])}), "
          f"districts21 {len(out['districts21'])} (matched {sum(d['matched'] for d in out['districts21'])})", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build map data from public source files.")
    parser.add_argument("--no-fetch", action="store_true", help="Use existing originals without downloading")
    arguments = parser.parse_args()
    main(fetch_missing=not arguments.no_fetch)
