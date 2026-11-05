"""서울 자치구의회(그룹 1: 강남·강동·강북·강서·광진·구로·금천·노원) 업무추진비 수집·파싱.

사용법:
  .venv/bin/python pipeline/districts/g1.py collect [slug...]
  .venv/bin/python pipeline/districts/g1.py parse [slug...]

- 원본은 data/raw/<slug>/ 에 그대로 보관하고 manifest.json 에 URL·sha256·수집 시각을 남긴다.
- 파싱 결과는 data/staging/<slug>.jsonl (마포·관악과 같은 키) + <slug>_parse_report.json.
- 의회 정보는 data/staging/councils/<slug>.json.
- 수집 범위: 공개 대상 기간 2022-07 이후 (제9대·제10대).
"""
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import parse_period, period_range  # noqa: E402

ROOT = PIPELINE.parent
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SCOPE_FROM = "2022-07"
TITLE_FILTER = re.compile(r"업무추진비|공통경비")

COUNCILS = {
    "gangnam": {"name": "강남구의회", "region": "서울 강남구", "kind": "costbbs", "base": "https://www.gncouncil.go.kr", "kr": "/kr",
                "board": "noticeBBS", "filter": True,
                "notes": "공지사항 게시판(noticeBBS)에 분기별 게시(제목에 '업무추진비'로 검색). 2024-03~2026-Q2 첨부 대부분이 스캔 PDF(텍스트 없음)라 OCR 필요 — 미처리. 2022-07~2024-02, 2026-Q3만 파싱. ZIP 묶음 1건 미처리."},
    "gangdong": {"name": "강동구의회", "region": "서울 강동구", "kind": "mapostyle", "base": "https://council.gangdong.go.kr",
                 "list": "/kr/news/bbsBusiness.do",
                "notes": "업무추진비 게시판 /kr/news/bbsBusiness.do(마포형 CMS). 2022-07~2023-12 의회운영 PDF는 스캔본(OCR 필요, 미처리). 표에 사용자 열이 없어 페이지 제목 '(의장)' 등의 직책을 사용. 주소 비공개. 원문 날짜 오기 일부(2029년 등)."},
    "gangbuk": {"name": "강북구의회", "region": "서울 강북구", "kind": "costbbs", "base": "https://council.gangbuk.go.kr", "kr": "/kr",
                "board": "costBBS",
                "notes": "costBBS.do. 2022-07 이후 첨부는 PDF 뷰어 전용(/viewer/pdf.do)이고 서버 방화벽이 스크립트 요청을 HTTP 400으로 막아, 설치된 Chrome(Playwright)으로 뷰어를 열어 내려받음."},
    "gangseo": {"name": "강서구의회", "region": "서울 강서구", "kind": "costbbs", "base": "https://gsc.gangseo.seoul.kr", "kr": "/kr",
                "board": "costBBS",
                "notes": "costBBS.do. 의장단 월별 + 의정운영공통경비 분기별. 같은 게시판의 '행사개최 현황' 자료는 업무추진비가 아니라 제외. 2024-11~2025-04 의장 파일은 '11.01 18:12' 형식 일시."},
    "gwangjin": {"name": "광진구의회", "region": "서울 광진구", "kind": "gwangjin", "base": "https://council.gwangjin.go.kr",
                "notes": "/kr/data/bbs?bbs_id=businesswork. 월별 의회운영·시책추진·기관운영 PDF. 거래처 주소 비공개. 비목 약칭(시책·의회운영·기관)을 정식 명칭으로 변환. 첨부 파일명 끝에 '파일 내려받기'가 붙어 있어 내용으로 형식 판정."},
    "guro": {"name": "구로구의회", "region": "서울 구로구", "kind": "costbbs", "base": "https://www.guroc.go.kr", "kr": "/kr",
             "board": "costBBS",
                "notes": "costBBS.do, 첨부는 PDF 뷰어(/viewer/pdf/loadFile.do POST) 경유. 2025년 이후 사용자 열에 의원 성명(정당 약칭 포함)이 적혀 있어 성명은 버리고 '의장단'으로 둠(직책 구분 손실)."},
    "geumcheon": {"name": "금천구의회", "region": "서울 금천구", "kind": "costbbs", "base": "https://council.geumcheon.go.kr",
                  "kr": "/council/kr", "board": "costBBS",
                "notes": "/council/kr/costBBS.do. 의장단 분기별 PDF + 사무국 월별 PDF. '구분' 열의 위원회 약칭(행정재경 등)을 '…위원장'으로 변환, 세로 병합 셀은 위 행 값으로 채움. 2018년 1분기 스캔본 1건(범위 밖) 미처리."},
    "nowon": {"name": "노원구의회", "region": "서울 노원구", "kind": "mapostyle", "base": "https://council.nowon.kr",
              "list": "/kr/news/bbsData.do", "filter": True,
                "notes": "의회자료 게시판(/kr/news/bbsData.do)에서 제목 필터. 의장단 분기별 XLS(월별 시트). 상호명·주소가 공개되지 않음. 연도 없는 2018년 자료 1건은 범위 밖이라 제외."},
}


