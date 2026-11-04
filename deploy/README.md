# PostgreSQL 운영과 주기 수집 배포

기존 메인 DB 안의 `robinhood` 전용 스키마를 사용합니다. 이 문서는 운영 계정·환경 파일·권한·서비스 활성화를 설명합니다. 공통 의존성과 로컬 실행은 [설치 안내](../docs/INSTALL.md)를 따릅니다. 저장소의 서비스 파일은 배포 템플릿이며 실제 활성화는 운영 환경에서 수행합니다.

현재 OCI/Linux에서 새 스캔 PDF를 OCR로 처리하는 어댑터는 미구현입니다. API와 일반 자료 수집을 배포하는 단계와 스캔 자료까지 포함한 전체 수집 준비를 구분합니다. 지원 상태는 [OCR 실행 환경](../docs/INSTALL.md#ocr-실행-환경)에 있습니다.

## 환경과 권한

API 환경 파일 `/etc/robinhood/api.env` 예시:

```dotenv
DATABASE_URL=postgresql://API_USER:ENCODED_PASSWORD@DB_HOST:5432/MAIN_DB?sslmode=require
ROBINHOOD_DATABASE_SCHEMA=robinhood
ROBINHOOD_VAR=/var/lib/robinhood
ROBINHOOD_PSEUDONYMS=true
NAVER_MAPS_CLIENT_ID=
```

worker 환경 파일 `/etc/robinhood/worker.env`에는 같은 DB의 적재 역할 연결을 설정합니다. 직접 연결 URL이 필요하면 `ROBINHOOD_JOB_DATABASE_URL`로 지정합니다. `ROBINHOOD_COLLECTOR_PYTHON=/srv/robinhood/.venv/bin/python`, `ROBINHOOD_VAR=/var/lib/robinhood`도 설정합니다. 실제 환경 파일은 서비스 계정만 읽도록 관리합니다.

저장소에는 SOPS 암호문 `credentials.yaml`과 KMS 설정 `.sops.yaml`을 함께 포함합니다. worker 실행 환경에 SOPS CLI와 해당 키의 `roles/cloudkms.cryptoKeyDecrypter` 권한을 가진 GCP 실행 주체를 준비합니다. 운영에서는 서비스 계정/Workload Identity의 ADC를 사용하며, 별도 ADC 파일이 필요하면 저장소 밖에서 주입합니다. systemd의 ProtectHome 설정을 고려해 서비스가 읽을 수 있는 경로를 사용합니다. 대체 API 키는 `ASSEMBLY_API_KEY`, `OPENFISCAL_API_KEY`로 주입할 수 있습니다.

마이그레이션 역할은 해당 스키마의 생성/DDL 권한이 필요합니다. API는 해당 스키마의 USAGE와 테이블 SELECT만 있으면 됩니다. 역할을 미리 생성한 DB 관리자가 부여할 권한의 예시는 다음과 같습니다. 실제 역할명으로 바꿔 적용하세요.

```sql
CREATE SCHEMA IF NOT EXISTS robinhood AUTHORIZATION robinhood_writer;
GRANT USAGE ON SCHEMA robinhood TO robinhood_api;
GRANT SELECT ON ALL TABLES IN SCHEMA robinhood TO robinhood_api;
ALTER DEFAULT PRIVILEGES FOR ROLE robinhood_writer IN SCHEMA robinhood
    GRANT SELECT ON TABLES TO robinhood_api;
```

worker 역할과 API 역할을 하나로 시작해도 API 자체의 읽기 트랜잭션은 유지됩니다. 운영 DB에 적용할 역할과 계정 생성은 기존 인프라 관리 방식에 맞춥니다.

## 준비와 최초 발행

프로젝트를 `/srv/robinhood`에 놓고 서비스 계정 `robinhood`가 `data/`, `site/data/`, `/var/lib/robinhood`를 읽고 쓸 수 있게 준비합니다. 최초 배포는 빈 데이터 볼륨과 DB에서 수집해 채웁니다. 다음 명령은 서비스 계정과 worker 환경변수가 설정된 셸에서 실행하며, SOPS CLI와 KMS 권한도 준비되어 있어야 합니다.

```bash
cd /srv/robinhood
uv sync --project robinhood-server
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pipeline/requirements.txt
npm ci --prefix robinhood-web
npm run build --prefix robinhood-web
uv run --project robinhood-server --env-file /etc/robinhood/worker.env python pipeline/credentials.py
uv run --project robinhood-server --env-file /etc/robinhood/worker.env python pipeline/credentials.py openfiscal_api_key
```

두 키 읽기 확인이 성공한 뒤 같은 worker 환경 파일로 최초 적재를 실행합니다.

```bash
uv run --project robinhood-server --env-file /etc/robinhood/worker.env robinhood migrate
uv run --project robinhood-server --env-file /etc/robinhood/worker.env robinhood collect
```

`collect`가 기관별 자료와 없는 지도 원본을 가져와 파싱·정규화·검증 후 DB에 반영합니다. 최초 발행 전까지 API 준비 상태는 503입니다. 이후 코드 재배포에서는 DB와 데이터 볼륨을 유지하며 worker가 주기 갱신합니다.

강북구 자료 수집에는 설치된 Chrome이 필요합니다. Linux에서는 macOS Vision OCR이 실행되지 않아 기존 OCR 결과가 있을 때만 유지할 수 있습니다. 새 스캔본까지 처음부터 처리하려면 macOS 수집 호스트를 사용하거나 별도 OCR 엔진을 추가해야 합니다.

OCI/Linux의 Tesseract 시스템 패키지·한국어/영어 언어 데이터 설치와 현재 어댑터 구현 상태는 [OCR 실행 환경](../docs/INSTALL.md#ocr-실행-환경)에 기록했습니다.

## Linux 상시 실행

`systemd/robinhood-api.service`, `systemd/robinhood-worker.service`는 검토 가능한 서비스 구성입니다. 파일의 경로·계정·환경 파일을 배포 위치에 맞춘 후 활성화합니다.

제공된 API unit의 포트는 8000입니다. 설치 안내의 8010 개발 예시나 운영 프록시에 맞추려면 unit의 `ExecStart`에서 `--port`를 조정합니다.

```bash
sudo cp deploy/systemd/robinhood-api.service deploy/systemd/robinhood-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now robinhood-api robinhood-worker
sudo systemctl status robinhood-worker
journalctl -u robinhood-worker -f
```

worker는 시작/재시작 후 PostgreSQL에 저장된 일정을 확인합니다. 새 상태라면 즉시 실행하고 이후 성공 완료에서 24시간 간격입니다. 실패 시 1·5·15분 재시도 후 다음 정규 주기로 넘어갑니다. 여러 호스트가 같은 설정으로 실행되어도 advisory lock과 DB의 다음 실행 시각으로 조정합니다. 장애로 잠금 연결이 끊어지면 해당 연결을 통한 발행도 실패합니다.

Kubernetes CronJob 등 기존 스케줄러를 쓴다면 worker 서비스 대신 `robinhood run-due`를 1분 간격으로 실행하면 됩니다. 환경변수와 원본 데이터 영구 볼륨은 동일하게 전달해야 합니다. 수집 과정은 기존 게시판/인증키/지원 연도 범위 안에서 동작합니다.

## 선택적 Codex OCR 문구 정정

서버 환경에서 `uv sync --project robinhood-server --extra ocr-correction`로 SDK를 설치하고 worker 환경에 `ROBINHOOD_OCR_CORRECTION_ENABLED=true`를 설정합니다. 서버 수집 job이 OCR 파싱과 정규화 사이에서 호출합니다. 별도 AI 스케줄러나 ChatGPT 브라우저 자동화는 사용하지 않습니다.

`ROBINHOOD_OCR_CODEX_HOME=/var/lib/robinhood/codex-home`처럼 서비스 계정이 읽고 쓸 수 있는 전용 실행 환경과 ChatGPT 로그인이 필요합니다. 제공된 systemd 서비스는 ProtectHome=true이므로 다른 사용자의 홈 디렉터리에 의존하지 않게 준비합니다. 기존 설정이나 인증 파일을 자동 복사·변경하지 않습니다. SDK는 ChatGPT 로그인 여부를 확인하고 API 키 인증이면 중단합니다. 계정 사용량 한도와 로그인 상태에 따라 실행이 실패할 수 있고, 기존 job의 재시도 정책을 따릅니다.

묶음 수·행 수·호출 제한시간은 서버 `.env.example`의 `ROBINHOOD_OCR_*` 설정으로 조정합니다. `ocr-correct --plan`은 모델을 호출하지 않습니다. PostgreSQL 마이그레이션 002가 정정 이력 테이블을 추가하며, 원본·OCR 추출본은 유지하고 별도 정정본만 다음 정규화에 적용합니다. 자세한 범위·검증 기준은 서버 README에 있습니다.

## 확인과 복구

- `/api/health`: 발행 데이터가 조회 가능한지 확인. 미적재·DB 장애는 503.
- `/api/v1/jobs/status`: 최근 상태, 단계, 시도 횟수, 발행 여부, 다음 실행 시각.
- `/api/v1/jobs/history?limit=20`: 여러 호스트에서 공유하는 실행 이력.
- `var/logs/`: 상세 수집 로그. 외부 API로 제공하지 않음.

실패한 적재는 PostgreSQL 트랜잭션을 롤백해 이전 조회 자료를 유지합니다. 원인을 고친 뒤 `collect`로 즉시 다시 실행하거나 worker의 재시도를 기다립니다. 미완료 작업 기록은 다음 잠금 소유자가 중단으로 기록합니다. 메인 PostgreSQL의 백업·autovacuum 정책을 그대로 적용하고, 원본 파일/OCR 캐시는 별도로 백업합니다.

구현에 사용한 동작 기준: [PostgreSQL 트랜잭션 격리](https://www.postgresql.org/docs/current/transaction-iso.html), [advisory lock](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS), [psycopg COPY와 롤백](https://www.psycopg.org/psycopg3/docs/basic/copy.html).
