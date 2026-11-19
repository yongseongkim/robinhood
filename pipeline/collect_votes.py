"""열린국회정보 본회의 표결 수집 → data/raw/assembly/votes/<대수>/<BILL_ID>.json

- 처리 의안 목록(ncocpgfiaoituanbr)으로 본회의에서 처리된 의안을 찾고,
  의안마다 의원별 표결(nojepdqqaweusdfbi)을 1회 호출로 받는다 (의원 약 300명이 한 번에 옴).
- 이미 받은 의안은 건너뛰므로 중간에 멈춰도 이어받고, 새 의안만 더 받는다.
- 1초에 1회 이하로 천천히 요청하고, 오류가 연속되면 멈춘다. 인증키는 기록하지 않는다.
"""
from datetime import date, timedelta
import json
import sys
import time

import requests

import credentials
from common import RAW
from source_status import atomic_bytes, check_source

BASE = "https://open.assembly.go.kr/portal/openapi/"
OUT = RAW / "assembly" / "votes"
PAUSE = 1.0


def get(session, key, service, **params):
    for attempt in range(4):
        try:
            r = session.get(BASE + service, params={"KEY": key, "Type": "json", **params}, timeout=60)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            wait = 5 * (attempt + 1)
            print(f"  재시도 {attempt + 1} ({type(e).__name__}) {wait}s 후", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"{service} 요청이 계속 실패함")


def processed_bills(session, key, age):
    rows, page = [], 1
    while True:
        d = get(session, key, "ncocpgfiaoituanbr", AGE=age, pIndex=page, pSize=1000).get("ncocpgfiaoituanbr")
        if not d:
            raise RuntimeError("처리 의안 목록 응답 누락")
        total = d[0]["head"][0]["list_total_count"]
        batch = d[1]["row"] if len(d) > 1 else []
        if not batch and len(rows) < total:
            raise ValueError("처리 의안 목록 일부 누락")
        rows += batch
        if len(rows) >= total:
            break
        page += 1
        time.sleep(PAUSE)
    if len(rows) != total or len({r["BILL_ID"] for r in rows}) != total:
        raise ValueError("처리 의안 목록 일부 중복 또는 누락")
    keep = ("BILL_ID", "BILL_NO", "BILL_NAME", "PROC_DT", "PROC_RESULT_CD", "CURR_COMMITTEE", "MEMBER_TCNT", "VOTE_TCNT",
            "YES_TCNT", "NO_TCNT", "BLANK_TCNT", "LINK_URL")
    return [{k: r.get(k) for k in keep} for r in rows]


def main():
    key = credentials.get("assembly_api_key")
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh) robinhood-collector"
    for age in (22, 21):
        folder = OUT / str(age)
        folder.mkdir(parents=True, exist_ok=True)
        bills = processed_bills(s, key, age)
        atomic_bytes(OUT / f"processed_{age}.json", json.dumps(bills, ensure_ascii=False).encode())
        recent = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
        todo = []
        for b in bills:
            path = folder / f"{b['BILL_ID']}.json"
            if not path.exists() or (str(b.get("PROC_DT") or "").replace("-", "") >= recent
                                     and not json.loads(path.read_text()).get("votes")):
                todo.append(b)
        print(f"제{age}대 처리 의안 {len(bills)}건, 새로 받을 표결 {len(todo)}건", file=sys.stderr)
        for i, b in enumerate(todo, 1):
            d = get(s, key, "nojepdqqaweusdfbi", AGE=age, BILL_ID=b["BILL_ID"], pIndex=1, pSize=1000)
            body = d.get("nojepdqqaweusdfbi")
            if body is None and (d.get("RESULT") or {}).get("CODE") != "INFO-200":
                raise RuntimeError("표결 조회 실패")
            rows = body[1]["row"] if body and len(body) > 1 else []
            if body and len(rows) != body[0]["head"][0]["list_total_count"]:
                raise ValueError("의원별 표결 누락")
            first = rows[0] if rows else {}
            rec = {"BILL_ID": b["BILL_ID"], "BILL_NAME": first.get("BILL_NAME") or b.get("BILL_NAME"),
                   "VOTE_DATE": first.get("VOTE_DATE"), "CURR_COMMITTEE": first.get("CURR_COMMITTEE"),
                   "votes": [[r.get("MONA_CD"), r.get("HG_NM"), r.get("POLY_NM"), r.get("RESULT_VOTE_MOD")] for r in rows]}
            atomic_bytes(folder / f"{b['BILL_ID']}.json", json.dumps(rec, ensure_ascii=False).encode())
            if i % 100 == 0:
                print(f"  제{age}대 {i}/{len(todo)}", file=sys.stderr)
            time.sleep(PAUSE)
    print("표결 수집 완료", file=sys.stderr)


if __name__ == "__main__":
    check_source("votes", main)