class Fetcher:
    def __init__(self, base):
        self.base = base
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})

    def browser_viewer(self, viewer_url, list_url):
        """요청 라이브러리를 막는 PDF 뷰어(강북구의회 등)는 설치된 Chrome으로 열어 loadFile.do 응답에서 파일 경로를 얻는다."""
        if not hasattr(self, "_pw"):
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            # ARM64 배포는 Chrome 대신 컨테이너에 설치된 Chromium을 쓴다.
            executable = os.environ.get("ROBINHOOD_BROWSER_EXECUTABLE")
            options = {"executable_path": executable} if executable else {"channel": "chrome"}
            self._browser = self._pw.chromium.launch(**options, headless=True)
            self._page = self._browser.new_page(user_agent=UA)
            self._page.goto(list_url, wait_until="domcontentloaded")
        got = {}

        def on_resp(r):
            if "loadFile.do" in r.url:
                try:
                    got["json"] = r.json()
                except Exception:
                    got["status"] = r.status
        self._page.on("response", on_resp)
        self._page.goto(viewer_url, wait_until="networkidle", timeout=60000)
        self._page.remove_listener("response", on_resp)
        time.sleep(0.7)
        j = got.get("json") or {}
        if not j.get("result"):
            raise RuntimeError(f"브라우저 뷰어로도 파일을 받지 못함: {got}")
        r = self._page.request.get(self.base + j["file"], timeout=90000)
        if r.status != 200:
            raise RuntimeError(f"브라우저 내려받기 실패 HTTP {r.status}")
        return r.body(), r.headers.get("content-type", "")

    def close(self):
        if hasattr(self, "_pw"):
            self._browser.close()
            self._pw.stop()

    def get(self, url, referer=None, retries=4, timeout=40):
        return self._req("GET", url, referer=referer, retries=retries, timeout=timeout)

    def post(self, url, data, referer=None, retries=3, headers=None):
        return self._req("POST", url, data=data, referer=referer, retries=retries, headers=headers)

    def _req(self, method, url, referer=None, retries=4, timeout=40, **kw):
        url = url if url.startswith("http") else self.base + url
        hdrs = dict(kw.pop("headers", None) or {})
        hdrs["Referer"] = referer or self.base + "/"
        last = None
        for attempt in range(retries):
            try:
                r = self.s.request(method, url, headers=hdrs, timeout=timeout, **kw)
                time.sleep(0.7)
                if r.status_code >= 500:
                    last = RuntimeError(f"{r.status_code} {url}")
                    time.sleep(3 * (attempt + 1))
                    continue
                return r
            except requests.RequestException as e:
                last = e
                time.sleep(3 * (attempt + 1))
        raise last


def period_of(title):
    """게시글 제목에서 공개 대상 기간. common.parse_period가 못 읽는 서식도 처리한다."""
    t = title or ""
    m = re.search(r"(20\d{2})\s*\.\s*(\d{1,2})\s*\.\s*\d{1,2}\s*\.?\s*~\s*(?:20\d{2}\s*\.\s*)?(\d{1,2})\s*\.\s*\d{1,2}", t)  # 2026.7.1. ~ 9.30.
    if m:
        y, m1, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m2 - m1 == 2 and m1 % 3 == 1:
            return f"{y}-Q{(m1 - 1) // 3 + 1}"
        return f"{y}-{m1:02d}" if m1 == m2 else None  # 여러 달·연도에 걸친 범위는 기간을 정하지 않는다
    m = re.search(r"(20\d{2})\s*\.?\s*년?\s*(\d{1,2})\s*월?\s*~\s*(\d{1,2})\s*월", t)  # 2026.1월~3월, 2025. 10월~12월
    if m:
        y, m1, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y}-Q{(m1 - 1) // 3 + 1}" if m2 - m1 == 2 and m1 % 3 == 1 else f"{y}-{m1:02d}"
    p = parse_period(t)
    if p:
        return p
    m = re.search(r"(?<!\d)(\d{2})\s*년\s*(\d{1,2})\s*월", t)  # 26년 9월
    if m:
        return f"20{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(20\d{2})\s*[.-]\s*(\d{1,2})\s*월", t)  # 2026. 9월
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return None


