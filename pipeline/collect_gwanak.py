"""관악구의회 업무추진비 게시판 수집기.

https://www.ga21c.seoul.kr/kr/costBBS.do 의 모든 게시글과 첨부파일을 원본 그대로 내려받는다.
- 첨부파일은 data/raw/gwanak/<sha256 앞 12자리>_<원본 파일명> 으로 저장 (이미 있으면 건너뜀)
- data/raw/gwanak/manifest.json 에 게시글·첨부파일 메타데이터를 기록
"""
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from common import parse_period

BASE = "https://www.ga21c.seoul.kr"
LIST_URL = BASE + "/kr/costBBS.do?schwrd=&flag=all&begindate=&enddate=&page={page}&list_style="
VIEW_URL = BASE + "/kr/costBBSview.do?uid={uid}&schwrd=&flag=all&begindate=&enddate=&page=1&list_style="
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "gwanak"
KST = timezone(timedelta(hours=9))

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 robinhood-collector",
    "Referer": BASE + "/kr/costBBS.do",
})


def get(url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            time.sleep(0.5)
            return r
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def list_posts():
    posts, seen, page = [], set(), 1
    while True:
        t = get(LIST_URL.format(page=page)).text
        rows = re.findall(r"costBBSview\.do\?uid=([0-9A-F]+)[^>]*>\s*([^<]+?)\s*</a>(.*?)</tr>", t, flags=re.S)
        new = 0
        for uid, title, rest in rows:
            if uid in seen:
                continue
            seen.add(uid)
            new += 1
            date = re.search(r"(\d{4}[-.]\d{2}[-.]\d{2})", rest)
            posts.append({
                "uid": uid,
                "post_title": html.unescape(title).strip(),
                "post_url": VIEW_URL.format(uid=uid),
                "posted_date": date.group(1).replace(".", "-") if date else None,
            })
        print(f"page {page}: {new} new posts", file=sys.stderr)
        if new == 0:
            break
        page += 1
    return posts


def attachments_of(post):
    t = get(post["post_url"]).text
    out = []
    for href, name in re.findall(r"<a href='(/kr/bbs/download\.do\?bbs_id=cost&uid=[0-9A-F]+)' title='([^']+)'", t):
        out.append({"filename": html.unescape(name).strip(), "url": BASE + href})
    return out


def safe_name(name):
    return re.sub(r"[^\w.\-가-힣()]+", "_", name)[:120]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    previous = {}
    if manifest_path.exists():
        for p in json.loads(manifest_path.read_text()):
            for a in p["attachments"]:
                previous[a["url"]] = a

    manifest = []
    for post in list_posts():
        post["period"] = parse_period(post["post_title"])
        post["attachments"] = []
        for att in attachments_of(post):
            prev = previous.get(att["url"])
            if prev and (ROOT / prev["local_path"]).exists():
                post["attachments"].append(prev)
                continue
            r = get(att["url"])
            sha = hashlib.sha256(r.content).hexdigest()
            local = OUT / f"{sha[:12]}_{safe_name(att['filename'])}"
            if not local.exists():
                local.write_bytes(r.content)
            post["attachments"].append({
                **att,
                "local_path": str(local.relative_to(ROOT)),
                "sha256": sha,
                "bytes": len(r.content),
                "content_type": r.headers.get("Content-Type"),
                "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            })
        print(f"{post['period']} {post['post_title']} ({len(post['attachments'])} files)", file=sys.stderr)
        manifest.append(post)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"{len(manifest)} posts, {sum(len(p['attachments']) for p in manifest)} attachments", file=sys.stderr)


if __name__ == "__main__":
    main()
