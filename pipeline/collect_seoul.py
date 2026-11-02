"""서울특별시의회 업무추진비 공개 게시판 수집기 (제11대, 2022-07 이후 공개분).

https://www.smc.seoul.kr/board/BoardList.do?boardTypeId=158&menuId=001007013001
- 목록(30건씩)에서 게시글을 모은 뒤, 게시글 상세에서 첨부파일 전체를 확인한다
  (목록에는 첫 번째 첨부만 보이는 경우가 있다).
- 첨부는 POST /board/fileDown.do 로 받는다. 사람이 열어 볼 링크로는 GET 가능한
  /common/fileTrans.do (문서 뷰어) 주소를 기록한다.
- data/raw/seoul/<sha256 앞 12자리>_<원본 파일명>, data/raw/seoul/manifest.json
"""
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote_plus

import requests

from common import RAW, ROOT, parse_period, period_range

BASE = "https://www.smc.seoul.kr"
LIST_URL = BASE + "/board/BoardList.do?boardTypeId=158&menuId=001007013001&nPageSize=30&pageIndex={page}"
DETAIL_URL = BASE + "/board/BoardDetail.do?boardId={bid}&boardTypeId=158&menuId=001007013001"
VIEW_URL = BASE + "/common/fileTrans.do?fileId={fid}&articleId={bid}&objectId=158&groupId=B"
DOWN_URL = BASE + "/board/fileDown.do"
OUT = RAW / "seoul"
KST = timezone(timedelta(hours=9))
SINCE = "2022-07"  # 제11대 서울특별시의회 (2022-07-01 개원)
SLEEP = 1.0  # 0.5초 간격에서 503(Service Temporarily Unavailable)을 받은 적이 있어 늦춤

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 robinhood-collector",
    "Referer": BASE + "/board/BoardList.do?boardTypeId=158&menuId=001007013001",
})

ROW_RE = re.compile(r"<tr onMouseOver.*?</tr>", re.S)
FILE_RE = re.compile(r"fileDown\('(\d+)','([^']*)','([^']*)'\)")


def request(method, url, retries=6, **kw):
    last = None
    for attempt in range(retries):
        try:
            time.sleep(SLEEP)
            r = session.request(method, url, timeout=30, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            status = getattr(e.response, "status_code", None)
            wait = 30 * (attempt + 1) if status in (429, 502, 503, 504) or "503" in str(e) else 2 * (attempt + 1)
            print(f"  retry in {wait}s {url}: {e}", file=sys.stderr)
            time.sleep(wait)
    raise last


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def in_scope(post):
    if post["period"]:
        return period_range(post["period"])[1] >= SINCE + "-01"
    return (post["posted_date"] or "") >= "2022-08-01"


def list_posts():
    posts, seen, page = [], set(), 1
    while True:
        rows = ROW_RE.findall(request("GET", LIST_URL.format(page=page)).text)
        new = 0
        for r in rows:
            m = re.search(r"goDetail\('(\d+)'\);\">([^<]*)</a>", r)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            new += 1
            cells = re.findall(r'<td class="num hidden-xs">([^<]*)</td>', r)
            title = text(m.group(2))
            posted = cells[2].strip() if len(cells) > 2 else None
            posts.append({
                "board_id": m.group(1),
                "post_title": title,
                "post_url": DETAIL_URL.format(bid=m.group(1)),
                "posted_date": posted,
                "author": cells[1].strip() if len(cells) > 1 else None,
                "period": parse_period(title),
            })
        page_posts = posts[-new:] if new else []
        print(f"list page {page}: {new} posts", file=sys.stderr)
        # 목록은 등록일 역순: 한 페이지가 통째로 범위 밖이면 멈춘다
        if new == 0 or not any(in_scope(p) for p in page_posts):
            break
        page += 1
    return [p for p in posts if in_scope(p)]


def attachments_of(post):
    t = request("GET", post["post_url"]).text
    out, seen = [], set()
    for fid, dirname, name in FILE_RE.findall(t):
        if fid in seen:
            continue
        seen.add(fid)
        out.append({"file_id": fid, "dir": dirname, "filename": unquote_plus(name).strip(),
                    "url": VIEW_URL.format(fid=fid, bid=post["board_id"])})
    return out


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f\s]+', "_", name).strip("_")[:120] or "attachment"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    previous, known_posts = {}, {}
    if manifest_path.exists():
        for p in json.loads(manifest_path.read_text()):
            known_posts[p["board_id"]] = p
            for a in p["attachments"]:
                previous[(p["board_id"], a["file_id"])] = a
    manifest = []
    posts = list_posts()
    print(f"{len(posts)} posts in scope (period >= {SINCE})", file=sys.stderr)
    for i, post in enumerate(posts, 1):
        post["attachments"] = []
        known = known_posts.get(post["board_id"])
        if known and known["attachments"] and all((ROOT / a["local_path"]).exists() for a in known["attachments"]):
            post["attachments"] = known["attachments"]  # 이미 받은 게시글: 상세 페이지를 다시 열지 않음
            manifest.append(post)
            continue
        for att in attachments_of(post):
            prev = previous.get((post["board_id"], att["file_id"]))
            if prev and (ROOT / prev["local_path"]).exists():
                post["attachments"].append(prev)
                continue
            r = request("POST", DOWN_URL, data={"fileId": att["file_id"], "dirName": att["dir"], "fileName": "",
                                                "originalName": att["filename"]})
            body = r.content
            sha = hashlib.sha256(body).hexdigest()
            local = OUT / f"{sha[:12]}_{safe_name(att['filename'])}"
            if not local.exists():
                local.write_bytes(body)
            post["attachments"].append({
                "file_id": att["file_id"],
                "filename": att["filename"],
                "url": att["url"],
                "download": {"method": "POST", "url": DOWN_URL, "fileId": att["file_id"], "dirName": att["dir"]},
                "local_path": str(local.relative_to(ROOT)),
                "sha256": sha,
                "bytes": len(body),
                "content_type": r.headers.get("Content-Type"),
                "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            })
        manifest.append(post)
        if i % 25 == 0:
            print(f"  {i}/{len(posts)} posts", file=sys.stderr)
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{len(manifest)} posts, {sum(len(p['attachments']) for p in manifest)} attachments", file=sys.stderr)


if __name__ == "__main__":
    main()
