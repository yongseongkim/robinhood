# robinhood-web

나랏일보고서의 React·TypeScript·Vite 웹입니다. 페이지·탭·필터와 모바일 장소 탐색을 같은 경로에 반응형으로 제공합니다.

설치·개발 서버·빌드 명령은 [공통 설치 안내](../docs/INSTALL.md#로컬-웹과-api)를 따릅니다. 공통 예시는 웹 5173과 API 8010 포트를 사용하고 `ROBINHOOD_API_URL`로 프록시 대상을 지정합니다. 이 문서는 웹의 경로, 지도와 브라우저 검사를 설명합니다.

빌드 후 `robinhood-server`를 실행하면 `dist/`와 API를 같은 출처에서 제공합니다. 운영에서는 HTTPS 역방향 프록시를 앞에 둘 수 있습니다. 외부 호스팅에서 웹만 따로 배포하려면 `/api` 프록시와 SPA 경로의 `index.html` fallback을 함께 설정해야 합니다.

주요 경로는 `/`, `/members`, `/members/{id}`, `/councils`, `/rankings`, `/places`, `/places/{id}`, `/fiscal`, `/transactions/{id}`, `/sources`입니다. 선택값은 URL에 남아 새로고침과 공유에 유지됩니다. 페이지가 로딩·오류·결측·빈 결과를 각각 표시하며 샘플 금액으로 대체하지 않습니다.

`/fiscal`의 ‘얼마나 달라졌나’는 총지출 또는 수집 부처 예산 합계, 분야·부처별 금액의 연도별 추세와 전년 대비 증감액·증감률·비중 변화를 보여줍니다. 연도와 항목 선택은 URL에 남고, 차트의 원 단위 금액을 표로 펼칠 수 있습니다. 연도 선택지는 API에 실제로 수집된 자료를 따릅니다. 결산은 연간 자료가 완성된 최신 연도를 기본으로 보여주며, 정부안은 전년도 확정 예산과 편성 규모를 비교한다고 표시합니다. 전년 자료 누락·부처명 변경·0원 기준액에서는 계산할 수 없는 증감률을 채우지 않습니다.

## 네이버 지도

서버의 `NAVER_MAPS_CLIENT_ID`에 현재 Maps 애플리케이션의 공개 키 ID를 설정하고 실제 웹 서비스 URL을 등록합니다. 서버가 이 값을 `/meta`로 전달하고 웹은 `ncpKeyId` 방식으로 SDK를 불러옵니다. 클라이언트 시크릿과 Geocoding 키는 웹에 넣지 않습니다. SDK 인증·로딩이 실패하거나 키가 없으면 실제 행정구역 경계 지도로 전환합니다.

현재 수집본에 정확한 가게 좌표는 없습니다. 구의 대표 좌표에 구별 거래처 수를 표시하고 지도·지역 선택·목록을 연결합니다. 대표 좌표는 가게 위치가 아닙니다. 표시 이름은 공개자료의 원래 표기를 사용하며 상호만으로 실제 장소를 자동 연결하지 않습니다. SDK 로고·저작권 표시는 유지합니다. 지도 경계 출처는 화면과 `/sources`에서 확인할 수 있습니다.

## 브라우저 검사

```bash
# 저장소 루트에서 (최초 한 번)
uv run --project robinhood-server --with playwright python -m playwright install chromium
# 웹 디렉터리에서
npm run test:e2e
```

기본 E2E는 TCP 서버 없이 실제 FastAPI TestClient와 빌드된 웹을 Playwright 요청 라우팅으로 연결합니다. 먼저 웹 빌드와 실제 조회 데이터 적재가 필요합니다. 최초 적재는 `collect`, 기존 정규화 자료의 재적재는 `index`를 사용합니다. 실행 중인 웹을 검사하려면 `npm run test:e2e -- --url http://127.0.0.1:8010`을 사용합니다. `--channel chrome`으로 설치된 Chrome을 쓸 수 있습니다. 캡처는 루트 `.artifacts/implementation/screenshots/`에 저장됩니다.
