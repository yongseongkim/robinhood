# robinhood-server

나랏일보고서의 FastAPI 읽기 API와 수집 작업입니다. 운영 데이터는 기존 메인 PostgreSQL의 전용 `robinhood` 스키마에 저장합니다. `DATABASE_URL`이 없을 때만 로컬 SQLite를 사용하는 개발 모드입니다. PostgreSQL을 설정한 상태에서 연결이 실패하면 SQLite로 전환하지 않습니다.

## 설정과 실행

의존성 설치·환경변수·최초 수집·로컬 실행은 [공통 설치 안내](../docs/INSTALL.md)를 따릅니다. 이 문서는 서버의 저장 구조, 수집 정책과 API 동작을 설명합니다.

`DATABASE_URL`은 기존 메인 DB를 가리킵니다. DB 이름을 바꾸거나 새 DB를 만들 필요가 없습니다. 기본 `ROBINHOOD_DATABASE_SCHEMA=robinhood`만 별도로 사용하며 `public` 등 시스템/공용 스키마는 허용하지 않습니다. 운영 API와 수집 역할을 나누려면 API 조회용 URL을 `DATABASE_URL`, 적재·마이그레이션·수집 잠금용 URL을 `ROBINHOOD_JOB_DATABASE_URL`에 설정합니다. 두 URL은 같은 DB·스키마를 가리켜야 합니다. URL에는 비밀번호가 포함될 수 있으므로 저장소에 커밋하지 않습니다.

API는 `/api/docs`에 명세를 제공하고, 웹 빌드가 있으면 같은 서버가 `robinhood-web/dist`도 제공합니다. 설정 파일은 uv의 `--env-file` 옵션으로 읽으며 운영에서는 환경변수를 직접 주입할 수 있습니다.

