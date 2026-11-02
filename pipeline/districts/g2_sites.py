"""G2 구의회(도봉·동대문·동작·서대문·서초·송파·성동·성북) 게시판 어댑터.

게시판 CMS가 네 계열로 나뉜다.
  mapo    : bbsCost.do?reform=view&key=…, 첨부 /bbsAttachDownload.do?key=…  (도봉·송파·성북·서초)
  gwanak  : xxxBBSview.do?uid=…, 첨부 /kr/bbs/download.do?bbs_id=…&uid=…     (동대문·동작)
  sd      : bbs?bbs_id=expenses&reform=view&uid=…, 첨부 bbs_process?reform=download (성동)
  sdm     : /sdmassem/board/26/<page>, /read/<id>, /download/<id>/<fid>      (서대문)
"""
import html
import re

COUNCILS = {
    "dobong": {"name": "도봉구의회", "region": "서울 도봉구", "kind": "mapo",
               "base": "https://www.council-dobong.seoul.kr", "list": "/kr/activity/bbsCost.do"},
    "dongdaemun": {"name": "동대문구의회", "region": "서울 동대문구", "kind": "gwanak",
                   "base": "http://council.ddm.go.kr", "list": "/kr/busiexpensesBBS.do",
                   "view": "/kr/busiexpensesBBSview.do", "bbs_id": "busiexpenses"},
    "dongjak": {"name": "동작구의회", "region": "서울 동작구", "kind": "gwanak",
                "base": "https://assembly.dongjak.go.kr", "list": "/kr/costBBS.do", "view": "/kr/costBBSview.do", "bbs_id": "cost"},
    "seodaemun": {"name": "서대문구의회", "region": "서울 서대문구", "kind": "sdm",
                  "base": "https://www.sdmcouncil.go.kr", "list": "/sdmassem/board/26"},
    "seocho": {"name": "서초구의회", "region": "서울 서초구", "kind": "mapo",
               "base": "https://www.sdc.seoul.kr", "list": "/kr/news/bbsBusiness.do"},
    "songpa": {"name": "송파구의회", "region": "서울 송파구", "kind": "mapo",
               "base": "https://council.songpa.go.kr", "list": "/kr/news/bbsCost.do"},
    "seongdong": {"name": "성동구의회", "region": "서울 성동구", "kind": "sd",
                  "base": "https://sdcouncil.sd.go.kr", "list": "/kr/news/bbs", "verify": False},
    "seongbuk": {"name": "성북구의회", "region": "서울 성북구", "kind": "mapo",
                 "base": "https://www.sbc.go.kr", "list": "/kr/activity/bbsCost.do"},
}


