"""파이프라인 공통 유틸리티: 경로, 문자열 정규화, 거래처 키, 공휴일, 개인정보 마스킹."""
import hashlib
import json
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

import holidays

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"
NORMALIZED = ROOT / "data" / "normalized"
SITE = ROOT / "site"

WEEKDAYS_KO = "월화수목금토일"


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_json(path, obj, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent))


def parse_period(title):
    """게시글 제목의 공개 대상 기간: '2026-07' (월), '2022-Q1' (분기), '2021' (연)."""
    m = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월", title or "")
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(20\d{2})\s*년\s*(?:도\s*)?(\d)\s*(?:/\s*4\s*)?분기", title or "")
    if m:
        return f"{m.group(1)}-Q{m.group(2)}"
    m = re.search(r"(20\d{2})\s*년", title or "")
    return m.group(1) if m else None


def period_range(period):
    """parse_period 결과 → (시작일, 종료일) ISO 문자열."""
    if not period:
        return None, None
    y = int(period[:4])
    if re.fullmatch(r"\d{4}-\d{2}", period):
        mth = int(period[5:])
        end = date(y + (mth == 12), mth % 12 + 1, 1)
        return f"{period}-01", date.fromordinal(end.toordinal() - 1).isoformat()
    m = re.fullmatch(r"\d{4}-Q(\d)", period)
    if m:
        q = int(m.group(1))
        s = date(y, 3 * q - 2, 1)
        e = date(y + (q == 4), (3 * q) % 12 + 1, 1)
        return s.isoformat(), date.fromordinal(e.toordinal() - 1).isoformat()
    return f"{y}-01-01", f"{y}-12-31"


def short_hash(*parts, n=10):
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:n]


def clean_text(s):
    """NFKC(전각→반각), 전각 공백·줄바꿈 제거, 연속 공백 축약."""
    if s is None:
        return None
    s = unicodedata.normalize("NFKC", str(s)).replace("　", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


CORP_MARKERS = re.compile(
    r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|사단법인|\(재\)|재단법인|\(합\)|합자회사|\(학\)|^주\)|\(주$|주\)$"
)


