"""서울특별시의회 직책 보유자(의장단·상임위원장·예결위원장·교섭단체 대표의원) 수집기.

서울특별시의회 공식 홈페이지(https://www.smc.seoul.kr)만 근거로 쓴다.
- 역대의장단·의장단 구성·교섭단체 대표 페이지, 그리고 의회 보도자료 게시판(boardTypeId=66)의
  선출 보도자료 본문과 첨부 PDF.
- 가져온 원문은 data/raw/roles_seoul/<sha256 앞 12자리>_<이름>.<html|pdf> 로 그대로 보관하고
  manifest.json 에 URL·sha256·수집 시각을 기록한다.
- 각 기록은 원문에서 정규식으로 찾은 문구(evidence_text)가 있어야만 출력한다. 찾지 못하면 버리고 보고한다.
- 결과: data/staging/role_holders_seoul.json (data/staging/role_holders.json 과 같은 형식)
"""
import hashlib
import html
import io
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pdfplumber
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "roles_seoul"
STAGING = ROOT / "data" / "staging"
KST = timezone(timedelta(hours=9))
BASE = "https://www.smc.seoul.kr"
PRESS_LIST = BASE + "/board/BoardList.do?boardTypeId=66&menuId=001006002"
PRESS_URL = BASE + "/board/BoardDetail.do?boardId={bid}&boardTypeId=66&menuId=001006002"
FILE_RE = re.compile(r"fileDown\('(\d+)','([^']*)','([^']*)'\)")

PAGES = {
    "history": (BASE + "/publish/view.do?menuId=001002002001", "서울특별시의회 역대의장단"),
    "leaders": (BASE + "/publish/view.do?menuId=001002006001", "서울특별시의회 의장단 구성"),
    "groups": (BASE + "/main/organization.do?menuId=001001007002", "서울특별시의회 교섭단체 대표"),
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 robinhood-collector",
})
_manifest = None
_warmed = False


def manifest():
    global _manifest
    if _manifest is None:
        p = OUT / "manifest.json"
        _manifest = json.loads(p.read_text()) if p.exists() else {}
    return _manifest


def save_manifest():
    (OUT / "manifest.json").write_text(json.dumps(manifest(), ensure_ascii=False, indent=1))


def request(method, url, **kw):
    global _warmed
    if not _warmed:  # 메인 페이지에서 세션 쿠키를 먼저 받는다
        session.get(BASE + "/main/index.do", timeout=30)
        _warmed = True
        time.sleep(1.2)
    for attempt in range(6):
        try:
            r = session.request(method, url, timeout=30, **kw)
            if r.status_code == 503:
                raise requests.HTTPError("503")
            r.raise_for_status()
            time.sleep(1.2)
            return r
        except requests.RequestException as e:
            if attempt == 5:
                raise
            wait = 3 * (attempt + 1)
            print(f"  retry {url} in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)


def store(key, name, body, ext, url, extra=None):
    OUT.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(body).hexdigest()
    local = OUT / f"{sha[:12]}_{re.sub(r'[^0-9A-Za-z가-힣_.-]+', '_', name)[:80]}.{ext}"
    if not local.exists():
        local.write_bytes(body)
    manifest()[key] = {"url": url, "name": name, "local_path": str(local.relative_to(ROOT)), "sha256": sha,
                       "bytes": len(body), "fetched_at": datetime.now(KST).isoformat(timespec="seconds"), **(extra or {})}
    save_manifest()
    return local


def cached(key):
    m = manifest().get(key)
    if m and (ROOT / m["local_path"]).exists():
        return (ROOT / m["local_path"]).read_bytes()
    return None


def html_text(raw):
    t = raw.decode("utf-8", errors="replace")
    t = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", t, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))).strip()


def page_text(key):
    url, name = PAGES[key]
    raw = cached(url)
    if raw is None:
        raw = request("GET", url, headers={"Referer": BASE + "/main/index.do"}).content
        store(url, name, raw, "html", url)
    return html_text(raw)


def pdf_text(raw):
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pdf.pages)).strip()
    except Exception as e:  # PDF가 아니거나 깨진 파일
        return f"(PDF 판독 실패: {e})"


