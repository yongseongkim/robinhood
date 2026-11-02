"""서울 자치구의회(G3: 양천·영등포·용산·은평·종로·중구·중랑) 업무추진비 수집·파싱.

사용법
  python pipeline/districts/g3.py collect [slug ...]   # 게시판 → data/raw/<slug>/
  python pipeline/districts/g3.py parse [slug ...]     # 첨부 → data/staging/<slug>.jsonl
슬러그를 생략하면 G3 의회 전체. 공개 대상 기간 2022-07 이후(제9·10대)만 수집한다.
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

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import parse_period, period_range  # noqa: E402

ROOT = PIPELINE.parent
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"
KST = timezone(timedelta(hours=9))
SCOPE_START = "2022-07-01"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126 Safari/537.36 robin-hood-collector")

COUNCILS = {
    "yangcheon": {
        "notes": "분기별 게시글에 PDF 3종(의정운영공통경비·의회사무국·의회운영업무추진비). 주소 칸 없음. 금액 글자가 '9 14,000'처럼 쪼개져 추출되어 공백을 제거해 읽음. 이 게시판은 2021년부터 있으나 2022-07 이후만 수집.",
        "name": "양천구의회", "region": "서울 양천구", "base": "https://www.ycc.go.kr",
        "board": "https://www.ycc.go.kr/kr/news/bbs?bbs_id=business",
        "list": "/kr/news/bbs?bbs_id=business&reform=list&list_style=&page={page}&flag=&keyword=&search_code=council&filter=latest",
        "list_path": "/kr/news/bbs",
        "post_re": r"reform=view[^\"']*uid=[0-9A-F]{32}",
        "attach_re": r"bbs_process\?reform=download",
    },
    "yeongdeungpo": {
        "notes": "사무국 월별 PDF + 의장단·공통경비 분기별 PDF(일부 XLSX). 2025년 9월 사무국 첨부는 게시판 서버에 파일이 없음('첨부파일이 없습니다'). 공통경비 파일은 사용자 칸이 없어 '영등포구의회' 명의로 둠. 주소는 도로명만 있는 경우가 많음.",
        "name": "영등포구의회", "region": "서울 영등포구", "base": "https://www.ydpc.go.kr",
        "board": "https://www.ydpc.go.kr/content/news/bbsCost.html",
        "list": "/content/news/bbsCost.html?sid=1000&page={page}&sword=&f_code=",
        "list_path": "/content/news/bbsCost.html",
        "post_re": r"fidx=\w+&(?:amp;)?pg=vv",
        "attach_re": r"gtb_download\.php",
    },
    "yongsan": {
        "notes": "직책별 월별 PDF(첨부는 /viewer/pdf.do → 세션·CSRF로 loadFile.do를 불러 실제 파일 경로를 얻음). 2022년 하반기는 직책별 시트 XLSX(시트 이름=직책, 목적은 제목 줄 '사용목적'). 2023년 10~12월 PDF 17개는 글자가 외곽선으로 변환되어 텍스트가 없음(OCR 필요).",
        "name": "용산구의회", "region": "서울 용산구", "base": "https://www.yscl.go.kr",
        "board": "https://www.yscl.go.kr/kr/councilcostBBS.do",
        "list": "/kr/councilcostBBS.do?schwrd=&flag=all&publish_sch=&page={page}&list_style=",
        "list_path": "/kr/councilcostBBS.do",
        "post_re": r"councilcostBBSview\.do\?uid=[0-9A-F]{32}",
        "attach_re": r"viewer/pdf\.do|/download|fileDown|FileDown",
    },
    "eunpyeong": {
        "notes": "월별 통합 파일(2025년까지 XLSX, 이후 PDF). '구분' 칸에 비목과 직책이 함께 적힘(예: '의회운영업무추진비 (의장)', 세로 병합). 2026년 2월부터 사무국 업무추진비 PDF가 별도 게시(표가 헤더만 추출되어 단어 위치로 복원). 작업용 복사 시트(Sheet1)는 제외.",
        "name": "은평구의회", "region": "서울 은평구", "base": "https://council.ep.go.kr",
        "board": "https://council.ep.go.kr/kr/costBBS.do",
        "list": "/kr/costBBS.do?schwrd=&flag=all&page={page}&list_style=",
        "list_path": "/kr/costBBS.do",
        "post_re": r"costBBSview\.do\?uid=[0-9A-F]{32}",
        "attach_re": r"viewer/pdf\.do|/download|fileDown|FileDown",
    },
    "jongno": {
        "notes": "의회운영업무추진비 월별 PDF만 게시(게시판 시작 2024-01). 의정운영공통경비는 이 게시판에 없음. 2024년 2~3월 PDF는 사용자 칸이 세로 병합되어 직책이 블록 가운데 한 번만 찍혀 있어, 검은 테두리로 블록을 나눠 채움.",
        "name": "종로구의회", "region": "서울 종로구", "base": "https://council.jongno.go.kr",
        "board": "https://council.jongno.go.kr/council/bbs/BBSMSTR_000000000061/list.do?menuNo=401070",
        "list": "/council/bbs/BBSMSTR_000000000061/list.do?menuNo=401070&pageIndex={page}",
        "list_path": "/council/bbs/BBSMSTR_000000000061/list.do",
        "post_re": r"BBSMSTR_000000000061/view\.do\?nttId=\d+",
        "attach_re": r"FileDown\.do\?atchFileId=",
    },
    "junggu": {
        "notes": "의장단 월별 통합 파일(시트=직책; 2023~2024 XLS·XLSX, 2025~ PDF 일부). 집행목적 칸이 대부분 없고 2024년 이전은 시간 칸도 없음. 2023년 5월 복지건설위원장 시트는 사용자 칸에 승인시각이 들어간 원문 오기 — 직책은 시트 제목에서 정함. 서버가 TLS 중간 인증서를 보내지 않아 AIA 주소의 중간 인증서를 덧붙여 검증.",
        "name": "중구의회", "region": "서울 중구", "base": "https://council.junggu.seoul.kr",
        "board": "https://council.junggu.seoul.kr/kr/bbs?bbs_id=cost",
        "list": "/kr/bbs?reform=list&page={page}&flag=&keyword=&search_code=&bbs_id=cost&list_style=",
        "list_path": "/kr/bbs",
        "post_re": r"reform=view&(?:amp;)?uid=[0-9A-F]{32}",
        "attach_re": r"/kr/bbs/download\?",
        # 서버가 중간 인증서(AlphaSSL CA 2025)를 보내지 않는다. 검증을 끄지 않고, 인증서의 AIA 주소에서 중간 인증서를 받아 보탠다.
        "extra_ca": "http://secure.globalsign.com/cacert/gsgccr6alphasslca2025.crt",
    },
    "jungnang": {
        "notes": "월별 PDF 1개. 37개 중 19개(2023-07~2024-06, 2025-07~2026-01)는 스캔 이미지라 텍스트가 없음(OCR 필요). 게시판은 2023-07부터(그 이전 2015년 게시글 1건은 범위 밖).",
        "name": "중랑구의회", "region": "서울 중랑구", "base": "http://council.jungnang.go.kr",
        "board": "http://council.jungnang.go.kr/kr/costBBS.do",
        "list": "/kr/costBBS.do?schwrd=&flag=all&mem_sch=&page={page}&list_style=",
        "list_path": "/kr/costBBS.do",
        "post_re": r"costBBSview\.do\?uid=[0-9A-F]{32}",
        "attach_re": r"viewer/pdf\.do|/download|fileDown|FileDown",
    },
}

DATE_RE = re.compile(r"(20\d{2})[-.](\d{2})[-.](\d{2})")
ANCHOR_RE = re.compile(r"<a\s([^>]*?)href=([\"'])(.*?)\2([^>]*)>(.*?)</a>", re.S | re.I)
FILENAME_RE = re.compile(r"(\S.*?\.(?:pdf|xlsx|xls|hwpx|hwp|docx?|zip|cell|csv))(?=\s|\(|\[|$)", re.I)


class Fetcher:
    def __init__(self, referer, extra_ca=None, ca_dir=None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": referer})
        self.last = 0.0
        if extra_ca:
            import ssl
            import certifi
            der = requests.get(extra_ca, timeout=30).content
            pem = der.decode() if der.startswith(b"-----") else ssl.DER_cert_to_PEM_cert(der)
            bundle = Path(ca_dir) / "_ca_bundle.pem"
            bundle.write_text(Path(certifi.where()).read_text() + "\n" + pem)
            self.s.verify = str(bundle)

    def req(self, method, url, **kw):
        for attempt in range(5):
            wait = 0.7 - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.request(method, url, timeout=30, **kw)
                self.last = time.time()
                if r.status_code >= 500:
                    raise requests.HTTPError(f"{r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                self.last = time.time()
                if attempt == 4:
                    raise
                print(f"    retry {attempt + 1} {url[:90]}: {e}", file=sys.stderr)
                time.sleep(2 ** attempt)

    def get(self, url, **kw):
        return self.req("GET", url, **kw)


def text_of(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def in_scope(period, posted_date):
    if period:
        s, _ = period_range(period)
        return s >= SCOPE_START
    return bool(posted_date) and posted_date >= "2022-07-15"


def list_posts(cfg, f):
    posts, seen, page = [], set(), 1
    post_re = re.compile(cfg["post_re"])
    while page < 80:
        url = cfg["base"] + cfg["list"].format(page=page)
        t = f.get(url).text
        found = 0
        dates = []
        for m in ANCHOR_RE.finditer(t):
            href = html.unescape(m.group(3))
            if not post_re.search(href):
                continue
            abs_url = urljoin(cfg["base"] + cfg["list_path"], href)
            key = re.search(cfg["post_re"], href).group(0)
            if key in seen:
                continue
            seen.add(key)
            found += 1
            title = text_of(m.group(5))
            seg_end = min([x for x in (t.find("</tr>", m.end()), t.find("</li>", m.end())) if x > 0] or [m.end() + 800])
            dm = DATE_RE.search(t[m.end():seg_end])
            posted = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm else None
            dates.append(posted)
            posts.append({"post_title": title, "post_url": abs_url, "posted_date": posted, "key": key})
        print(f"  page {page}: {found} posts (oldest posted {min([d for d in dates if d] or ['?'])})", file=sys.stderr)
        if found == 0 or (dates and all(d and d < SCOPE_START for d in dates)):
            break
        page += 1
    return posts


def attachments_of(cfg, f, post_html, post_url):
    out, seen = [], set()
    att_re = re.compile(cfg["attach_re"], re.I)
    for m in ANCHOR_RE.finditer(post_html):
        href = html.unescape(m.group(3))
        if not att_re.search(href) or href.startswith("javascript"):
            continue
        attrs = m.group(1) + " " + m.group(4)
        tm = re.search(r"title=([\"'])(.*?)\1", attrs)
        name = None
        for cand in ((html.unescape(tm.group(2)) if tm else ""), text_of(m.group(5))):
            fm = FILENAME_RE.search(cand)
            if fm:
                name = fm.group(1).strip()
                break
        if not name:
            continue
        absu = urljoin(post_url, href)
        if absu in seen:
            continue
        seen.add(absu)
        out.append({"filename": name, "url": absu})
    return out


def resolve_viewer(cfg, f, viewer_url):
    """/viewer/pdf.do?group=bbs&uid=N → 세션·CSRF로 loadFile.do 호출 → 실제 파일 경로."""
    r = f.get(viewer_url)
    csrf = re.search(r"name=[\"']_csrf[\"'] content=[\"']([^\"']+)", r.text)
    uid = re.search(r"uid=(\d+)", viewer_url).group(1)
    group = re.search(r"group=(\w+)", viewer_url).group(1)
    hdr = {"Referer": viewer_url, "X-Requested-With": "XMLHttpRequest", "Origin": cfg["base"]}
    if csrf:
        hdr["X-CSRF-TOKEN"] = csrf.group(1)
    j = f.req("POST", cfg["base"] + "/viewer/pdf/loadFile.do", data={"group": group, "uid": uid}, headers=hdr).json()
    if not j.get("result"):
        raise RuntimeError(f"viewer 해석 실패: {j.get('message')}")
    return cfg["base"] + j["file"]


def safe_name(name):
    return re.sub(r"[^\w.\-가-힣()]+", "_", name)[:120]


def jongno_period(post_html):
    t = text_of(post_html)
    m = re.search(r"년\s*(20\d{2})\s*해당월\s*(\d{1,2})", t)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def collect(slug):
    cfg = COUNCILS[slug]
    out_dir = RAW / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    mpath = out_dir / "manifest.json"
    previous = {}
    if mpath.exists():
        for p in json.loads(mpath.read_text(encoding="utf-8")):
            previous[p["post_url"]] = p
    f = Fetcher(cfg["board"], cfg.get("extra_ca"), out_dir)
    f.get(cfg["board"])  # 세션 쿠키
    print(f"[{slug}] listing", file=sys.stderr)
    posts = list_posts(cfg, f)
    manifest = []
    for post in posts:
        period = parse_period(post["post_title"])
        if not in_scope(period, post["posted_date"]) and slug != "jongno":
            continue
        prev = previous.get(post["post_url"])
        if prev and prev.get("attachments") and all(a.get("local_path") and (ROOT / a["local_path"]).exists() for a in prev["attachments"]):
            manifest.append(prev)
            continue
        ph = f.get(post["post_url"]).text
        if slug == "jongno":
            period = jongno_period(ph) or period
            if not in_scope(period, post["posted_date"]):
                continue
        entry = {"post_title": post["post_title"], "post_url": post["post_url"], "posted_date": post["posted_date"],
                 "period": period, "attachments": []}
        for att in attachments_of(cfg, f, ph, post["post_url"]):
            try:
                url = resolve_viewer(cfg, f, att["url"]) if "viewer/pdf.do" in att["url"] else att["url"]
                r = f.get(url, headers={"Referer": post["post_url"]})
                ctype = r.headers.get("Content-Type", "")
                if "text/html" in ctype and not r.content[:5] == b"%PDF-":
                    body = r.content[:400].decode("utf-8", "replace")
                    if "첨부파일이 없습니다" in body:
                        raise RuntimeError("게시판 서버에 첨부파일 없음(응답: '첨부파일이 없습니다')")
                    raise RuntimeError(f"HTML 응답({ctype})")
            except Exception as e:  # noqa: BLE001 - 실패는 매니페스트에 남긴다
                entry["attachments"].append({**att, "error": str(e)[:200]})
                print(f"    ! {att['filename']}: {e}", file=sys.stderr)
                continue
            sha = hashlib.sha256(r.content).hexdigest()
            local = out_dir / f"{sha[:12]}_{safe_name(att['filename'])}"
            if not local.exists():
                local.write_bytes(r.content)
            entry["attachments"].append({
                "filename": att["filename"], "url": url, "local_path": str(local.relative_to(ROOT)), "sha256": sha,
                "bytes": len(r.content), "content_type": ctype, "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
            })
        print(f"  {period} {post['post_title'][:50]} ({len(entry['attachments'])} files)", file=sys.stderr)
        manifest.append(entry)
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{slug}] {len(manifest)} posts, {sum(len(p['attachments']) for p in manifest)} attachments", file=sys.stderr)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("collect", "parse"):
        print(__doc__)
        sys.exit(1)
    slugs = sys.argv[2:] or list(COUNCILS)
    if sys.argv[1] == "collect":
        for s in slugs:
            try:
                collect(s)
            except Exception as e:  # noqa: BLE001 - 한 의회 실패가 다른 의회 수집을 막지 않게
                print(f"[{s}] FAILED: {e}", file=sys.stderr)
    else:
        from g3_parse import parse
        for s in slugs:
            parse(s, COUNCILS[s])


if __name__ == "__main__":
    main()
