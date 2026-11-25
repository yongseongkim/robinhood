# robinhood-web

의원·정당은 목적별 다섯 탭으로 탐색하며 기본 화면은 `재산 순위`입니다. 탭·필터·기준일은 스크롤 중에도 상단에 표시합니다.

| 탭 | URL의 `view` | 표시 내용 |
| --- | --- | --- |
| 재산 순위 | `assets` | 선택한 지표의 Top 10 한 개. 순재산, 부동산·토지·건물·증권·예금·현금·가상자산·채무와 부동산·증권 비중을 선택 |
| 연간 증감 | `changes` | 최신 수집 연도의 재산 증가·감소 Top 10 |
| 정치자금 | `funds` | 회계보고분을 선택해 지출·정치자금 수입 Top 10 비교 |
| 정당 비교 | `parties` | 전체 정당의 순재산 중앙값·수록 인원과 선택 정당의 재산 Top 10 |
| 의원 목록 | `list` | 이름·지역 검색, 지출 정렬, 월·보고분 필터와 페이지 이동 |

`asset`에는 `net`, `realestate`, `land`, `buildings`, `securities`, `deposits`, `cash`, `crypto`, `debt`, `share-realestate`, `share-securities`를 사용합니다. 선택값은 URL에 남아 새로고침·뒤로 가기·공유에 유지됩니다. 검색어·지역·정렬·페이지·월이 있는 기존 링크는 목록을 열고, 이전 `view=rankings` 링크는 재산 순위로 연결합니다. 재산 순위의 정당 선택은 선택한 개인 순위를 좁힙니다. 정당 비교에서는 중앙값 표가 전체 정당을 유지하고 표·드롭다운의 선택이 정당 Top 10만 바꿉니다.

연간 증감은 현재 2025년 말 공보의 2024년 말 대비 값만 있으며 회계보고분 선택은 정치자금 탭에 표시합니다. 부동산은 전세·임차권을 제외하고 증권에는 주식 외 증권도 포함합니다. 자산은 채무 차감 전 신고액이고 비중은 총자산(순재산 + 채무) 기준으로 분자·분모 금액을 함께 표시합니다. 기준일·금액이 불명확한 기록과 비중의 0원 이하 분모는 비교에서 제외합니다. 순위 행 전체에서 프로필로 이동하며 미연결 기록은 공보 원문으로 연결합니다.

나랏일보고서의 웹 대시보드는 React·TypeScript·Vite로 구성합니다.
데스크톱과 모바일에서 같은 URL로 페이지를 열고 탭·필터를 선택하거나 장소를 탐색할 수 있습니다.

로컬 개발 예시에서 웹은 5173번, API는 8010번 포트를 사용합니다.
Vite가 `/api` 요청을 보낼 주소는 `ROBINHOOD_API_URL`에 지정합니다.
의존성 설치와 개발 서버 실행·빌드 명령은 [공통 설치 안내](../docs/INSTALL.md#로컬-웹과-api)를 따릅니다.

웹을 빌드한 뒤 `robinhood-server`를 실행하면 FastAPI가 `dist/`와 API를 같은 출처에서 제공합니다.
운영 환경에서는 앞단에 HTTPS 역방향 프록시를 둘 수 있습니다.
웹만 따로 호스팅할 때는 `/api` 요청을 API 서버로 전달하고, `/members/{id}` 같은 화면 경로를 직접 열어도 `index.html`을 반환하도록 설정합니다.

주요 경로는 `/`, `/members`, `/members/{id}`, `/councils`, `/rankings`, `/places`, `/places/{id}`, `/fiscal`, `/transactions/{id}`, `/sources`입니다.
URL에 기록된 선택값은 새로고침하거나 링크를 공유해도 유지됩니다.
화면에서는 로딩 중, 조회 오류, 누락된 값, 검색 결과 없음 상태를 구분하며 실제 자료에 있는 금액만 표시합니다.

`/fiscal`의 ‘얼마나 달라졌나’는 총지출 또는 수집 부처 예산 합계, 분야·부처별 금액의 연도별 추세와 전년 대비 증감액·증감률·비중 변화를 보여줍니다. 연도와 항목 선택은 URL에 남고, 차트의 원 단위 금액을 표로 펼칠 수 있습니다. 연도 선택지는 API에 실제로 수집된 자료를 따릅니다. 결산은 연간 자료가 완성된 최신 연도를 기본으로 보여주며, 정부안은 전년도 확정 예산과 편성 규모를 비교한다고 표시합니다. 전년 자료 누락·부처명 변경·0원 기준액에서는 계산할 수 없는 증감률을 채우지 않습니다.

## 방문 통계

`index.html`에서 운영 hostname `robinhood.yongseongkimm.com`에만 Google Analytics 4(`G-C7KL1XNX65`)를 비동기로 로드합니다. 로컬·다른 미리보기 hostname은 수집하지 않습니다. 측정 ID는 공개 식별자이며 로그인 정보나 API secret은 쓰지 않습니다.

페이지 조회는 Google 태그와 [브라우저 이력 기반 향상된 측정](https://developers.google.com/analytics/devguides/collection/ga4/single-page-applications)이 처리합니다. 데이터 스트림의 향상된 측정에서 `Page views → Page changes based on browser history events`를 켭니다. 라우터에 별도 `page_view` 전송을 추가하지 않으므로 초기 진입과 화면 전환이 중복 집계되지 않습니다. 태그 로딩이 막혀도 웹·API 조회는 계속 동작합니다.

## 네이버 지도

네이버 Maps 애플리케이션에 웹 서비스 URL을 등록하고, 서버의 `NAVER_MAPS_CLIENT_ID`에 공개 키 ID를 설정합니다.
웹은 `/api/v1/meta`에서 받은 ID를 `ncpKeyId`로 전달해 SDK를 불러옵니다.
클라이언트 시크릿과 Geocoding 키는 웹에 넣지 않습니다.
공개 키가 없거나 SDK 로딩·인증에 실패하면 행정구역 경계 지도를 표시합니다.

현재 수집본에는 가게의 정확한 좌표가 없어 각 구의 대표 좌표에 그 구의 거래처 수를 표시합니다.
구를 선택하면 지도와 거래처 목록에 같은 지역이 표시됩니다.
상호는 공개자료의 표기를 사용합니다.
상호만으로 지도에 개별 가게를 연결하지 않습니다.
지도에는 SDK 로고와 저작권 표시를 유지하며, 경계 자료의 출처는 화면과 `/sources`에서 확인할 수 있습니다.

## 브라우저 검사

```bash
# 저장소 루트에서 (최초 한 번)
uv run --project robinhood-server --with playwright python -m playwright install chromium
# 웹 디렉터리에서
npm run test:e2e
```

기본 E2E 검사를 실행하기 전에 웹을 빌드하고 조회 DB에 데이터를 적재합니다.
처음 수집할 때는 `collect`, 정규화한 자료를 다시 적재할 때는 `index`를 사용합니다.
검사는 별도의 TCP 서버를 띄우지 않고 Playwright의 브라우저 요청을 FastAPI `TestClient`로 전달합니다.
실행 중인 웹을 검사하려면 `npm run test:e2e -- --url http://127.0.0.1:8010`을 사용합니다.
`--channel chrome`을 지정하면 설치된 Chrome으로 검사합니다.
화면 캡처는 저장소 루트의 `.artifacts/implementation/screenshots/`에 저장됩니다.