def press(bid):
    """보도자료 게시글 본문과 첨부 PDF 텍스트. (제목, 등록일, 본문+PDF 텍스트) 를 돌려준다."""
    url = PRESS_URL.format(bid=bid)
    raw = cached(url)
    if raw is None:
        raw = request("GET", url, headers={"Referer": PRESS_LIST}).content
        store(url, f"보도자료_{bid}", raw, "html", url)
    page = raw.decode("utf-8", errors="replace")
    text = html_text(raw)
    i = text.find("맨 위로 가기")
    j = text.find("목록 -->", i)
    body = text[i + 6:j if j > 0 else i + 2500].strip()
    m = re.search(r"^(.*?) 등록일 : (\d{4}-\d{2}-\d{2})", body)
    title, posted = (m.group(1).strip(), m.group(2)) if m else (body[:80], None)
    title = re.sub(r"^기\s+", "", title)  # 화면의 '기' 표식(아이콘 대체 문자) 제거
    texts = [body]
    for fid, dirname, fname in dict.fromkeys(FILE_RE.findall(page)):
        if not fname.lower().endswith(".pdf"):
            continue
        key = f"file:{fid}"
        data = cached(key)
        if data is None:
            data = request("POST", BASE + "/board/fileDown.do", headers={"Referer": url},
                           data={"fileId": fid, "dirName": dirname, "fileName": "", "originalName": fname}).content
            store(key, f"보도자료_{bid}_{fname}", data, "pdf",
                  f"{BASE}/common/fileTrans.do?fileId={fid}&articleId={bid}&objectId=66&groupId=B",
                  {"board_id": bid, "filename": fname})
        texts.append(pdf_text(data))
    return title, posted, " ".join(texts), url


# ---------------------------------------------------------------- 기록 정의
# 각 기록: 근거 문서(PAGES 키 또는 보도자료 번호)와, 그 문서에서 반드시 찾아야 하는 정규식.
# 찾은 문구가 evidence_text 가 된다. 날짜는 근거 문서에 적힌 것만 쓴다.
T11A, T11B, T12A = "제11대 전반기", "제11대 후반기", "제12대 전반기"
SPECS = []


def spec(role, term, name, src, pattern, start=None, end=None, confidence="HIGH", party=None, note=None, also=()):
    """also: [(문서, 정규식)] — 날짜·명칭 변경 등 기록의 다른 부분도 원문에서 확인해야 할 때."""
    SPECS.append(dict(role=role, term_label=term, name=name, src=src, pattern=pattern, start=start, end=end,
                      confidence=confidence, party=party, note=note, also=list(also)))


VICE_NOTE = ("서울시의회 공식 페이지에는 두 부의장 중 누가 제1부의장·제2부의장인지 적혀 있지 않다. "
             "지출 자료의 '제1부의장'·'제2부의장'과 자동으로 연결하지 말 것.")
GROUP_NOTE = "공식 페이지 표기는 '대표의원' 또는 '원내대표'(교섭단체 대표)."

# ---- 제11대 전반기 (2022-07-01 ~ 2024-06-30)
spec("의장", T11A, "김현기", "history", r"김현기 제25대 의장 출신선거구 : 강남구 제3선거구 \(2022\.07\.01 ~ 2024\.06\.30\)", "2022-07-01", "2024-06-30",
     party="국민의힘", also=[(134892, r"전반기 의장에는 국민의힘 김현기 의원\(강남3\)")])
spec("부의장", T11A, "남창진", "history", r"남창진 \(전반기\) 송파구 제2선거구 \(2022\.07\.01 ~ 2024\.06\.30\)", "2022-07-01", "2024-06-30", note=VICE_NOTE)
spec("부의장", T11A, "우형찬", "history", r"우형찬 \(전반기\) 양천구 제3선거구 \(2022\.07\.01 ~ 2024\.06\.30\)", "2022-07-01", "2024-06-30", note=VICE_NOTE)
spec("의회운영위원장", T11A, "박환희", 134944, r"7월 11일\(월\), 제310회 임시회를 개최해 제11대 의회 전반기 서울시의회를 이끌어갈 운영위원장으로 박환희 의원\(국민의힘, 노원2\)을 선출했다",
     "2022-07-11", party="국민의힘")
