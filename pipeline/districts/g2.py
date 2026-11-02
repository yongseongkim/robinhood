"""G2 구의회 업무추진비 수집·파싱 CLI.

  .venv/bin/python pipeline/districts/g2.py collect [slug...]
  .venv/bin/python pipeline/districts/g2.py parse [slug...]

slug: dobong dongdaemun dongjak seodaemun seocho songpa seongdong seongbuk (생략 시 전부)
수집 범위: 공개 대상 기간이 2022-07 이후인 게시글 (제9대·제10대).
"""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
import urllib3

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from common import period_range  # noqa: E402
from g2_sites import COUNCILS, list_url, parse_attachments, parse_list, parse_period_title  # noqa: E402

urllib3.disable_warnings()
ROOT = HERE.parent.parent
KST = timezone(timedelta(hours=9))
SCOPE_START = "2022-07-01"
SLEEP = 0.7
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Fetcher:
    def __init__(self, c):
        self.c = c
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": c["base"] + c["list"]})
        self.verify = c.get("verify", True)

    def get(self, url, retries=5):
        last = None
        for attempt in range(retries):
            time.sleep(SLEEP)
            try:
                r = self.s.get(url, timeout=30, verify=self.verify)
                if r.status_code >= 500 or r.status_code == 429:
                    raise requests.HTTPError(f"{r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last = e
                time.sleep(3 * (2 ** attempt))
        raise last

    def page(self, url):
        r = self.get(url)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text


def in_scope(period, posted):
    if period:
        _, end = period_range(period)
        return end >= SCOPE_START
    return bool(posted) and posted >= "2022-07-15"


def filename_from_headers(h):
    cd = h.get("Content-Disposition") or h.get("content-disposition") or ""
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", cd)
    if m:
        return unquote(m.group(1)).strip('"')
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    if not m:
        return None
    raw = m.group(1)
    if "%" in raw:
        raw = unquote(raw)
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.encode("latin-1").decode(enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return raw


def safe_name(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip()
    return name[:150] or "attachment"


EXT_BY_TYPE = {"pdf": ".pdf", "spreadsheetml": ".xlsx", "ms-excel": ".xls", "hwp": ".hwp", "zip": ".zip"}


def collect(slug):
    c = COUNCILS[slug]
    f = Fetcher(c)
    out_dir = ROOT / "data" / "raw" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    mpath = out_dir / "manifest.json"
    old = {}
    if mpath.exists():
        for p in json.loads(mpath.read_text(encoding="utf-8")):
            old[p["post_url"]] = p
    posts, seen = [], set()
    page = 1
    while True:
        items = parse_list(c, f.page(list_url(c, page)))
        new = [x for x in items if x["key"] not in seen]
        if not new:
            break
        for x in new:
            seen.add(x["key"])
            x["period"] = parse_period_title(x["title"])
        posts.extend(new)
        log(f"[{slug}] list page {page}: {len(new)} posts")
        if all(not in_scope(x["period"], x["posted_date"]) for x in new):
            break
        page += 1
        if page > 200:
            break
    posts = [p for p in posts if in_scope(p["period"], p["posted_date"])]
    manifest = []
    for p in posts:
        prev = old.get(p["view_url"])
        if prev and prev.get("attachments") and all((ROOT / a["local_path"]).exists() for a in prev["attachments"]):
            manifest.append(prev)
            continue
        try:
            atts = parse_attachments(c, f.page(p["view_url"]), p["row_downloads"])
        except requests.RequestException as e:
            log(f"[{slug}] view failed {p['title']}: {e}")
            continue
        saved = []
        for i, a in enumerate(atts):
            try:
                r = f.get(a["url"])
            except requests.RequestException as e:
                log(f"[{slug}] download failed {a['url']}: {e}")
                continue
            body = r.content
            if body[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                log(f"[{slug}] got html instead of file: {a['url']}")
                continue
            name = a["filename"] or filename_from_headers(r.headers)
            if not name:
                ct = (r.headers.get("Content-Type") or "").lower()
                ext = next((v for k, v in EXT_BY_TYPE.items() if k in ct), ".bin")
                name = f"attachment_{i + 1}{ext}"
            sha = hashlib.sha256(body).hexdigest()
            local = out_dir / f"{sha[:12]}_{safe_name(name)}"
            if not local.exists():
                local.write_bytes(body)
            saved.append({"filename": name, "url": a["url"], "local_path": str(local.relative_to(ROOT)), "sha256": sha,
                          "bytes": len(body), "content_type": r.headers.get("Content-Type"),
                          "fetched_at": datetime.now(KST).isoformat(timespec="seconds")})
        manifest.append({"post_title": p["title"], "post_url": p["view_url"], "posted_date": p["posted_date"],
                         "period": p["period"], "attachments": saved})
        log(f"[{slug}] {p['period']} {p['title']}: {len(saved)} files")
        mpath.write_text(json.dumps(manifest + [v for k, v in old.items() if k not in {m['post_url'] for m in manifest}
                                                and in_scope(v.get('period'), v.get('posted_date'))],
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[{slug}] done: posts={len(manifest)} files={sum(len(m['attachments']) for m in manifest)}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("collect", "parse"):
        print(__doc__)
        sys.exit(1)
    slugs = sys.argv[2:] or list(COUNCILS)
    for s in slugs:
        if s not in COUNCILS:
            sys.exit(f"unknown slug {s}")
    if sys.argv[1] == "collect":
        for s in slugs:
            collect(s)
    else:
        from g2_parse import parse_council
        for s in slugs:
            parse_council(s)


if __name__ == "__main__":
    main()
