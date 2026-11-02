# robinhood-web

나랏일보고서의 React·TypeScript·Vite 웹입니다. Pencil의 P01–P10을 페이지·탭·필터로 구현하고 모바일 장소 탐색을 같은 경로에 반응형으로 제공합니다.

```bash
cd robinhood-web
npm ci
npm run dev
```

Node.js 22.12+가 필요합니다. `http://localhost:5173`에서 열며 `/api`는 기본 `http://127.0.0.1:8000`으로 프록시합니다. 다른 API 주소는 `ROBINHOOD_API_URL` 환경변수로 Vite에 전달합니다. 서버 API를 먼저 실행하세요.

```bash
npm run build
npm run format:check
```

빌드 후 `robinhood-server`를 실행하면 `dist/`와 API를 같은 출처에서 제공합니다. 운영에서는 HTTPS 역방향 프록시를 앞에 둘 수 있습니다. 외부 호스팅에서 웹만 따로 배포하려면 `/api` 프록시와 SPA 경로의 `index.html` fallback을 함께 설정해야 합니다.

주요 경로는 `/`, `/members`, `/members/{id}`, `/councils`, `/rankings`, `/places`, `/places/{id}`, `/fiscal`, `/transactions/{id}`, `/sources`입니다. 선택값은 URL에 남아 새로고침과 공유에 유지됩니다. 페이지가 로딩·오류·결측·빈 결과를 각각 표시하며 샘플 금액으로 대체하지 않습니다.

## 네이버 지도

서버의 `NAVER_MAPS_CLIENT_ID`에 현재 Maps 애플리케이션의 공개 키 ID를 설정하고 실제 웹 서비스 URL을 등록합니다. 서버가 이 값을 `/meta`로 전달하고 웹은 `ncpKeyId` 방식으로 SDK를 불러옵니다. 클라이언트 시크릿과 Geocoding 키는 웹에 넣지 않습니다. SDK 인증·로딩이 실패하거나 키가 없으면 실제 행정구역 경계 지도로 전환합니다.

현재 수집본에 정확한 가게 좌표는 없습니다. 구의 대표 좌표에 구별 거래처 수를 표시하고 지도·지역 선택·목록을 연결합니다. 대표 좌표는 가게 위치가 아닙니다. 가명 상호로 실제 네이버 장소를 검색하지 않습니다. SDK 로고·저작권 표시는 유지합니다. 지도 경계 출처는 화면과 `/sources`에서 확인할 수 있습니다.

## 브라우저 검사

```bash
# 저장소 루트에서 (최초 한 번)
uv run --project robinhood-server --with playwright python -m playwright install chromium
# 웹 디렉터리에서
npm run test:e2e
```

기본 E2E는 TCP 서버 없이 실제 FastAPI TestClient와 빌드된 웹을 Playwright 요청 라우팅으로 연결합니다. 먼저 웹 빌드와 `robinhood index`가 필요합니다. 실행 중인 웹을 검사하려면 `npm run test:e2e -- --url http://localhost:8000`을 사용합니다. `--channel chrome`으로 설치된 Chrome을 쓸 수 있습니다. 캡처는 루트 `.artifacts/implementation/screenshots/`에 저장됩니다.