def text(s):
    s = html.unescape(re.sub(r"</?[a-zA-Z][^>]*>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def list_url(c, page):
    if c["kind"] == "mapo":
        return f"{c['base']}{c['list']}?pageNum={page}"
    if c["kind"] == "gwanak":
        return f"{c['base']}{c['list']}?schwrd=&flag=all&page={page}&list_style="
    if c["kind"] == "sd":
        return f"{c['base']}{c['list']}?bbs_id=expenses&page={page}"
    return f"{c['base']}{c['list']}/{page}"


VIEW_RE = {
    "mapo": re.compile(r'href="(\?reform=view&(?:amp;)?key=([0-9a-f]+))[^"]*"[^>]*>(.*?)</a>', re.S),
    "gwanak": re.compile(r'href="(/kr/\w+BBSview\.do\?uid=([0-9A-F]+))[^"]*"[^>]*>(.*?)</a>', re.S),
    "sd": re.compile(r'href="(\?bbs_id=expenses&(?:amp;)?reform=view&(?:amp;)?uid=([0-9A-F]+))[^"]*"[^>]*>(.*?)</a>', re.S),
    "sdm": re.compile(r'href="(/sdmassem/board/26/\d+/read/(\d+))"[^>]*>(.*?)</a>', re.S),
}
DATE_RE = re.compile(r"(20\d{2})[.\-](\d{2})[.\-](\d{2})")


def parse_list(c, page_html):
    """목록 페이지 → [{key, title, view_url, posted_date, row_downloads}] (tr 단위로 읽는다)."""
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, flags=re.S):
        m = VIEW_RE[c["kind"]].search(tr)
        if not m:
            continue
        href, key, title = m.group(1), m.group(2), text(m.group(3))
        href = html.unescape(href)
        if c["kind"] == "mapo":
            view = f"{c['base']}{c['list']}{href}"
        elif c["kind"] == "sd":
            view = f"{c['base']}{c['list']}{href}"
        else:
            view = c["base"] + href
        d = DATE_RE.search(re.sub(r"<[^>]+>", " ", tr[m.end():]))
        row_dl = [html.unescape(h) for h in re.findall(r'href="(/kr/bbs/download\.do\?[^"]+)"', tr)]
        out.append({"key": key, "title": title, "view_url": view,
                    "posted_date": f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else None, "row_downloads": row_dl})
    return out


ATTACH_RE = {
    "mapo": re.compile(r'href=["\'](/bbsAttachDownload\.do\?key=[0-9a-f]+)["\'][^>]*>(.*?)</a>', re.S),
    "gwanak": re.compile(r'href=["\'](/kr/bbs/download\.do\?bbs_id=\w+&(?:amp;)?uid=[0-9A-F]+)["\'][^>]*?(?:title=["\']([^"\']*)["\'])?[^>]*>(.*?)</a>', re.S),
    "sd": re.compile(r'href=["\'](/kr/news/bbs_process\?reform=download&(?:amp;)?bbs_id=expenses&(?:amp;)?uid=\d+)["\'][^>]*>(.*?)</a>', re.S),
    "sdm": re.compile(r'href=["\'](/sdmassem/board/26/\d+/download/\d+/\d+)["\'][^>]*>(.*?)</a>', re.S),
}


def clean_filename(name):
    """'파일.xlsx (32.1KB)', '파일.xls (0Byte)' 같은 크기 표기를 뗀다."""
    return re.sub(r"\s*\(\s*[\d.,]+\s*(?:[KMG]?B|Byte|bytes?)\s*\)\s*$", "", name or "", flags=re.I).strip()


def parse_attachments(c, view_html, row_downloads=()):
    """게시글 본문 → [{filename or None, url}] (중복 제거)."""
    out, seen = [], set()
    for m in ATTACH_RE[c["kind"]].finditer(view_html):
        href = html.unescape(m.group(1))
        if c["kind"] == "gwanak":
            name = text(m.group(3)) or re.sub(r"^'|' 파일 내려받기$|'$", "", text(m.group(2) or ""))
            name = re.sub(r"\s*파일 내려받기$", "", name).strip("' ")
        else:
            name = text(m.group(2))
        name = clean_filename(name)
        url = c["base"] + href
        if url in seen or not name and c["kind"] != "gwanak":
            continue
        seen.add(url)
        out.append({"filename": name or None, "url": url})
    for h in row_downloads:
        url = c["base"] + h
        if url not in seen:
            seen.add(url)
            out.append({"filename": None, "url": url})
    return out


def parse_period_title(title):
    """게시글 제목 → 'YYYY-MM' / 'YYYY-Qn' / 'YYYY' (공통 parse_period보다 넓은 표기 처리)."""
    t = title or ""
    m = re.search(r"(20\d{2})\s*[.년]\s*(\d{1,2})\s*\.?\s*월?\s*~\s*(\d{1,2})\s*\.?\s*월?", t)
    if m:
        y, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= a <= b <= 12:
            if (a - 1) // 3 == (b - 1) // 3:
                return f"{y}-Q{(a - 1) // 3 + 1}"
            return f"{y}"
    m = re.search(r"(20\d{2})\s*년?\s*\.?\s*(?:도\s*)?([1-4])\s*(?:/\s*4\s*)?분기", t)
    if m:
        return f"{m.group(1)}-Q{m.group(2)}"
    m = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월", t) or re.search(r"(20\d{2})\s*\.\s*(\d{1,2})\s*(?:월|\.|\))", t) \
        or re.search(r"(20\d{2})[_\-]?(0[1-9]|1[0-2])(?!\d)", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(20\d{2})\s*년", t)
    return m.group(1) if m else None


def title_range_end(title):
    """'2022년 3월 ~ 6월' 같은 범위 제목의 마지막 달 (YYYY, M). 범위 표기가 없으면 None."""
    m = re.search(r"(20\d{2})\s*[.년]\s*(\d{1,2})\s*\.?\s*월?\s*~\s*(\d{1,2})\s*\.?\s*월?", title or "")
    return (int(m.group(1)), int(m.group(3))) if m else None