def in_scope(period):
    return period is None or period_range(period)[1] >= SCOPE_FROM + "-01"


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def safe_name(name):
    return re.sub(r"[^\w.\-가-힣()]+", "_", name)[:120]


# ----------------------------------------------------------------- list / view per CMS
def list_costbbs(f, c, page):
    q = quote("업무추진비") if c.get("filter") else ""
    url = f"{c['kr']}/{c['board']}.do?schwrd={q}&flag=all&begindate=&enddate=&page={page}&list_style="
    t = f.get(url).text
    posts = []
    for uid, title, rest in re.findall(rf"{c['board']}view\.do\?uid=([0-9A-Fa-f]+)[^>]*>(.*?)</a>(.*?)</tr>", t, flags=re.S):
        d = re.search(r"(\d{4}[-.]\d{2}[-.]\d{2})", rest)
        posts.append({"key": uid, "post_title": clean(title),
                      "post_url": f"{f.base}{c['kr']}/{c['board']}view.do?uid={uid}&schwrd=&flag=all&begindate=&enddate=&page=1&list_style=",
                      "posted_date": d.group(1).replace(".", "-") if d else None})
    return posts


def list_mapostyle(f, c, page):
    t = f.get(f"{c['list']}?view=&startDay=&endDay=&flag=&keyword=&pageNum={page}").text
    posts = []
    for m in re.finditer(r"""<a[^>]+href=["'](\?reform=view&(?:amp;)?key=([0-9a-f]+)[^"']*)["'][^>]*>(.*?)</a>(.*?)</tr>""", t, flags=re.S):
        d = re.search(r"(\d{4}[-.]\d{2}[-.]\d{2})", m.group(4))
        posts.append({"key": m.group(2), "post_title": clean(m.group(3)),
                      "post_url": f"{f.base}{c['list']}{html.unescape(m.group(1))}",
                      "posted_date": d.group(1).replace(".", "-") if d else None})
    return posts


def list_gwangjin(f, c, page):
    t = f.get(f"/kr/data/bbs?bbs_id=businesswork&reform=list&list_style=&page={page}&flag=&keyword=&search_code=council&filter=latest").text
    posts = []
    for m in re.finditer(r"""<a[^>]+href=["'](\?bbs_id=businesswork&(?:amp;)?reform=view&(?:amp;)?uid=([0-9A-Fa-f]+)[^"']*)["'][^>]*>(.*?)</a>(.*?)</tr>""",
                         t, flags=re.S):
        d = re.search(r"(\d{4}[-.]\d{2}[-.]\d{2})", m.group(4))
        posts.append({"key": m.group(2), "post_title": clean(m.group(3)),
                      "post_url": f"{f.base}/kr/data/bbs{html.unescape(m.group(1))}",
                      "posted_date": d.group(1).replace(".", "-") if d else None})
    return posts


ATT_RE = re.compile(r"""<a[^>]+href=['"]([^'"]*(?:download|Download|viewer/pdf\.do|bbsAttachDownload|bbs_process\?reform=download)[^'"]*)['"]([^>]*)>(.*?)</a>""",
                    flags=re.S)


def attachments(f, post):
    t = f.get(post["post_url"]).text
    out = []
    for href, attrs, inner in ATT_RE.findall(t):
        href = html.unescape(href)
        if "downloadSelector" in href:  # 압축 일괄 받기
            continue
        tm = re.search(r"""title=['"]([^'"]+)['"]""", attrs)
        name = clean(tm.group(1)) if tm else clean(inner)
        name = re.sub(r"\s*\(?새창열림\)?\s*$", "", name).strip()
        name = re.sub(r"\s*(파일\s*)?(내려받기|다운로드|미리보기|바로보기)\s*$", "", name).strip() or "attachment"
        if any(a["url"].endswith(href) for a in out):
            continue
        out.append({"filename": name, "url": href if href.startswith("http") else f.base + href})
    return out