PHONE_RE = re.compile(r"(?<!\d)(0\d{1,2})[-.\s)]?\d{3,4}[-.\s]?\d{4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def mask_contacts(s):
    """자유 기재 텍스트의 전화번호·이메일을 가린다 (지역번호·통신사 앞자리만 남김)."""
    if not s:
        return s
    s = PHONE_RE.sub(lambda m: m.group(1) + "-****-****", s)
    return EMAIL_RE.sub("(이메일 비공개)", s)


def merchant_key(name):
    """동일 업체의 표기 차이(법인 표기, 공백, 괄호, 전각문자)를 흡수한 비교용 키."""
    s = clean_text(name)
    if not s:
        return None
    s = CORP_MARKERS.sub("", s)
    s = re.sub(r"[\s()\[\]{}·.,'\"&\-_/]+", "", s).lower()
    return s or None


BIZNO_RE = re.compile(r"^(\d{3})-?(\d{2})-?(\d{5})$")
PLACEHOLDER_BIZNO = {"9999999999", "0000000000", "1111111111", "1234567890"}


def parse_bizno(raw):
    """사업자등록번호 형식 검증. (정규화된 번호, 구분) 반환. 생년월일이면 ('', 'INDIVIDUAL')."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    if re.match(r"^(19|20)\d{2}-\d{2}-\d{2}", s) or re.match(r"^\d{6}-?[1-4*]?\**$", s):
        return None, "INDIVIDUAL"
    m = BIZNO_RE.match(s.replace(" ", ""))
    if not m:
        return None, None
    digits = "".join(m.groups())
    if digits in PLACEHOLDER_BIZNO:
        return None, None
    code = int(m.group(2))
    if 81 <= code <= 88:
        kind = "CORPORATION"
    elif 89 <= code <= 99 or code == 80:
        kind = "NONPROFIT_OR_OTHER"
    else:
        kind = "SOLE_PROPRIETOR"
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", kind


def display_bizno(bizno, kind):
    """법인·비영리 번호만 전체 공개, 개인사업자 번호는 뒷자리 가림."""
    if not bizno:
        return None
    if kind in ("CORPORATION", "NONPROFIT_OR_OTHER"):
        return bizno
    return bizno[:7] + "*****"


SIDO = {
    "서울": "서울", "서울특별시": "서울", "서울시": "서울", "부산": "부산", "부산광역시": "부산", "대구": "대구",
    "대구광역시": "대구", "인천": "인천", "인천광역시": "인천", "광주": "광주", "광주광역시": "광주", "대전": "대전",
    "대전광역시": "대전", "울산": "울산", "울산광역시": "울산", "세종": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원", "충북": "충북",
    "충청북도": "충북", "충남": "충남", "충청남도": "충남", "전북": "전북", "전라북도": "전북",
    "전북특별자치도": "전북", "전남": "전남", "전라남도": "전남", "경북": "경북", "경상북도": "경북", "경남": "경남",
    "경상남도": "경남", "제주": "제주", "제주도": "제주", "제주특별자치도": "제주",
}


def address_region(addr):
    """주소에서 '시도 시군구'까지만 추출 (상세주소는 공개하지 않음)."""
    s = clean_text(addr)
    if not s:
        return None
    s = re.sub(r"^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|경기도|강원특별자치도|강원도|충청북도|충청남도|전북특별자치도|전라북도|전라남도|경상북도|경상남도|제주특별자치도)",
               r"\1 ", s)
    toks = s.split()
    if not toks:
        return None
    sido = SIDO.get(toks[0])
    if not sido:
        m = re.match(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", toks[0])
        if not m:
            return None
        sido = m.group(1)
        rest = toks[0][len(m.group(0)):]
        toks = [toks[0], rest] + toks[1:] if rest else toks
    sgg = None
    for t in toks[1:3]:
        m = re.match(r"^([가-힣]+?(시|군|구))", t)
        if m:
            sgg = m.group(1)
            break
    return f"{sido} {sgg}" if sgg else sido


@lru_cache(maxsize=None)
def kr_holidays(year):
    # 관공서의 공휴일에 관한 규정 기준 (python-holidays 패키지, 선거일·임시공휴일·대체공휴일 포함)
    return holidays.KR(years=[year])


def day_info(d: date):
    hol = kr_holidays(d.year).get(d)
    return {
        "weekday": WEEKDAYS_KO[d.weekday()],
        "is_weekend": d.weekday() >= 5,
        "holiday": hol,
    }


MEAL_KEYWORDS = re.compile(
    r"식당|음식|한식|일식|중식|양식|분식|고기|갈비|삼겹|정육|숯불|횟집|수산|초밥|스시|참치|국밥|해장|(?<!목욕)탕|찜|면옥|냉면|칼국수|"
    r"치킨|족발|보쌈|곱창|막창|순대|만두|김밥|도시락|뷔페|쌈밥|백반|밥|반찬|정식|피자|버거|파스타|비스트로|레스토랑|"
    r"키친|주방|집$|가든|식육|오리|닭|돈까스|우동|라멘|쌀국수|마라|훠궈|딤섬|반점|포차|주점|호프|이자카야|와인|"
    r"bbq|grill|kitchen|food|f&b|에프앤비|푸드"
)
CAFE_KEYWORDS = re.compile(
    r"카페|커피|cafe|coffee|스타벅스|투썸|이디야|빽다방|메가|컴포즈|할리스|폴바셋|파스쿠찌|엔제리너스|탐앤탐스|커피빈|"
    r"베이커리|제과|빵|파리바게|뚜레쥬르|디저트|케이크|설빙|아이스크림|베스킨|배스킨|요거|티하우스|다방|찻집|떡집"
)


def merchant_kind(name):
    """상호명 기반 업종 추정 (확정이 아니라 추정값)."""
    k = (clean_text(name) or "").lower()
    if not k:
        return None
    compact = k.replace(" ", "")
    if CAFE_KEYWORDS.search(k) or CAFE_KEYWORDS.search(compact):
        return "CAFE"
    if MEAL_KEYWORDS.search(k) or MEAL_KEYWORDS.search(compact):
        return "MEAL"
    return None


RETAIL_KEYWORDS = re.compile(
    r"마트|다이소|쿠팡|11번가|지마켓|g마켓|gmarket|ssg|옥션|위메프|티몬|네이버|문고|서점|오피스|아울렛|백화점|홈플러스|"
    r"코스트코|빅마켓|우체국|플라워|꽃|화원|인쇄|광고|기획|문구|전자|하이마트|약국|철물|가구|인테리어|스토어|몰$|상사|유통|"
    r"청과|과일|농산물|농협|하나로|홍삼|인삼|떡집|방앗간"
)
# 결제대행(PG)·VAN·배달앱·오픈마켓: 실제 가맹점이 아니므로 업소 반복·분할·지역 판단에서 뺀다
PLATFORM = re.compile(
    r"우아한형제들|배달의민족|배민|요기요|위대한상상|쿠팡|네이버파이낸셜|네이버페이|카카오페이|토스페이|이니시스|kcp|ksnet|"
    r"kis정보통신|나이스정보통신|나이스페이|kiosk_|키오스크|스마트로|kicc|한국정보통신|다날|페이먼츠|11번가|지마켓|g마켓|옥션|ssg|위메프|티몬|웰컴페이"
)


def is_platform(name):
    return bool(PLATFORM.search((clean_text(name) or "").lower()))
HOSPITALITY_PURPOSE = re.compile(r"간담|차담|오찬|만찬|중식|석식|조식|식사|유대|격려(?!금)|협의|논의|회의|다과|위로(?!금)|의견수렴|소통")
DONATION_PURPOSE = re.compile(r"위문금|위로금|성금|기부|후원금|(?<!담)회비|격려금|지원금|의연금|납부")  # '간담회비'·'차담회비'는 식비
GOODS_PURPOSE = re.compile(r"물품|구입|구매|제작|인쇄|소모품|비품")
CONDOLENCE_PURPOSE = re.compile(r"경조|조화|화환|부의|축의|근조|조의|축하화분|축화")


ADDRESS_IN_NAME = re.compile(r"(서울특별시|서울시|경기도|인천광역시|서울)\s?[가-힣]+(구|시|군)\s")


def split_name_address(name):
    """PDF 추출 중 상호명 뒤에 주소가 붙은 경우 분리: '브이아이피참치서울특별시 중구 세종대로' → ('브이아이피참치', '서울특별시 중구 세종대로')."""
    s = clean_text(name)
    if not s:
        return s, None
    m = ADDRESS_IN_NAME.search(s + " ")
    if m and m.start() >= 2:
        return s[:m.start()].strip(), s[m.start():].strip()
    return s, None


def council_category(merchant, purpose):
    """지방의회 지출의 성격 추정: 상호명과 집행목적 문구를 함께 본다 (확정 업종 아님)."""
    m, p = (clean_text(merchant) or "").lower(), clean_text(purpose) or ""
    if CONDOLENCE_PURPOSE.search(p):
        return "경조사"
    if DONATION_PURPOSE.search(p):
        return "성금·회비·격려금"
    if m and RETAIL_KEYWORDS.search(m) and not MEAL_KEYWORDS.search(m):
        return "물품·구매"
    kind = merchant_kind(m)
    if kind == "MEAL":
        return "식사"
    if kind == "CAFE":
        return "카페·다과"
    if GOODS_PURPOSE.search(p):
        return "물품·구매"
    if HOSPITALITY_PURPOSE.search(p):
        return "간담회(업종 미확인)"
    return "기타"


# 전국 체인: 카드 가맹점 주소가 본사로 찍히고 지점이 여러 곳이라 한 '장소'로 보지 않는다
CHAIN_STORE = re.compile(
    r"스타벅스|투썸|이디야|파리바게|뚜레쥬르|맥도날드|버거킹|롯데리아|도미노|피자헛|배스킨|베스킨|던킨|공차|메가|컴포즈|빽다방|할리스|"
    r"폴바셋|커피빈|엔제리너스|파스쿠찌|탐앤탐스|서브웨이|써브웨이|bhc|bbq|교촌|코페이|택시|모빌리티|코레일|철도|고속|항공|휴게소|편의점|cu|gs25|세븐일레븐|이마트24|"
    r"야쿠르트|투다리|본죽|김밥천국|에스씨케이컴퍼니|보나비|아티제"
)
# 식대로 분류됐지만 상호로 보아 식당이 아닌 곳 (광고·기획사, 여행사, 컨설팅 등). 순위판의 '식당' 집계에서만 뺀다
NOT_FOOD_PLACE = re.compile(r"광고|기획|여행|투어|컨설팅|전략|연구소|연구원|인테리어|쿠팡|상사|마트|우체국(?!식당)|렌터|주유|통신|인쇄|협회|재단|학회|문고|서점|전자|철물|가구|약국")


def is_chain(name):
    return bool(CHAIN_STORE.search((clean_text(name) or "").lower()))


def is_food_place(name):
    return not NOT_FOOD_PLACE.search(clean_text(name) or "")


KA_HOSPITALITY = ("간담회_식대", "간담회_다과", "언론_기자식대등", "사무실_식대비")
COUNCIL_HOSPITALITY = ("식사", "카페·다과", "간담회(업종 미확인)")


def is_hospitality(e):
    return e["category"] in (KA_HOSPITALITY if e["source_id"] == "ka-money" else COUNCIL_HOSPITALITY)
