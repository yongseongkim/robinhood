"""관악구의회·마포구의회 직책 보유자(의장단·상임위원장) 수집기.

의회 공식 홈페이지(역대의장단·의회연혁·역대의원·위원회 구성·공지)만 근거로 쓴다.
- 가져온 HTML은 data/raw/roles/<sha256 앞 12자리>_<이름>.html 로 원본 그대로 보관, manifest.json에 URL·sha256·수집 시각 기록
- 결과: data/staging/role_holders.json (페이지에서 직접 읽은 사실만, 근거 문구 포함)
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "roles"
STAGING = ROOT / "data" / "staging"
KST = timezone(timedelta(hours=9))

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 robinhood-collector",
})
_manifest = None


def manifest():
    global _manifest
    if _manifest is None:
        p = OUT / "manifest.json"
        _manifest = json.loads(p.read_text()) if p.exists() else {}
    return _manifest


def save_manifest():
    (OUT / "manifest.json").write_text(json.dumps(manifest(), ensure_ascii=False, indent=1))


def fetch(url, name, referer=None, refresh=False):
    """URL을 가져와 원본을 보관하고 텍스트를 돌려준다. 이미 받은 URL은 보관본을 쓴다."""
    OUT.mkdir(parents=True, exist_ok=True)
    m = manifest().get(url)
    if m and not refresh and (ROOT / m["local_path"]).exists():
        return (ROOT / m["local_path"]).read_bytes().decode("utf-8", errors="replace")
    for attempt in range(3):
        try:
            r = session.get(url, timeout=30, headers={"Referer": referer or url.split("/kr/")[0] + "/"})
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    time.sleep(0.6)
    sha = hashlib.sha256(r.content).hexdigest()
    local = OUT / f"{sha[:12]}_{re.sub(r'[^0-9A-Za-z가-힣_.-]+', '_', name)[:80]}.html"
    local.write_bytes(r.content)
    manifest()[url] = {"url": url, "name": name, "local_path": str(local.relative_to(ROOT)), "sha256": sha,
                       "bytes": len(r.content), "fetched_at": datetime.now(KST).isoformat(timespec="seconds")}
    save_manifest()
    return r.content.decode(r.encoding or "utf-8", errors="replace") if r.encoding else r.content.decode("utf-8", errors="replace")


def fetch_post(url, name, referer):
    """POST로 돌려주는 프로필(JSON) 등을 받아 원본 그대로 보관한다."""
    OUT.mkdir(parents=True, exist_ok=True)
    key = "POST " + url
    m = manifest().get(key)
    if m and (ROOT / m["local_path"]).exists():
        return (ROOT / m["local_path"]).read_bytes().decode("utf-8", errors="replace")
    for attempt in range(3):
        try:
            r = session.post(url, timeout=30, headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    time.sleep(0.6)
    sha = hashlib.sha256(r.content).hexdigest()
    local = OUT / f"{sha[:12]}_{re.sub(r'[^0-9A-Za-z가-힣_.-]+', '_', name)[:80]}.json"
    local.write_bytes(r.content)
    manifest()[key] = {"url": url, "method": "POST", "name": name, "local_path": str(local.relative_to(ROOT)), "sha256": sha,
                       "bytes": len(r.content), "fetched_at": datetime.now(KST).isoformat(timespec="seconds")}
    save_manifest()
    return r.content.decode("utf-8", errors="replace")


def text_of(h):
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</(p|div|li|tr|h\d|dt|dd)>", "\n", h, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return "\n".join(re.sub(r"[ \t ]+", " ", line).strip() for line in t.splitlines() if line.strip())


# ------------------------------------------------------------------ 공통
G = "https://www.ga21c.seoul.kr"
M = "https://council.mapo.seoul.kr"
HALF_TERMS = [  # 의회 대수·전후반기 (의회 공식 일정상 임기 구분)
    ("제8대 전반기", "2018-07-01", "2020-06-30"), ("제8대 후반기", "2020-07-01", "2022-06-30"),
    ("제9대 전반기", "2022-07-01", "2024-06-30"), ("제9대 후반기", "2024-07-01", "2026-06-30"),
    ("제10대 전반기", "2026-07-01", "2028-06-30"),
]
COUNCIL = {"gwanak": "관악구의회", "mapo": "마포구의회"}


def page_text(url, name, referer=None):
    h = fetch(url, name, referer=referer)
    return text_of(re.sub(r"<!--.*?-->", " ", h, flags=re.S))  # 주석 처리되어 화면에 보이지 않는 내용은 제외


def term_of(day):
    for label, s, e in HALF_TERMS:
        if day and s <= day <= e:
            return label
    return None


def ymd(y, m, d):
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def rec(src, role, term, name, start, end, url, title, evidence, confidence, party=None, **extra):
    r = {"council": COUNCIL[src], "source_id": src, "role": role, "term_label": term, "name": name, "start": start, "end": end,
         "party": party, "source_url": url, "source_title": title, "evidence_text": evidence[:120], "confidence": confidence}
    r.update({k: v for k, v in extra.items() if v is not None})
    return r


# ------------------------------------------------------------------ 마포구의회
MAPO_ROLE = {"운영위원장": "의회운영위원장"}


def mapo_history():
    url, title = M + "/kr/intro/cmsHistory.do", "마포구의회 의회연혁"
    lines = page_text(url, "mapo_history").split("\n")
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(.*)$", line)
        if not m:
            continue
        day = ymd(*m.groups()[:3])
        if day < "2018-07-01":
            continue
        body = m.group(4)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        tm = re.search(r"제(\d+)대\s*(전반기|후반기)", body)
        term = f"제{tm.group(1)}대 {tm.group(2)}" if tm else term_of(day)
        if "의장단 선출" in body or "상임위원장 선출" in body:
            for role, name in re.findall(r"([가-힣]*?(?:부의장|의장|위원장))\(([가-힣]{2,4})\)", nxt):
                role = MAPO_ROLE.get(role, role)
                out.append(rec("mapo", role, term, name, day, None, url, title, f"{line} / {nxt}", "HIGH"))
        elif "예산결산특별위원회 구성" in body:
            period = re.search(r"기간\s*:?\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*~\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", line + " " + nxt)
            who = re.search(r"위원장\(([가-힣]{2,4})\)", line + " " + nxt)
            if who:
                start, end = (ymd(*period.groups()[:3]), ymd(*period.groups()[3:])) if period else (day, None)
                out.append(rec("mapo", "예산결산특별위원장", term_of(start), who.group(1), start, end, url, title, f"{line} / {nxt}", "HIGH"))
        elif "윤리특별위원회 구성" in body:
            who = re.search(r"위원장\s*:\s*([가-힣]{2,4})", body)
            if who:
                out.append(rec("mapo", "윤리특별위원장", term_of(day), who.group(1), day, None, url, title, line, "HIGH"))
    return out


def mapo_chairmanlist_check(records):
    """역대의장단 페이지와 교차 확인 (화면에 보이는 내용만). 불일치 목록을 돌려준다."""
    t = page_text(M + "/kr/member/cmsChairmanlist.do", "mapo_chairmanlist")
    issues = []
    for block in re.split(r"\n(?=제\d+대 의회 (?:전반기|후반기)\n)", t):
        hm = re.match(r"제(\d+)대 의회 (전반기|후반기)", block)
        if not hm or int(hm.group(1)) < 8:
            continue
        term = f"제{hm.group(1)}대 {hm.group(2)}"
        listed = {(MAPO_ROLE.get(r, r), n) for n, r in re.findall(r"([가-힣]{2,4})(?:\([^)]*\))?\n직위 : ([가-힣]+)", block)}
        mine = {(r["role"], r["name"]) for r in records if r["term_label"] == term and r["role"] not in ("예산결산특별위원장",)}
        for x in sorted(listed - mine):
            issues.append(f"{term}: 역대의장단에만 있음 {x}")
        for x in sorted(mine - listed):
            issues.append(f"{term}: 의회연혁에만 있음 {x}")
    return issues


def mapo_session_notices():
    """회기별일정계획 게시판: 회기 번호 → (게시일, 게시글 URL). 회기 날짜 자체는 첨부(HWP/PDF)에만 있다."""
    notices = {}
    for page in range(1, 25):
        url = M + f"/kr/news/bbsSession.do?pageNum={page}"
        h = re.sub(r"<!--.*?-->", " ", fetch(url, f"mapo_session_list_p{page}"), flags=re.S)
        rows = re.findall(r"href=['\"]\?reform=view&key=([0-9a-f]+)[^'\"]*['\"][^>]*>\s*(?:<[^>]+>\s*)*([^<]{4,120}?)\s*<.*?(\d{4}\.\d{2}\.\d{2})", h, flags=re.S)
        if not rows:
            break
        for key, title, posted in rows:
            m = re.search(r"제\s*(\d{3})\s*회", title)
            if m:
                notices.setdefault(int(m.group(1)), (posted.replace(".", "-"), M + f"/kr/news/bbsSession.do?reform=view&key={key}", html.unescape(title).strip()))
        if min(notices, default=999) <= 225:
            break
    return notices


def mapo_profiles():
    out, notes = [], []
    notices = None
    for th in (8, 9):
        lst_url = M + f"/kr/member/memberlist.do?sTh={th}"
        lst = re.sub(r"<!--.*?-->", " ", fetch(lst_url, f"mapo_memberlist_{th}"), flags=re.S)
        for key in dict.fromkeys(re.findall(r"/kr/profile/profile\.do\?key=([0-9a-f]+)", lst)):
            url = M + f"/kr/profile/profile.do?key={key}"
            lines = page_text(url, f"mapo_profile_{th}_{key[:10]}", referer=lst_url).split("\n")
            name = next((lines[i + 1] for i, l in enumerate(lines) if l == "마포구의회 의원프로필" and i + 1 < len(lines)), None)
            party = next((l.replace("소속정당", "").strip() for l in lines if l.startswith("소속정당")), None)
            title = f"마포구의회 {name} 의원 프로필"
            for l in lines:
                m = re.search(r"제(\d+)대 (?:마포구의회 )?(?:(제\d+회)\s*(?:제\d차\s*)?(정례회|임시회)\s*)?(전반기|후반기)?\s*예산결산특별위원(?:회\s*위원)?장", l)
                if m and "부위원장" not in l:
                    dates = re.search(r"\((\d{4})\.\s*(\d{1,2})\.\s*(?:(\d{1,2})\.)?\s*~\s*(\d{4})\.\s*(\d{1,2})\.\s*(?:(\d{1,2})\.)?\)", l)
                    term = f"제{m.group(1)}대 {m.group(4)}" if m.group(4) else None
                    start = end = None
                    if dates:
                        g = dates.groups()
                        start = ymd(g[0], g[1], g[2]) if g[2] else f"{int(g[0]):04d}-{int(g[1]):02d}"
                        end = ymd(g[3], g[4], g[5]) if g[5] else f"{int(g[3]):04d}-{int(g[4]):02d}"
                    extra = {}
                    if m.group(2) and not term:
                        notices = notices or mapo_session_notices()
                        n = notices.get(int(re.sub(r"\D", "", m.group(2))))
                        if n:
                            term = term_of(n[0])
                            extra = {"session_notice_url": n[1], "session_notice_posted": n[0],
                                     "note": f"회기 날짜는 의사일정 첨부에만 있음. 의사일정 게시일({n[0]}) 기준으로 {term}로 분류"}
                    out.append(rec("mapo", "예산결산특별위원장", term or f"제{m.group(1)}대",
                                   name, start, end, url, title, l, "HIGH" if dates else "MEDIUM",
                                   session=(m.group(2) + " " + m.group(3)) if m.group(2) else None, **extra))
                m = re.search(r"제(\d+)대 마포구의회 (국민의힘|더불어민주당) 교섭단체 대표위원", l)
                if m:
                    out.append(rec("mapo", f"교섭단체 대표({m.group(2)})", f"제{m.group(1)}대", name, None, None, url, title, l, "MEDIUM",
                                   note="기간 미표기" + (", 전직으로 표기" if l.startswith("(전)") else ", 현재형으로 표기")))
                m = re.search(r"제(\d+)대 마포구의회 마포구 신규 쓰레기소각장 건립 반대 특별위원회 위원장", l)
                if m:
                    out.append(rec("mapo", "신규쓰레기소각장건립반대특별위원장", f"제{m.group(1)}대", name, None, None, url, title, l, "MEDIUM",
                                   note="기간 미표기. 지출자료의 '추가소각장건립반대특별위원장'과 같은 위원회인지는 페이지에 명시되지 않음"))
            if party:
                for r in out:
                    if r["name"] == name and r["source_url"] == url:
                        r["party"] = party
                        r["party_note"] = "프로필의 현재 소속정당 표기(재임 당시 정당과 다를 수 있음)"
    return out, notes


# ------------------------------------------------------------------ 관악구의회
GWANAK_COMMITTEES = ("의회운영위원회", "행정재경위원회", "보건복지위원회", "도시건설위원회")


def gwanak_history():
    url, title = G + "/kr/historyCnts.do", "관악구의회 의회연혁"
    lines = page_text(url, "gwanak_history").split("\n")
    out, term, last_date, i = [], None, None, 0
    while i < len(lines):
        line = lines[i]
        hm = re.match(r"^(\d+)대 \((전반기|후반기)\)$", line)
        if hm:
            term = f"제{hm.group(1)}대 {hm.group(2)}" if int(hm.group(1)) >= 8 else None
            i += 1
            continue
        dm = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})", line)
        if dm:
            last_date = ymd(*dm.groups())
        if term and "상임위원회 구성" in line:
            group, j = [line], i + 1
            while j < len(lines) and any(c in lines[j] for c in GWANAK_COMMITTEES):
                group.append(lines[j])
                j += 1
            ds = [ymd(*d) for d in re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", " ".join(group))]
            day = ds[0] if ds else last_date
            note = None
            lab = re.search(r"제(\d+)대 관악구의회 (전반기|후반기)", line)
            if lab and f"제{lab.group(1)}대 {lab.group(2)}" != term:
                note = f"의회연혁 원문 제목은 '{lab.group(0)}'이나 '{term}' 항목 아래, {day} 구성으로 기재됨"
            for g in group[1:] if not any(c in group[0] for c in GWANAK_COMMITTEES) else group:
                for com, name in re.findall(r"(" + "|".join(GWANAK_COMMITTEES) + r")\s*\(위원장\s*([가-힣]{2,4})", g):
                    out.append(rec("gwanak", com.replace("위원회", "위원장"), term, name, day, None, url, title,
                                   f"{group[0]} / {g}", "HIGH", note=note))
            i = j
            continue
        if term:
            seg = line if "선출" in line else ""
            m = re.search(r"의장단 선출\s*\(의장\s*([가-힣]{2,4}),\s*부의장\s*([가-힣]{2,4})\)", seg)
            if m:
                day = ymd(*re.match(r"^(\d{4})\.(\d{2})\.(\d{2})", line).groups()) if dm else last_date
                ev = line if dm else f"{lines[i - 1]} / {line}"
                out.append(rec("gwanak", "의장", term, m.group(1), day, None, url, title, ev, "HIGH"))
                out.append(rec("gwanak", "부의장", term, m.group(2), day, None, url, title, ev, "HIGH"))
            for role, name in re.findall(r"(부의장|의장) 선출\s*\((?:부의장|의장)\s*([가-힣]{2,4})\)", seg):
                out.append(rec("gwanak", role, term, name, last_date, None, url, title, line, "HIGH"))
        i += 1
    return out


def gwanak_sessions():
    t = page_text(G + "/kr/yearSessionCnts.do", "gwanak_year_sessions")
    blocks = re.split(r"\n(20\d\d)년도 의회운영 일정\n", t)
    sess = {}
    for k in range(1, len(blocks), 2):
        y = int(blocks[k])
        for m in re.finditer(r"제\s*(\d{3})회\s*\n?\s*\((임시회|정례회)\)\s*\n\s*([0-9.\s~]+?)\s*\n", blocks[k + 1]):
            ds = re.findall(r"(\d{1,2})\.\s*(\d{1,2})", m.group(3))
            if ds:
                sess[int(m.group(1))] = (m.group(2), ymd(y, *ds[0]), ymd(y, *ds[-1]), m.group(3).strip())
    return sess


def gwanak_profiles(sess):
    out, conflicts = [], []
    uids = {}
    chron = re.sub(r"<!--.*?-->", " ", fetch(G + "/kr/member/chronicle.do", "gwanak_chronicle"), flags=re.S)
    heads = sorted((m.start(), int(m.group(1))) for m in re.finditer(r"(\d+)대 의원", chron))
    first = {}
    for pos, th in heads:
        first.setdefault(th, pos)
    order = sorted(first.items(), key=lambda kv: kv[1])
    for n, (th, pos) in enumerate(order):
        end = order[n + 1][1] if n + 1 < len(order) else len(chron)
        if th in (8, 9):
            for uid, nm in re.findall(r'data-uid="(\d+)"\s+title="([^"]+?) 의원', chron[pos:end]):
                uids.setdefault(uid, nm)
    cur = re.sub(r"<!--.*?-->", " ", fetch(G + "/kr/member/name.do", "gwanak_current_members"), flags=re.S)
    for uid, nm in re.findall(r'data-uid="(\d+)"\s+title="([^"]+?) 의원', cur):
        uids.setdefault(uid, nm)
    by_session = {}
    for uid in sorted(uids, key=int):
        purl = G + f"/common/async/member/{uid}.do"
        d = json.loads(fetch_post(purl, f"gwanak_profile_{uid}", G + "/kr/member/chronicle.do"))
        name = d.get("name")
        for line in re.split(r"[\r\n]+", d.get("career") or ""):
            line = line.strip().lstrip("-").strip()
            if "예산결산" not in line or "위원장" not in line or "부위원장" in line:
                continue
            tm = re.search(r"제\s*(\d+)대", line)
            nums = [int(x) for x in re.findall(r"(\d{3})(?=\s*회|·)", line.replace("제", ""))]
            if not tm or int(tm.group(1)) < 8 or "·" in line.split("관악구의회")[0] and not nums:
                continue
            for no in nums or [None]:
                s = sess.get(no) if no else None
                term = term_of(s[1]) if s else f"제{tm.group(1)}대"
                note = None if s else "회기 날짜를 의회 연간회기일정 페이지에서 찾지 못함(2018년 회기는 페이지에 없음)"
                if not s and no and 249 < no < 255:
                    term = "제8대 전반기"
                    note = ("회기 날짜 미게재. 의회연혁의 '2018.07.06 제8대 개원 및 제249회 임시회'와 연간회기일정의 "
                            "'제255회 2019.1.15~' 사이 회기이므로 제8대 전반기(2018년 하반기)로 분류")
                r = rec("gwanak", "예산결산특별위원장", term, name,
                        s[1] if s else None, s[2] if s else None, G + "/kr/member/chronicle.do",
                        f"관악구의회 역대의원 {name} 의원 프로필(경력)", line, "MEDIUM",
                        session=f"제{no}회" if no else None,
                        session_dates_source=(G + "/kr/yearSessionCnts.do") if s else None, note=note,
                        source_api=f"POST {purl} (역대의원 페이지 '프로필보기' 팝업이 불러오는 경력)")
                if no and no in by_session and by_session[no]["name"] != name:
                    conflicts.append(f"제{no}회 예결위원장: {by_session[no]['name']} vs {name}")
                if no and no in by_session:
                    continue
                if no:
                    by_session[no] = r
                out.append(r)
    return out, conflicts


def gwanak_party(records):
    chron = re.sub(r"<!--.*?-->", " ", fetch(G + "/kr/member/chronicle.do", "gwanak_chronicle"), flags=re.S)
    t = text_of(chron)
    rosters = {}
    for block in re.split(r"\n(?=\d+대 의원\n)", t):
        m = re.match(r"(\d+)대 의원", block)
        if m:
            for nm, party in re.findall(r"([가-힣]{2,4})\n선 거 구 : [^\n]+\n소속정당 : ([^\n]+)", block):
                rosters.setdefault(int(m.group(1)), {})[nm] = party.strip()
    cur = page_text(G + "/kr/member/name.do", "gwanak_current_members")  # 제10대 현역의원
    for nm, party in re.findall(r"([가-힣]{2,4})\n(?:직 위 : [^\n]+\n)?선 거 구 : [^\n]+\n소속정당 : ([^\n]+)", cur):
        rosters.setdefault(10, {})[nm] = party.strip()
    for r in records:
        tm = re.search(r"제(\d+)대", r["term_label"] or "")
        if tm and r["party"] is None:
            p = rosters.get(int(tm.group(1)), {}).get(r["name"])
            if p:
                r["party"] = p
                r["party_note"] = "역대의원 명단의 해당 대수 소속정당 표기(표기 시점 불명, 재임 당시 정당과 다를 수 있음)"


def mapo_party(records):
    rosters = {}
    for th in (8, 9):
        t = page_text(M + f"/kr/member/memberlist.do?sTh={th}", f"mapo_memberlist_{th}")
        for nm, party in re.findall(r"\n([가-힣]{2,4})\n직위 :\n[^\n]+\n선거구 :\n[^\n]+\n(?:\([^\n]*\)\n)?소속정당 :\n([^\n]+)", t):
            rosters.setdefault(th, {})[nm] = party.strip()
    t = page_text(M + "/kr/member/active.do", "mapo_current_members")  # 제10대 현역의원
    for nm, party in re.findall(r"\n([가-힣]{2,4})\n(?:직위 :\n[^\n]+\n)?선거구 :\n[^\n]+\n(?:\([^\n]*\)\n)?소속정당 :\n([^\n]+)", t):
        rosters.setdefault(10, {})[nm] = party.strip()
    for r in records:
        tm = re.search(r"제(\d+)대", r["term_label"] or "")
        if tm and r["party"] is None:
            p = rosters.get(int(tm.group(1)), {}).get(r["name"])
            if p:
                r["party"] = p
                r["party_note"] = "역대의원·현역의원 명단의 해당 대수 소속정당 표기(표기 시점 불명, 재임 당시 정당과 다를 수 있음)"
    return rosters


def main():
    records, issues = [], []
    mh = mapo_history()
    issues += mapo_chairmanlist_check(mh)
    mp, _ = mapo_profiles()
    # 의회연혁에 기간까지 있는 9대 이후 예결위원장은 프로필 중복을 버린다
    have = {(r["name"], r["start"]) for r in mh if r["role"] == "예산결산특별위원장"}
    mp = [r for r in mp if not (r["role"] == "예산결산특별위원장" and (r["name"], r["start"]) in have)
          and not (r["role"] == "예산결산특별위원장" and r["term_label"] and r["term_label"].startswith("제9대")
                   and any(h["name"] == r["name"] for h in mh if h["role"] == "예산결산특별위원장"))]
    mapo_party(mh + mp)
    records += mh + mp
    gh = gwanak_history()
    gp, conflicts = gwanak_profiles(gwanak_sessions())
    issues += conflicts
    gwanak_party(gh + gp)
    records += gh + gp
    seen, uniq = set(), []
    for r in records:
        k = (r["source_id"], r["role"], r["term_label"], r["name"], r["start"], r.get("session"))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    uniq.sort(key=lambda r: (r["source_id"], r["start"] or r["term_label"] or "", r["role"]))
    STAGING.mkdir(parents=True, exist_ok=True)
    (STAGING / "role_holders.json").write_text(json.dumps(uniq, ensure_ascii=False, indent=1))
    print(f"{len(uniq)} role holder records", file=sys.stderr)
    for x in issues:
        print("  check:", x, file=sys.stderr)


if __name__ == "__main__":
    main()
