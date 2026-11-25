# PostgreSQL 운영과 주기 수집 배포

운영에서는 기존 메인 PostgreSQL의 `robinhood` 전용 스키마를 사용합니다.
아래 절차에 따라 운영 계정에 권한을 부여하고 환경 파일을 준비한 뒤 API와 수집 worker를 활성화합니다.
공통 의존성과 로컬 실행 방법은 [설치 안내](../docs/INSTALL.md)에 있습니다.

Linux worker는 Tesseract로 스캔 PDF를 처리합니다. 설치·검증 기준은 [OCR 실행 환경](../docs/INSTALL.md#ocr-실행-환경)에 있습니다.

## Homelab k3s 배포

`Dockerfile`은 `api`, `worker` 두 target을 제공합니다. `api`가 React 빌드와 FastAPI를 8000 포트로 함께 제공하고, `worker`는 수집·발행을 실행합니다.
`helm/`은 웹과 API를 함께 제공하는 ClusterIP Service `robinhood:80`, API Deployment, 단일 worker Deployment, PreSync migration·PostSync 컬럼 정리 Job과 원본 저장 PVC를 만듭니다.
namespace·DB·role·Secret·Cloudflare 연결은 [homelab-infra 운영 문서](https://github.com/yongseongkim/homelab-infra/blob/main/k8s/robinhood/README.md)를 따릅니다.

```bash
docker build --platform linux/arm64 --target api -f deploy/Dockerfile -t robinhood-api:local .
docker build --platform linux/arm64 --target worker -f deploy/Dockerfile -t robinhood-worker:local .
helm lint deploy/helm
helm template robinhood deploy/helm --namespace robinhood
```

GitHub Actions `Release ARM64 images`는 PR에서 빌드를 검증하고 `vMAJOR.MINOR.PATCH` 태그 push 시 자동 배포합니다.
예를 들어 앱 저장소에서 다음과 같이 새 버전을 게시합니다. 이미 사용한 태그는 변경하지 않습니다.

```bash
git tag -a v0.3.0 -m 'Release v0.3.0'
git push origin v0.3.0
```

두 ARM64 이미지 `yny.ocir.io/axrudau2tcfl/robinhood-{api,worker}:0.3.0`이 모두 게시되어야 승격 job이 실행됩니다.
승격은 태그의 소스에 차트 `version`·`appVersion`과 `images.tag`를 맞춘 snapshot을 `deploy/production` 브랜치에 기록합니다.
`deploy/release.json`에는 릴리스 태그와 원본 commit이 남습니다. ArgoCD가 이 브랜치를 자동 동기화하며 인프라 values는 이미지 태그를 덮어쓰지 않습니다.
`main`의 변경은 다음 릴리스 태그를 게시할 때 반영됩니다. 승격은 직렬 실행되고 늦게 끝난 이전 버전은 건너뛰므로 운영 버전이 자동으로 내려가지 않습니다.
같은 태그의 재실행은 재승격하지 않으며, 다른 commit으로 옮긴 운영 태그는 거부합니다. prerelease·build suffix는 지원하지 않습니다.
되돌릴 때는 수정한 소스에 현재 운영보다 높은 새 버전 태그를 붙입니다.
수동 workflow 실행은 `sha-<short commit>` 이미지만 게시하고 운영 브랜치를 승격하지 않습니다.
CI에는 repository Secrets `OCI_REGISTRY_USERNAME`, `OCI_AUTH_TOKEN`을 설정하고, 클러스터에는 homelab-infra가 관리하는 `oci-registry-secret`을 준비합니다. 인증 원본은 homelab-infra의 SOPS 파일입니다.
승격 job만 기본 `GITHUB_TOKEN`에 `contents: write`를 부여하므로 인프라 저장소 쓰기 토큰은 필요하지 않습니다.

worker에는 `WORKER_DATABASE_URL`의 값을 `DATABASE_URL`로, API에는 조회 URL을 전달합니다.
출처 키는 `ASSEMBLY_API_KEY`, `OPENFISCAL_API_KEY`로 주입하므로 컨테이너에는 GCP 인증이나 SOPS가 필요하지 않습니다.
worker는 `/storage/data`, `/storage/site-data`, `/storage/var`를 영구 볼륨에 보존합니다.
기존 서버 경로 계산을 위해 이미지의 소스 구조와 `PYTHONPATH`를 유지합니다.

ARM64 worker는 시스템 Chromium을 사용합니다. 다른 환경도 `ROBINHOOD_BROWSER_EXECUTABLE`에 실행 파일 경로를 지정할 수 있고, 미지정 시 기존 Chrome channel을 사용합니다.
worker 이미지에 Tesseract와 한국어·영어 언어 데이터를 포함합니다.
AI OCR 정정은 Helm 배포에서 꺼져 있습니다.

API readiness는 `/api/health`를 사용해 최초 발행 전에는 실패합니다. startup·liveness는 DB와 무관한 `/api/openapi.json`을 사용합니다.
worker 교체는 Recreate이며 SIGTERM 뒤 진행 중인 수집이 끝날 때까지 최대 130분을 기다립니다.
기존 API가 사용하는 컬럼은 새 API·worker가 모두 Healthy가 된 뒤 PostSync의 `robinhood migrate --post-deploy`로 제거합니다.
서버 코드는 교체 전·후 스키마에서 모두 원래 이름을 조회합니다. migration 004는 표시용 이름 컬럼과 이름 치환 메타데이터만 제거하므로 데이터 재수집이 필요 없습니다.
컬럼 정리 이후에는 제거된 컬럼을 참조하는 이전 API·worker 이미지로 되돌리지 않습니다. 복구는 현재 스키마를 지원하는 수정 릴리스를 사용합니다.
아래 systemd 절은 Kubernetes 대신 호스트 서비스를 사용하는 대안입니다. 같은 수집을 양쪽에서 동시에 활성화하지 않습니다.

## 환경과 권한

API 환경 파일 `/etc/robinhood/api.env`를 다음과 같이 작성합니다.

```dotenv
DATABASE_URL=postgresql://API_USER:ENCODED_PASSWORD@DB_HOST:5432/MAIN_DB?sslmode=require
ROBINHOOD_DATABASE_SCHEMA=robinhood
ROBINHOOD_VAR=/var/lib/robinhood
NAVER_MAPS_CLIENT_ID=
```

worker 환경 파일 `/etc/robinhood/worker.env`에는 같은 DB의 적재 역할로 연결할 URL을 지정합니다.
API가 트랜잭션 풀을 사용하면 `ROBINHOOD_JOB_DATABASE_URL`에는 세션 잠금을 유지할 수 있는 직접 연결 URL을 지정합니다.
`ROBINHOOD_COLLECTOR_PYTHON=/srv/robinhood/.venv/bin/python`과 `ROBINHOOD_VAR=/var/lib/robinhood`도 설정합니다.
각 환경 파일은 해당 서비스를 실행하는 계정만 읽을 수 있도록 권한을 설정합니다.

저장소에는 SOPS 암호문 `credentials.yaml`과 KMS 설정 `.sops.yaml`이 있습니다.
worker 환경에 SOPS CLI를 설치하고, worker가 사용하는 GCP 계정에 해당 키의 `roles/cloudkms.cryptoKeyDecrypter` 권한을 부여합니다.
운영에서는 서비스 계정이나 Workload Identity로 ADC 인증을 구성합니다.
별도 ADC 파일이 필요하면 저장소 밖에 두고 systemd의 `ProtectHome`이 허용하는 경로에서 서비스 계정에 읽기 권한을 줍니다.
환경별 API 키는 `ASSEMBLY_API_KEY`와 `OPENFISCAL_API_KEY`로 지정할 수도 있습니다.

마이그레이션 역할에는 전용 스키마를 준비하고 그 안에서 테이블을 생성·변경할 권한이 필요합니다.
조회 API 역할에는 스키마의 `USAGE`와 테이블의 `SELECT` 권한을 부여합니다.
다음은 DB 관리자가 두 역할을 미리 만든 경우의 예입니다.
배포할 때는 실제 역할명을 사용합니다.

```sql
CREATE SCHEMA IF NOT EXISTS robinhood AUTHORIZATION robinhood_writer;
GRANT USAGE ON SCHEMA robinhood TO robinhood_api;
GRANT SELECT ON ALL TABLES IN SCHEMA robinhood TO robinhood_api;
ALTER DEFAULT PRIVILEGES FOR ROLE robinhood_writer IN SCHEMA robinhood
    GRANT SELECT ON TABLES TO robinhood_api;
```

API와 worker가 같은 역할을 사용해도 조회 API는 읽기 전용 트랜잭션을 엽니다.
운영 역할과 계정은 메인 DB의 계정 관리 절차에 따라 생성합니다.

## 준비와 최초 발행

프로젝트를 `/srv/robinhood`에 놓고 서비스 계정 `robinhood`가 `data/`, `site/data/`, `/var/lib/robinhood`를 읽고 쓸 수 있게 준비합니다.
최초 배포는 빈 데이터 볼륨과 DB에서 수집해 채웁니다.
다음 명령은 서비스 계정과 worker 환경변수가 설정된 셸에서 실행하며, SOPS CLI와 KMS 권한도 준비되어 있어야 합니다.

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

`collect`는 기관별 자료와 로컬에 없는 지도 원본을 내려받고 파싱·정규화 결과를 검증한 뒤 DB에 발행합니다.
최초 발행 전에는 `/api/health`가 HTTP 503을 반환합니다.
코드를 다시 배포할 때도 DB와 데이터 볼륨은 유지하고 worker가 자료를 주기적으로 갱신합니다.

강북구의회 첨부를 수집하려면 Chrome 또는 worker 이미지의 Chromium을 사용합니다.

OCI/Linux의 Tesseract 시스템 패키지와 한국어·영어 언어 데이터 설치 방법은 [OCR 실행 환경](../docs/INSTALL.md#ocr-실행-환경)에 기록했습니다.

## Linux 상시 실행

`systemd/robinhood-api.service`와 `systemd/robinhood-worker.service`의 실행 경로, 서비스 계정, 환경 파일 경로를 배포 환경에 맞춘 뒤 활성화합니다.

API 서비스 파일의 기본 포트는 8000입니다.
운영 프록시나 개발 예시의 8010번 포트에 맞추려면 서비스 파일의 `ExecStart`에서 `--port` 값을 바꿉니다.

```bash
sudo cp deploy/systemd/robinhood-api.service deploy/systemd/robinhood-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now robinhood-api robinhood-worker
sudo systemctl status robinhood-worker
journalctl -u robinhood-worker -f
```

worker는 시작할 때 PostgreSQL에 저장된 다음 실행 시각을 확인합니다.
일정이 없으면 즉시 수집하고, 성공하면 기본 설정에서 완료 시각의 24시간 뒤에 다시 수집합니다.
실패하면 1분, 5분, 15분 뒤에 차례로 재시도한 다음 정규 주기로 돌아갑니다.
여러 호스트에서 실행해도 잠금을 획득한 worker만 DB의 일정을 확인하고 수집을 시작합니다.
발행도 같은 연결에서 수행하므로 연결이 끊어지면 그 작업의 발행은 실패합니다.

Kubernetes CronJob 같은 외부 스케줄러를 쓸 때는 worker 서비스 대신 `robinhood run-due`를 1분마다 실행합니다.
이 작업에도 worker와 같은 환경변수와 원본 데이터 영구 볼륨을 연결합니다.
기관별 인증키·첨부 재사용 조건과 지원 기간은 [자동 갱신 범위](../robinhood-server/README.md#실제-자동-갱신-범위)에서 확인합니다.

## 선택적 Codex OCR 문구 정정

서버 환경에서 `uv sync --project robinhood-server --extra ocr-correction`으로 SDK를 설치하고 worker 환경에 `ROBINHOOD_OCR_CORRECTION_ENABLED=true`를 설정합니다.
수집 worker가 OCR 파싱과 정규화 사이에 SDK를 호출하므로 별도 스케줄러나 브라우저 자동화가 필요하지 않습니다.

worker 서비스 계정이 읽고 쓸 수 있는 전용 경로(예: `ROBINHOOD_OCR_CODEX_HOME=/var/lib/robinhood/codex-home`)에 ChatGPT 로그인을 준비합니다.
제공된 서비스 파일은 `ProtectHome=true`를 사용하므로 다른 사용자의 홈 디렉터리에 있는 인증 파일에 의존할 수 없습니다.
설정이나 인증 파일은 자동으로 복사하거나 변경하지 않습니다.
SDK는 API 키로 인증한 경우 정정 호출을 중단합니다.
계정 사용량 한도나 로그인 상태 때문에 실행이 실패하면 수집 worker의 재시도 일정을 따릅니다.

호출당 제한 시간과 실행당 묶음 수, 묶음당 행 수는 서버의 [예제 환경 파일](../robinhood-server/.env.example)에 있는 `ROBINHOOD_OCR_*` 설정으로 조정합니다.
`ocr-correct --plan`으로 모델 호출 없이 대상과 입력 크기를 확인할 수 있습니다.
PostgreSQL 마이그레이션 002는 정정 이력을 별도 테이블에 저장할 수 있도록 합니다.
원본과 OCR 추출본을 보존하고 다음 정규화에서 검증한 정정본을 적용합니다.
정정 대상과 검증 기준은 [서버 안내](../robinhood-server/README.md#ocr-표-텍스트-정정)에 있습니다.

## 확인과 복구

- `/api/health`는 발행한 자료를 조회할 수 있으면 HTTP 200, 아직 적재하지 않았거나 DB를 읽을 수 없으면 HTTP 503을 반환합니다.
- `/api/v1/jobs/status`에서 최근 수집 단계와 상태, 시도 횟수, 발행 여부, 다음 실행 시각을 확인합니다.
- `/api/v1/jobs/history?limit=20`에서 여러 호스트가 같은 DB에 기록한 최근 실행 이력을 확인합니다.
- 수집 로그 본문은 worker 호스트의 `ROBINHOOD_VAR/logs/`에서 확인합니다.

적재에 실패하면 PostgreSQL 트랜잭션을 롤백하므로 API는 이전 자료를 계속 제공합니다.
원인을 고친 뒤 `collect`로 바로 다시 수집하거나 worker의 재시도를 기다립니다.
다음 worker가 잠금을 획득하면 완료 전에 멈춘 이전 실행을 `interrupted`로 기록합니다.
메인 PostgreSQL의 백업·autovacuum 정책을 적용하고 원본 파일과 OCR 캐시는 별도로 백업합니다.

발행과 롤백에 사용하는 동작은 [PostgreSQL 트랜잭션 격리](https://www.postgresql.org/docs/current/transaction-iso.html), [advisory lock](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS), [psycopg COPY와 롤백](https://www.psycopg.org/psycopg3/docs/basic/copy.html) 문서를 참고합니다.
