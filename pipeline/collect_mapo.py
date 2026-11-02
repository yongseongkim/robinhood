"""Collect 마포구의회 업무추진비 disclosure posts and their attachments (raw, unmodified).

Usage: .venv/bin/python -I pipeline/collect_mapo.py
Writes data/raw/mapo/<sha12>_<filename> and data/raw/mapo/manifest.json.
"""
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "mapo"
BASE = "https://council.mapo.seoul.kr"
LIST_URL = BASE + "/kr/news/bbsCost.do"
KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": LIST_URL,
}
SLEEP = 0.5

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            time.sleep(SLEEP)
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def clean(s):
    # strip only real tags: some titles are literally wrapped in "<<...>>"
    s = html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", " ", s))
    return re.sub(r"\s+", " ", s).strip(" <>")


ROW_RE = re.compile(
    r'<td class="con"><a href="(\?reform=view&key=([0-9a-f]+)[^"]*)">(.*?)</a></td>\s*'
    r'<td class="author">.*?</td>\s*<td class="date">([^<]*)</td>',
    re.S,
)
ATTACH_RE = re.compile(r'href="(/bbsAttachDownload\.do\?key=[0-9a-f]+)"[^>]*>(.*?)</a>', re.S)


def parse_period(title):
    m = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월", title)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return None


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip()
    return name[:150] or "attachment"


def crawl_list():
    posts, seen = [], set()
    page = 1
    while True:
        r = fetch(f"{LIST_URL}?pageNum={page}")
        rows = ROW_RE.findall(r.text)
        new = [x for x in rows if x[1] not in seen]
        if not new:
            break
        for href, key, title, date in new:
            seen.add(key)
            posts.append({
                "post_title": clean(title),
                "post_url": f"{LIST_URL}?reform=view&key={key}",
                "posted_date": date.strip().replace(".", "-"),
                "key": key,
            })
        print(f"list page {page}: {len(new)} posts", file=sys.stderr)
        page += 1
    return posts


def crawl_post(post):
    r = fetch(post["post_url"])
    atts = []
    for href, label in ATTACH_RE.findall(r.text):
        fname = clean(label)
        if not fname:
            continue
        atts.append({"filename": fname, "url": urljoin(BASE, html.unescape(href))})
    # dedupe (same link can appear in preview + list)
    uniq, keys = [], set()
    for a in atts:
        if a["url"] not in keys:
            keys.add(a["url"])
            uniq.append(a)
    return uniq


def load_existing():
    path = RAW_DIR / "manifest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out = {}
    for p in data:
        for a in p.get("attachments", []):
            out[(p["post_url"], a["filename"])] = a
    return out


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_existing()
    posts = crawl_list()
    manifest = []
    for post in posts:
        attachments = []
        for att in crawl_post(post):
            prev = existing.get((post["post_url"], att["filename"]))
            if prev and (ROOT / prev["local_path"]).exists():
                attachments.append(prev)
                continue
            r = fetch(att["url"])
            body = r.content
            sha = hashlib.sha256(body).hexdigest()
            local = RAW_DIR / f"{sha[:12]}_{safe_name(att['filename'])}"
            if not local.exists():
                local.write_bytes(body)
            attachments.append({
                "filename": att["filename"],
                "url": att["url"],
                "local_path": str(local.relative_to(ROOT)),
                "sha256": sha,
                "bytes": len(body),
                "content_type": r.headers.get("Content-Type"),
                "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            })
        manifest.append({
            "post_title": post["post_title"],
            "post_url": post["post_url"],
            "posted_date": post["posted_date"],
            "period": parse_period(post["post_title"]),
            "attachments": attachments,
        })
        print(f"{post['post_title']}: {len(attachments)} attachments", file=sys.stderr)
    (RAW_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_att = sum(len(p["attachments"]) for p in manifest)
    print(f"posts={len(manifest)} attachments={n_att}", file=sys.stderr)


if __name__ == "__main__":
    main()