spec("행정자치위원장", T11A, "김원태", 135010, r"제11대 전반기 행정자치위원장으로 김원태 의원\(국민의힘, 송파6\)이 선출됐다", "2022-07-15", party="국민의힘",
     also=[(135010, r"15일 제311회 임시회 제1차 본회의를 열어 행정자치위원회 위원장 등을 선출")])
spec("기획경제위원장", T11A, "이숙자", 135018, r"7월 15일\(금\)에 개최된 제311회 임시회에서 이숙자 위원장은", "2022-07-15", party="국민의힘",
     also=[(135018, r"이숙자 의원\(국민의힘, 서초2\)이 선출됐다")])
spec("환경수자원위원장", T11A, "봉양순", 135015, r"봉양순 의원\(더불어민주\s?당, 노원 ?3\)이 제11대 서울시의회 전반기 환경수자원위원회 위원장으로 선출되었다", "2022-07-15",
     party="더불어민주당", also=[(135015, r"7월 15일\(금\) 서울시의회 본회의장에서 열린 제311회 서울특별시의회 임시회에서")])
spec("문화체육관광위원장", T11A, "이종환", 135005, r"이종환 의원\(국민의힘, 강북1\)은 지난 15일 열린 제311회 임시회 본회의에서 제11대 서울특별시의회 문화체육관광위원회 위원장으로 당선됐다",
     "2022-07-15", party="국민의힘")
spec("보건복지위원장", T11A, "강석주", 135017, r"15일\(금\) 제311회 임시회 제1차 본회의를 열고 제11대 전반기 보건복지위원장으로 강석주 의원\(국민의힘, 강서구 제2선거구\)을 선출했다",
     "2022-07-15", party="국민의힘")
spec("도시안전건설위원장", T11A, "송도호", 135016, r"지난 15일[^□]{0,80}제311회 임시회를 열고 도시안전건설위원장에 송도호 의원\(더불어민주당, 관악1\)을 선출했다", "2022-07-15",
     party="더불어민주당")
spec("주택균형개발위원장", T11A, "민병주", 135007, r"7월 15일\(금\) 제311회 임시회를 개최하여, 향후 2년간 도시주택위원회를 이끌어갈 위원장으로 민병주 의원\(국민의힘, 중랑구 제4선거구\)을 선출했다",
     "2022-07-15", party="국민의힘", confidence="MEDIUM",
     note="선출 당시 위원회 명칭은 '도시주택위원회'. 이후 '주택균형개발위원회'(2022-07-25 부위원장 선출 보도자료), '주택공간위원회'(2022-09-21 보도자료)로 바뀌었다.",
     also=[(135167, r"전반기 주택균형개발위원회 부위원장")])
spec("주택공간위원장", T11A, "민병주", 136989, r"서울시의회 주택공간위원회 민병주 위원장", "2022-07-15", party="국민의힘", confidence="MEDIUM",
     note="2022-07-15 '도시주택위원장'으로 선출(같은 위원회의 바뀐 명칭). 선출일은 제11대 전반기 도시주택위원장 선출 보도자료 기준.",
     also=[(135007, r"위원장으로 민병주 의원\(국민의힘, 중랑구 제4선거구\)을 선출했다")])
spec("도시계획균형위원장", T11A, "도문열", 135006, r"원\(국민의힘, 영등포구 제3선거구\)을 제11대 도시계획위원회 위원장으로 선출했다", "2022-07-15", party="국민의힘",
     confidence="MEDIUM", note="선출 당시 위원회 명칭은 '도시계획위원회'. 2022-11-07 보도자료 제목에 '도문열 도시계획균형위원장'으로 나온다.",
     also=[(140823, r"도문열 도시계획균형위원장")])
spec("교통위원장", T11A, "박중화", 135014, r"7월 15일\(금\)\)를 통해 제11대 서울시의회 전반기 교통위원장으로 선출됐다", "2022-07-15",
     also=[(135014, r"박중화 의원, 제11대 서울특별시의회 전반기 교통위원장으로 선출")])