def download(f, att, post_url):
    """일반 다운로드 또는 PDF 뷰어(/viewer/pdf.do?group=bbs&uid=N → loadFile.do) 경유."""
    url = att["url"]
    if "/viewer/pdf.do" in url:
        m = re.search(r"group=(\w+)&(?:amp;)?uid=(\d+)", url)
        f.get(url, referer=post_url)
        r = f.post("/viewer/pdf/loadFile.do", {"group": m.group(1), "uid": m.group(2)}, referer=url,
                   headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*; q=0.01"})
        try:
            j = r.json()
        except ValueError:
            # 방화벽이 스크립트 요청을 막는 경우 실제 브라우저로 재시도
            return f.browser_viewer(url, f.base + "/")
        if not j.get("result"):
            raise RuntimeError(f"PDF 뷰어 오류: {j.get('message')}")
        r = f.get(j["file"], referer=url, timeout=90)
    else:
        r = f.get(url, referer=post_url, timeout=90)
    ctype = r.headers.get("Content-Type", "")
    if r.status_code != 200 or ("text/html" in ctype and not r.content[:5] in (b"%PDF-", b"PK\x03\x04")):
        raise RuntimeError(f"내려받기 실패 HTTP {r.status_code} {ctype}")
    return r.content, ctype


def collect(slug):
    c = COUNCILS[slug]
    out = RAW / slug
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    previous = {}
    if mpath.exists():
        for p in json.loads(mpath.read_text()):
            for a in p["attachments"]:
                if a.get("sha256"):
                    previous[a["url"]] = a
    f = Fetcher(c["base"])
    lister = {"costbbs": list_costbbs, "mapostyle": list_mapostyle, "gwangjin": list_gwangjin}[c["kind"]]
    manifest, seen, page, old_pages = [], set(), 1, 0
    while page <= 80:
        try:
            posts = lister(f, c, page)
        except Exception as e:
            print(f"[{slug}] list page {page} failed: {e}", file=sys.stderr)
            break
        new = [p for p in posts if p["key"] not in seen]
        if not new:
            break
        any_in_scope = False
        for p in new:
            seen.add(p["key"])
            if c.get("filter") and not TITLE_FILTER.search(p["post_title"]):
                continue
            p["period"] = period_of(p["post_title"])
            if not in_scope(p["period"]):
                continue
            any_in_scope = True
            p["attachments"] = []
            try:
                atts = attachments(f, p)
            except Exception as e:
                p["error"] = str(e)
                atts = []
            for a in atts:
                prev = previous.get(a["url"])
                if prev and (ROOT / prev["local_path"]).exists():
                    p["attachments"].append(prev)
                    continue
                if "명단" in a["filename"]:
                    p["attachments"].append({**a, "skipped": "참석자 명단(개인 성명 포함) — 내려받지 않음"})
                    continue
                try:
                    content, ctype = download(f, a, p["post_url"])
                except Exception as e:
                    p["attachments"].append({**a, "error": str(e)})
                    continue
                sha = hashlib.sha256(content).hexdigest()
                local = out / f"{sha[:12]}_{safe_name(a['filename'])}"
                if not local.exists():
                    local.write_bytes(content)
                p["attachments"].append({**a, "local_path": str(local.relative_to(ROOT)), "sha256": sha, "bytes": len(content),
                                         "content_type": ctype, "fetched_at": datetime.now(KST).isoformat(timespec="seconds")})
            p.pop("key", None)
            manifest.append(p)
            print(f"[{slug}] {p['period']} {p['post_title'][:50]} ({len(p['attachments'])})", file=sys.stderr)
        # 공개 기간 순으로 정렬된 게시판이라 범위 밖 게시글만 있는 페이지가 이어지면 멈춘다
        old_pages = 0 if any_in_scope or c.get("filter") else old_pages + 1
        if old_pages >= 2:
            break
        page += 1
    f.close()
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    n_att = sum(1 for p in manifest for a in p["attachments"] if a.get("sha256"))
    print(f"[{slug}] {len(manifest)} posts, {n_att} files", file=sys.stderr)
    return manifest


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("collect", "parse"):
        print(__doc__)
        sys.exit(1)
    slugs = sys.argv[2:] or list(COUNCILS)
    if sys.argv[1] == "collect":
        for s in slugs:
            try:
                collect(s)
            except Exception as e:
                print(f"[{s}] FAILED: {e}", file=sys.stderr)
    else:
        from g1_parse import parse_council
        for s in slugs:
            parse_council(s, COUNCILS[s])


if __name__ == "__main__":
    main()