`migrate`는 스키마 준비, `collect`는 수집부터 DB 발행까지, `index`는 이미 정규화된 자료의 재적재 명령입니다. 최초 배포에서는 PostgreSQL 마이그레이션 후 `collect`를 실행합니다. OCR 플랫폼 지원 범위는 [OCR 실행 환경](../docs/INSTALL.md#ocr-실행-환경)을 확인합니다.

## 저장 구조와 발행

- `subjects`, `merchants`, `documents`, `transactions`, `findings`: 실제 수집본의 주체·거래처·출처·거래·추가 확인 근거.
- `extras`, `metadata`: 신고재산, 의정활동, 재정통계, 지도, 분류·출처·검토 이력을 JSONB로 저장.
- `job_runs`, `job_schedule`: 실행 이력과 상태, 시도 횟수, 다음 실행 시각.
- `schema_migrations`: 스키마 변경 이력.

`index`는 현재 정규화 자료를 검증한 임시 인덱스로 만든 다음 PostgreSQL COPY로 적재합니다. 이 과정의 SQLite 파일은 일시적인 로컬 작업 파일이며 완료 후 삭제됩니다. API는 PostgreSQL을 직접 읽습니다. 원본 PDF/XLSX와 OCR 캐시는 `data/` 또는 추후 객체 저장소에 보관하고 DB에는 정규화된 데이터·원문 URL·해시·수집 시각을 저장합니다.

발행은 하나의 PostgreSQL 트랜잭션에서 처리합니다. 기존 데이터 삭제와 새 적재 중 하나라도 실패하면 모두 롤백합니다. 읽기 API는 요청마다 `REPEATABLE READ READ ONLY` 트랜잭션을 사용하므로 한 응답에서 이전 자료와 새 자료가 섞이지 않습니다. 이 동작을 위해 TRUNCATE 대신 DELETE를 사용합니다. 운영 DB의 autovacuum을 유지하세요. 모든 변경은 전용 서비스 스키마 안에서 이뤄집니다.

세션 advisory lock으로 여러 호스트의 수집·인덱싱 중복을 막습니다. 발행은 잠금을 소유한 동일 연결에서 수행합니다. 이 연결이 끊어지면 새 연결로 발행을 강행하지 않고 실패합니다. 수집 URL에는 직접 연결 또는 세션 풀을 사용해야 합니다. 트랜잭션 풀 방식 PgBouncer를 API에 쓰는 경우 `ROBINHOOD_JOB_DATABASE_URL`을 직접 연결로 분리하세요.

## 주기 실행

프로세스 실행 명령은 [주기 수집 안내](../docs/INSTALL.md#주기-수집)에 있습니다. `serve`와 `worker`는 별도 프로세스이며, worker가 기존 수집 파이프라인을 실행합니다. 아래는 일정·재시도·장애 처리 정책입니다.

worker는 저장된 다음 실행 시각을 30초마다 확인합니다. 처음에는 즉시 수집하고, 성공하면 완료 시점으로부터 24시간 뒤에 실행합니다. 재시작해도 DB의 다음 실행 시각을 존중합니다. 실패하면 1분·5분·15분 간격으로 최대 세 번 재시도하고, 모두 실패하면 다음 정규 주기로 넘깁니다. 재시도에서는 수집 파이프라인 전체를 다시 실행하며 기존 원본·첨부 캐시는 재사용합니다.

외부 CronJob/스케줄러에서는 `robinhood run-due`를 1분마다 실행할 수 있습니다. DB에서 실행 시각을 확인하고 다른 수집자가 있으면 건너뛰므로 worker와 같은 중복 방지 규칙을 따릅니다. `collect`는 시각과 관계없이 한 번 실행하는 운영 명령입니다.

SIGTERM/SIGINT는 진행 중 작업을 마친 후 종료합니다. 작업이 2시간을 넘기면 수집 프로세스 그룹을 종료하고 실패로 기록합니다. 이전 작업이 중단된 상태로 남았다면 다음 잠금 소유자가 이를 기록하고 재실행합니다. 로그는 `var/logs/`에 권한 0600으로 저장합니다. API는 로그 본문이나 작업 시작 기능을 제공하지 않습니다.

Linux 상시 실행 설정과 DB 역할 권한은 [배포 안내](../deploy/README.md)에 있습니다. 서비스 파일을 추가하는 것만으로 실제 운영 서버나 예약 작업이 활성화되지는 않습니다.

## 실제 자동 갱신 범위

| 자료 | 주기 실행 때의 동작 | 범위·조건 |
|---|---|---|
| KA-money | 저장소 목록과 blob SHA 변경 재검사 | 현재 정규화·화면 지원 보고분은 2023/2024 제21·22대. 새 연도 서식은 별도 확장이 필요 |
| 서울시의회·25개 구의회 | 게시판 새 게시물·첨부 수집 및 재파싱 | 이미 받은 동일 첨부는 재사용하므로 수정본 전체 재검사는 아님. 강북구는 Chrome 필요 |
| 직책 보유자 | 공식 의회 홈페이지 기록 재수집 | 확인되는 직책·기간만 연결 |
| 법안·표결 | 최신 의원·법안과 새로 처리된 의안 갱신 | 열린국회정보 인증키 필요; 새 표결 중심의 증분 수집 |
| 국가재정 | 최신 API 수치 재조회·정규화 | 열린재정 인증키 필요; 오래된 연도 캐시 재사용 |
| 신고재산 | 최신 정기재산공개 공보 확인·파싱 | 원문 공개 이후 갱신 |
| 지도 | 없는 원본·출처 문서를 내려받고 경계 생성 | 정해진 경계 버전의 원본을 재사용. `--no-fetch`에서는 다운로드 생략 |
| OCR | 신규 스캔본 처리 | macOS Vision 전용. 다른 OS에서는 기존 OCR 결과 유지 |

작업의 `succeeded`는 설정된 파이프라인과 DB 발행 성공을 뜻합니다. 인증키가 없는 기관이 이전 수집본을 유지하거나 위 표의 지원 범위 밖 자료가 새로 나오는 경우까지 모든 출처가 최신이라는 뜻은 아닙니다. 화면의 원자료 수집 시각·대상 기간을 함께 확인합니다.

## OCR 표 텍스트 정정

서버 수집 job에 `OCR 파싱 → Codex 텍스트 정정 → 정규화 → DB 발행` 단계를 연결했습니다. Codex에는 추출된 표의 텍스트만 전달합니다. PDF·이미지·파일 경로·원문 URL·상세 주소는 입력에서 제외하고 읽기 전용 임시 작업 공간에서 실행합니다. 원본 PDF/XLSX/API 자료와 `data/staging/*_ocr.jsonl`은 이 단계에서 덮어쓰지 않습니다.

```bash
# robinhood-server/에서
uv sync --extra ocr-correction
# 모델 호출·DB 저장 없이 대상과 입력 크기만 확인
uv run --env-file .env robinhood ocr-correct --plan
# 설정을 활성화한 후, 기존 수집 job에서 자동 호출
uv run --env-file .env robinhood worker --interval-hours 24
```

`ROBINHOOD_OCR_CORRECTION_ENABLED=true`로 활성화합니다. Codex Python SDK를 사용하며 ChatGPT 로그인 상태를 확인합니다. API 키 인증으로 전환하지 않습니다. 전용 `ROBINHOOD_OCR_CODEX_HOME`에 정상 로그인된 실행 환경을 준비하세요. 사용량은 해당 계정의 한도에 따릅니다. 모델을 지정하지 않으면 계정의 기본 설정을 사용하며, 재현 가능한 운영 설정에는 `ROBINHOOD_OCR_MODEL`을 고정하는 편이 좋습니다.

기본 한 번에 5묶음, 묶음당 최대 40행·20,000자, 호출당 120초로 제한합니다. 원본 내용·추출 결과·프롬프트·모델 설정이 같은 완료 기록은 다시 호출하지 않습니다. 초기 자료가 많으면 여러 번에 나눠 처리하며 한도를 넘는 자료는 정정 전 OCR 값으로 남습니다. 수동 `ocr-correct`는 정정본만 준비하고, 다음 `collect --no-fetch`/수집 작업의 정규화에서 반영합니다.

자동 반영 범위는 기존 행의 거래처 표기·집행목적·결제수단에 대한 문구·띄어쓰기·텍스트 열 배치 정정입니다. 거래처 이름은 같은 표에 있는 근거나 공백·문장부호 정리로만 바꿉니다. 금액·날짜·시간·인원·재원·직책·주소, 행 추가/삭제·거래 병합은 자동 반영하지 않습니다. 텍스트 안의 숫자도 보존합니다. 그 범위의 변경 제안과 근거 불충분 항목은 검토 대기로 기록합니다. 모델 판단만으로 OCR 신뢰도를 올리지 않습니다.

PostgreSQL `ocr_corrections`에 원본 해시, 추출 행 사본, 프롬프트·모델 설정, 수정 전후, 사유·인용 근거, 검증 결과를 별도로 저장합니다. 로컬 모드에서는 `var/ocr-corrections.sqlite3`를 사용합니다. 검증된 정정본은 `var/ocr-corrections.json`으로 내보내 정규화가 읽도록 하며, 추출 행의 해시가 달라지면 이전 정정본을 적용하지 않습니다. 수치와 행 수를 보존하고 기존 중복 판단도 원래 추출 문구를 기준으로 유지합니다. 정정 이력 테이블은 조회 데이터 재발행 때 삭제하지 않습니다.

이 단계는 현재 로컬 OCR 파서가 만든 지방의회 표를 대상으로 합니다. KA-money의 2차 OCR XLSX와 파서가 행을 만들지 못한 표는 아직 대상에 포함되지 않습니다. 초기 점검 당시 117개 문서·5,614행·203묶음이었으며, 묶음당 최대 입력은 8,587자였고 모든 원본 파일 해시가 확인됐습니다. 이 수치는 초기 입력 조사 기록이며 실제 모델 정정 품질 평가와는 구분합니다. 정정 기능을 꺼도 같은 설정으로 저장된 검증 완료 정정본은 재사용합니다.

정정된 거래는 상세 화면에서 원문 보존과 텍스트 정정 여부를 표시합니다. 중간 파일 정리는 추출·정정·적재 검증 이후의 별도 정책이며 이번 단계에서 원본이나 OCR 캐시를 자동 삭제하지 않습니다.

## API와 상태 확인

| `/api/v1` 기준 경로 | 내용 |
|---|---|
| `/meta`, `/geo`, `/overview` | 데이터 범위·지도·지역 요약 |
| `/members`, `/subjects/{id}` | 의원 목록·지출·수입·재산·법안·표결 |
| `/councils`, `/councils/{id}` | 의회·직책·반기별 경비 |
| `/rankings`, `/places`, `/places/{id}` | Top 10·분포·자주 결제한 장소 |
| `/transactions`, `/transactions/{id}`, `/documents/{id}` | 거래·원문 근거 |
| `/fiscal`, `/sources`, `/findings` | 재정통계·출처·규칙·확인 표시 |

`/fiscal`은 `basis=actual|budget|proposal`, 선택적인 `year`를 받습니다. 연도가 없으면 수집된 최신 연도(결산은 우선 12월 누계 완료 연도)를 선택합니다. 응답의 `availableYears`는 기준별 선택 가능 연도이고 `trends.series`는 총규모·분야·부처별 시계열과 전년 대비 금액·증감률·비중 변화를 담습니다. 결산의 연간 비교에는 12월 누계만 포함하며, 정부안은 전년도 확정 예산과 비교하고 두 점의 기준을 각각 표시합니다. 누락 항목이나 분모가 0인 증감률은 null입니다.
| `/jobs/status`, `/jobs/history?limit=20` | 최근 실행 상태·다음 실행·실행 이력 |

금액 단위는 원입니다. 응답의 `scope`에 날짜·집계 종류·재원·보고서 ID가 포함됩니다. 재원을 합산하지 않고, 재수록 중복·문서 기간 밖 날짜는 합계에서 제외합니다. 빠진 달의 금액은 null입니다. 이름은 기본 가명이고 `ROBINHOOD_PSEUDONYMS=false`일 때 공개 자료의 원래 이름을 사용합니다. 가명은 표시 선택이며 익명화 보장이 아닙니다. 사업자번호 마스킹은 유지합니다.

운영 모니터링에서는 `/api/health`와 `/api/v1/jobs/status`의 `state`, `stage`, `attempt`, `nextRunAt`, 원자료 시각을 확인하세요. 별도의 알림 발송 연동은 설치하지 않았습니다.

## 검증

```bash
uv run pytest -q
# 별도 테스트 DB가 있을 때: 테스트마다 임의 스키마를 만들고 해당 스키마만 정리
TEST_POSTGRES_URL='postgresql://...' uv run pytest -q tests/test_postgres.py
```

`deploy/postgres-test.compose.yaml`은 로컬 일회성 테스트 DB를 위한 선택 구성입니다. PostgreSQL 미연결 환경에서는 실서버 통합 테스트 세 개가 건너뛰어집니다. SQL·JSONB·외래키·롤백과 API 집계 계약은 PostgreSQL 17.5 PGlite 엔진으로도 검증할 수 있습니다. 이는 psycopg 연결/COPY 전송의 실서버 검증과는 별개입니다.

```bash
# 저장소 루트에서, 선택 사항
npm install --prefix .artifacts/pg-test --no-save @electric-sql/pglite@0.3.15
PGLITE_MODULE="$PWD/.artifacts/pg-test/node_modules/@electric-sql/pglite/dist/index.js" \
  robinhood-server/.venv/bin/python robinhood-server/tests/pg_engine_smoke.py
```