spec("교육위원장", T11A, "이승미", 135009, r"15일\(금\) 제311회 임시회 제1차 본회의를 열고 제11대 전반기 교육위원장으로 이승미 의원\(더불어민주당, 서대문 제3선거구\)을 선출했다",
     "2022-07-15", party="더불어민주당")
spec("예산결산특별위원장", T11A, "이성배", 135097, r"7월 21일\(목\) 개최된 제311회 임시회에서[^□]{0,80}이성배 의원\(국민의힘, 송파4\)을 위원장으로 선출하였다",
     "2022-07-21", party="국민의힘",
     note="예산결산특별위원회 위원장은 기(期)별로 선출되며 선임된 날부터 1년간 재임한다(제11대 제3기 보도자료 기준). 제1기의 종료일은 공식 자료에서 확인하지 못함.")
spec("예산결산특별위원장", T11A, "이병도", 162997, r"서울시의회 예산결산특별위원회 이병도 위원장 선출", "2023-11-20", confidence="MEDIUM",
     note="본문 세부내용은 HWP 첨부라 읽지 않았고 게시글 제목만 근거로 한다. 시작일은 게시일 기준(제11대 제2기).")
spec("교섭단체 국민의힘", T11A, "최호정", "history", r"제11대 서울시의회 국힘의힘 대표의원\(전반기\)", confidence="MEDIUM", party="국민의힘",
     note=GROUP_NOTE + " 역대의장단 페이지 표기('국힘의힘')를 그대로 인용. 정확한 선출일은 확인하지 못함.",
     also=[(134892, r"국민의힘 최호정·더불어민주당 정진술 원내대표")])
spec("교섭단체 더불어민주당", T11A, "정진술", 134892, r"국민의힘 최호정·더불어민주당 정진술 원내대표", confidence="MEDIUM", party="더불어민주당",
     note=GROUP_NOTE + " 정확한 선출일·사임일은 확인하지 못함. 2023-04-10 후임 원내대표 추대 보도자료가 있다.")
spec("교섭단체 더불어민주당", T11A, "송재혁", 153356, r"서울시의회 더불어민주당 새 원내대표에 송재혁 의원 만장일치 추대", "2023-04-10", confidence="MEDIUM", party="더불어민주당",
     note=GROUP_NOTE + " 시작일은 보도자료 등록일 기준.")

# ---- 제11대 후반기 (2024-07-01 ~ 2026-06-30)
spec("의장", T11B, "최호정", "history", r"최호정 제26대 의장 출신선거구 : 서초구 제4선거구 \(2024\.07\.01 ~ 2026\.06\.30\)", "2024-07-01", "2026-06-30", party="국민의힘")
spec("부의장", T11B, "이종환", "history", r"이종환 \(후반기\) 강북구 제1선거구 \(2024\.07\.01 ~ 2026\.06\.30\)", "2024-07-01", "2026-06-30", note=VICE_NOTE)
spec("부의장", T11B, "김인제", "history", r"김인제 \(후반기\) 구로구 제2선거구 \(2024\.07\.01 ~ 2026\.06\.30\)", "2024-07-01", "2026-06-30", note=VICE_NOTE)
CHAIRS_11B = [("의회운영위원장", "운영위원장", "이숙자", "국민의힘, 서초2"), ("행정자치위원장", "행정자치위원장", "장태용", "국민의힘, 강동4"),
              ("기획경제위원장", "기획경제위원장", "임춘대", "국민의힘, 송파3"), ("환경수자원위원장", "환경수자원위원장", "임만균", "더불어민주당, 관악3"),
              ("문화체육관광위원장", "문화체육관광위원장", "김경", "더불어민주당, 강서1"), ("보건복지위원장", "보건복지위원장", "김영옥", "국민의힘, 광진3"),
              ("도시안전건설위원장", "도시안전건설위원장", "강동길", "더불어민주당, 성북3"), ("주택공간위원장", "주택공간위원장", "김태수", "국민의힘, 성북4"),
              ("도시계획균형위원장", "도시계획균형위원장", "김길영", "국민의힘, 강남6"), ("교통위원장", "교통위원장", "이병윤", "국민의힘, 동대문1"),
              ("교육위원장", "교육위원장", "박상혁", "국민의힘, 서초1")]
for role, printed, name, aff in CHAIRS_11B:
    spaced = r"\s?".join(name)
    spec(role, T11B, name, 174387, rf"△{printed} {spaced} 의원\({re.escape(aff)}, (초선|재선|3선)\)", "2024-07-29", party=aff.split(",")[0],
         also=[(174387, r"29일\(월\) 제325회 임시회 본회의를 열고, 이숙자 운영위원장을 비롯한 상임위원장 11명을 선출했다")])
spec("예산결산특별위원장", T11B, "최민규", 175269, r"8월 27일\(화\) 개최된 제326회 임시회에서[^□]{0,80}위원장으로 최민규 의원\(국민의힘, 동작2\)을 선출하였다", "2024-08-27",
     party="국민의힘", note="예산결산특별위원회 위원장은 선임된 날로부터 1년간 재임한다(같은 보도자료, 제11대 제3기).",
     also=[(175269, r"선임된 날로부터 1년간 재임")])
spec("예산결산특별위원장", T11B, "황철규", 183286, r"예산결산특별위원회 위원장으로 황철규 의원\(성동4, 국민\s?의\s?힘\)을 선출했다", "2025-09-05", party="국민의힘",
     confidence="MEDIUM", note="보도자료에 선출일이 없어 시작일은 보도자료 배포일(2025-09-05) 기준.")
spec("교섭단체 국민의힘", T11B, "이성배", 174387, r"국민의힘은 이성배 의원, 더불어민주당은 성흠제 의원을 각각 교섭단체 대표의원으로 선출하였다", confidence="MEDIUM",
     party="국민의힘", note=GROUP_NOTE + " 보도자료(2024-07-29)에 '지난달' 선출로만 적혀 있어 정확한 날짜는 확인하지 못함.")
spec("교섭단체 더불어민주당", T11B, "성흠제", 174387, r"국민의힘은 이성배 의원, 더불어민주당은 성흠제 의원을 각각 교섭단체 대표의원으로 선출하였다", confidence="MEDIUM",
     party="더불어민주당", note=GROUP_NOTE + " 보도자료(2024-07-29)에 '지난달' 선출로만 적혀 있어 정확한 날짜는 확인하지 못함.")


# ---- 제12대 전반기 (2026-07-01 ~ )
def loose(text):
    """보도자료 PDF의 띄어쓰기가 들쭉날쭉해(예: '한 신', '기획경제 위원장') 글자 사이 공백을 허용한다."""
    return r"\s?".join(re.escape(ch) for ch in text if not ch.isspace())


spec("의장", T12A, "임만균", 189455, r"전반기 의장으로 더불어민주당 임만균 의원\(관악3\)이 선출됐다", "2026-07-07", party="더불어민주당",
     also=[(189455, r"2026년 7월 7일\(화\) 오후 2시 제12대 서울시의회 첫 임\s?시회를 개최하여 의장과 부의장을 선출했다"),
           ("leaders", r"의장 임만균 소속정당 더불어민주당")])
for name, aff in (("성흠제", "더불어민주당 성흠제 의원\\(은평1\\)"), ("이성배", "국민의힘 이성배 의원\\(송파4\\)")):
    spec("부의장", T12A, name, 189455, r"부의장에는 더불어민주당 성흠제 의원\(은평1\), 국민의힘 이성배 의원\(송파4\)이 선출됐다", "2026-07-07",
         party=aff.split(" ")[0], note=VICE_NOTE)
CHAIRS_12A = [("의회운영위원장", "운영위원장", "이병도", "더불어민주당, 은평2"), ("행정자치위원장", "행정자치위원장", "이민옥", "더불어민주당, 성동3"),
              ("기획경제위원장", "기획경제위원장", "이준형", "더불어민주당, 강동3"), ("환경수자원위원장", "환경수자원위원장", "이민석", "국민의힘, 마포1"),
              ("문화체육관광위원장", "문화체육관광위원장", "황철규", "국민의힘, 성동4"), ("보건복지위원장", "보건복지위원장", "김경우", "더불어민주당, 동작2"),
              ("도시안전건설위원장", "도시안전건설위원장", "박칠성", "더불어민주당, 구로4"), ("주택공간위원장", "주택공간위원장", "박승진", "더불어민주당, 중랑3"),
              ("도시계획균형위원장", "도시계획균형위원장", "고광민", "국민의힘, 서초3"), ("교통위원장", "교통위원장", "한신", "더불어민주당, 성북1"),
              ("교육위원장", "교육위원장", "김호진", "더불어민주당, 서대문2")]
for role, printed, name, aff in CHAIRS_12A:
    spec(role, T12A, name, 189565, loose(printed + name) + r"\s?\(" + loose(aff) + r"\)", "2026-07-21", party=aff.split(",")[0],
         also=[(189565, r"2026년 7월 21일\(화\) 오후 2시 제338회 임시회를 개최")])
spec("예산결산특별위원장", T12A, "박유진", 190090, r"8월 25일\(화\) 개최된 제339회 임시회에서[^□]{0,80}박유진 의원\(더불어민주당, 은평3\)을 위원장으로 선출", "2026-08-25",
     party="더불어민주당", note="예산결산특별위원회 위원장은 기(期)별로 선출된다.")
spec("교섭단체 국민의힘", T12A, "김길영", 189286, r"김길영 서울시의원, 제12대 서울특별시의회 국민의힘 교섭단체 대표의원 당선", "2026-07-01", confidence="MEDIUM",
     party="국민의힘", note=GROUP_NOTE + " 2026-06-29 당선(게시글), 시작일은 제12대 임기 시작일. 대표의원 임기 종료일은 확인하지 못함.")
spec("교섭단체 더불어민주당", T12A, "이상훈", 189356, r"12대 서울시의회 더불어민주당 이상훈 대표의원 취임", "2026-07-01", confidence="MEDIUM",
     party="더불어민주당", note=GROUP_NOTE + " 시작일은 취임 게시글 등록일. 대표의원 임기 종료일은 확인하지 못함.",
     also=[("groups", r"12대 서울시의회 더불어민주당 대표의원 이상훈입니다")])


def build():
    out, missing = [], []
    for s in SPECS:
        if isinstance(s["src"], str):
            text, url, title = page_text(s["src"]), PAGES[s["src"]][0], PAGES[s["src"]][1]
        else:
            title, _posted, text, url = press(s["src"])
        m = re.search(s["pattern"], text)
        if not m:
            missing.append({**{k: s[k] for k in ("role", "term_label", "name", "src")}, "reason": "근거 문구를 원문에서 찾지 못함"})
            continue
        bad = [str(src) for src, pat in s["also"]
               if not re.search(pat, page_text(src) if isinstance(src, str) else press(src)[2])]
        if bad:
            missing.append({**{k: s[k] for k in ("role", "term_label", "name", "src")}, "reason": f"보조 근거를 찾지 못함: {bad}"})
            continue
        ev = m.group(0)
        if len(ev) > 120:
            ev = ev[:117] + "..."
        rec = {"council": "서울특별시의회", "source_id": "seoul", "role": s["role"], "term_label": s["term_label"],
               "name": s["name"], "start": s["start"], "end": s["end"], "party": s["party"], "source_url": url,
               "source_title": title, "evidence_text": ev, "confidence": s["confidence"]}
        if s["party"]:
            rec["party_note"] = "근거 문서에 적힌 소속 정당"
        if s["note"]:
            rec["note"] = s["note"]
        out.append(rec)
    return out, missing


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--dump":  # 근거 문서 내용 확인용
        for a in sys.argv[2:]:
            if a in PAGES:
                print("=====", a, page_text(a)[:3000])
            else:
                title, posted, text, url = press(a)
                print("=====", a, posted, title, "\n", text[:2500])
        return
    records, missing = build()
    (STAGING / "role_holders_seoul.json").write_text(json.dumps(records, ensure_ascii=False, indent=1))
    print(f"{len(records)} records, {len(missing)} missing", file=sys.stderr)
    for m in missing:
        print("  missing:", m, file=sys.stderr)


if __name__ == "__main__":
    main()
