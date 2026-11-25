# 설치·실행 안내

로컬 개발 예시는 API에 8010번, 웹 개발 서버에 5173번 포트를 사용합니다.
서비스 구성은 [루트 README](../README.md), 자료의 출처와 수집 범위는 [데이터 출처 문서](DATA_SOURCES.md)에서 확인합니다.

운영 계정의 권한과 서비스 활성화 절차는 [배포 안내](../deploy/README.md)에, 서버가 자료를 저장하고 갱신하는 기준은 [서버 안내](../robinhood-server/README.md)에 있습니다.

Linux worker는 Tesseract로 새 스캔 PDF를 읽습니다.
저장소의 worker 이미지에는 필요한 언어 데이터가 들어 있습니다.

## 필요한 환경

- Python 3.12 이상과 uv.
- Node.js 22.12 이상과 npm.
- 운영 저장소로 사용할 기존 PostgreSQL. 로컬 확인에는 SQLite를 사용할 수 있습니다.
- 스캔 문서 OCR의 시스템 패키지와 현재 지원 범위는 [OCR 실행 환경](#ocr-실행-환경)을 확인합니다.
- 강북구의회 자료 수집에는 설치된 Google Chrome이 필요합니다.
- 저장소의 암호화된 API 키를 사용할 환경에는 SOPS CLI와 해당 GCP KMS 키의 복호화 권한이 필요합니다.

## 의존성 설치

```bash
git clone https://github.com/yongseongkim/robinhood.git
cd robinhood
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pipeline/requirements.txt
uv sync --project robinhood-server
npm ci --prefix robinhood-web
```

루트의 `.venv`는 수집·파싱 스크립트가 사용하고 `robinhood-server/.venv`는 API와 worker가 사용합니다.
수집부터 발행까지 실행하려면 두 환경을 모두 준비합니다.

처음 설정할 때 서버의 예제 환경 파일을 복사하고 사용할 값을 입력합니다.
기존 `.env`가 있으면 그 파일을 수정합니다.

```bash
cp robinhood-server/.env.example robinhood-server/.env
```

로컬 SQLite를 사용하려면 PostgreSQL 연결 URL을 비워 둡니다.
PostgreSQL을 쓰려면 `DATABASE_URL`에 기존 메인 DB의 연결 URL을 지정하고, 전용 스키마는 `ROBINHOOD_DATABASE_SCHEMA=robinhood`로 설정합니다.
조회 역할과 적재 역할을 나눌 때는 `ROBINHOOD_JOB_DATABASE_URL`에 적재용 연결 URL을 지정합니다.
필요한 권한은 [운영 배포 안내](../deploy/README.md)에 있습니다.

## OCR 실행 환경

Python 의존성은 `pipeline/requirements.txt`로 설치합니다.
Tesseract CLI와 언어 데이터는 운영체제의 패키지 관리자로 설치합니다.

| 실행 환경 | OCR 엔진과 시스템 의존성 | 현재 연동 상태 |
|---|---|---|
| macOS | Apple Vision. Python 바인딩 `pyobjc-framework-Vision`, `pyobjc-framework-Quartz`는 requirements의 macOS 조건으로 설치 | 파이프라인에 연결됨 |
| OCI/Linux | Tesseract CLI와 한국어 `kor`·영어 `eng` 언어 데이터 | 파이프라인에 연결됨 |

Linux에서 새로 읽은 거래는 행의 금액 합계가 원문 인쇄 합계와 일치하고 날짜·금액 검사를 통과해야 집계합니다.
보류한 파일과 사유는 `data/staging/<의회>_ocr_report.json`에서 확인할 수 있습니다.
재인식이 실패하면 같은 원본·기간에 이미 공개한 행을 기존 추출 보고서의 행 수·금액과 대조해 보존합니다.
해당 행에는 기존 신뢰도를 유지하고, 공개 공백 화면에 재검증 보류 사유를 표시합니다.

OCI의 Ubuntu/Debian 인스턴스에서는 다음 시스템 패키지를 설치합니다.
Oracle Linux 등 다른 배포판에서는 해당 OS에 맞는 패키지 관리자를 사용합니다.

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng
tesseract --version
tesseract --list-langs
```

`tesseract --list-langs` 결과에 `kor`와 `eng`가 있는지 확인합니다.
저장소에서 제공하는 Linux worker 이미지에는 Tesseract와 두 언어 데이터가 포함돼 있습니다.
이 명령은 엔진과 언어 데이터 설치 여부를 확인합니다.

패키지와 실행 옵션은 [Tesseract 설치 안내](https://tesseract-ocr.github.io/tessdoc/Installation.html), [Ubuntu 한국어 언어 데이터 패키지](https://packages.ubuntu.com/noble/tesseract-ocr-kor), [Tesseract CLI 안내](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)에서 확인합니다.

## API 인증키

열린국회정보와 열린재정 API 키는 저장소의 SOPS 암호문 `credentials.yaml`에 포함되어 있습니다.
`.sops.yaml`에는 GCP KMS 키와 암호화 규칙이 들어 있습니다.
두 파일은 함께 버전 관리하며 평문으로 복호화한 사본은 커밋하지 않습니다.

수집 worker가 사용할 계정에 해당 KMS 키의 `roles/cloudkms.cryptoKeyDecrypter` 권한을 부여하고 애플리케이션 기본 사용자 인증 정보(ADC)를 설정합니다.
운영에서는 서비스 계정이나 Workload Identity를 사용하고, 로컬에서는 `gcloud auth application-default login`으로 인증할 수 있습니다.
ADC 파일과 서비스 계정 인증 파일은 배포 환경에서 관리합니다.
역할에 포함된 권한은 [GCP KMS 역할 안내](https://docs.cloud.google.com/kms/docs/reference/permissions-and-roles)에서 확인합니다.

저장소를 다시 복제해도 SOPS 암호문은 함께 내려옵니다.
환경별 키를 사용하려면 worker 환경변수나 로컬 `.env`에 다음 값을 지정합니다.

```dotenv
ASSEMBLY_API_KEY=YOUR_ASSEMBLY_KEY
OPENFISCAL_API_KEY=YOUR_OPENFISCAL_KEY
```

`uv run --env-file .env`로 시작한 worker는 수집 프로세스에도 이 값을 전달합니다.
루트에서 `pipeline/run_all.sh`를 직접 실행하면 같은 변수를 현재 셸에 설정해야 합니다.
인증키가 없으면 해당 수집기는 이전 자료를 유지하거나 수집을 건너뜁니다.

수집기는 환경변수를 먼저 읽고, 값이 없을 때 SOPS로 해당 키를 메모리에서 복호화합니다.
DB 연결 URL이나 평문 API 키가 들어 있는 `.env`는 Git에서 제외합니다.

SOPS와 KMS 인증이 준비된 환경에서는 저장소 루트에서 암호문 상태와 키 읽기 권한을 확인합니다.
확인 명령은 키 값 자체를 출력하지 않습니다.

```bash
python3 scripts/check_encrypted_credentials.py
sops filestatus credentials.yaml
.venv/bin/python pipeline/credentials.py
.venv/bin/python pipeline/credentials.py openfiscal_api_key
```

암호문에 저장된 키를 변경할 때만 `sops credentials.yaml`로 편집합니다.

## 데이터 준비와 최초 적재

원본·중간 결과·정규화 자료와 로컬 DB는 Git에 포함되지 않습니다.
최초 배포에서는 빈 데이터 볼륨과 DB에서 실제 자료를 새로 수집해 채웁니다.
데이터가 준비되지 않은 동안 `/api/health`는 503을 반환합니다.

지도 생성기는 `data/raw/geo/`에 없는 지도 원본·출처 문서를 처음 실행할 때 내려받습니다.
다운로드와 JSON 검증이 완료된 파일만 보관하고, 이미 받은 파일은 재사용합니다.
`--no-fetch` 재처리에서는 지도도 내려받지 않습니다.
출처와 라이선스는 [지도 원본 파일](DATA_SOURCES.md#지도-원본-파일)에 기록했습니다.

로컬 설치에서는 이후 서버 명령을 `robinhood-server/` 디렉터리에서 실행합니다.
운영 환경 파일을 사용하는 경우에는 [배포 안내](../deploy/README.md)의 명령을 따릅니다.

```bash
cd robinhood-server
```

PostgreSQL을 설정했다면 먼저 전용 스키마와 테이블을 준비합니다.
SQLite 모드에서는 이 단계를 생략합니다.

```bash
uv run --env-file .env robinhood migrate
```

`collect`는 최초 수집부터 가공·검증·조회 DB 발행까지 실행하므로, 완료 후 `index`를 따로 실행할 필요가 없습니다.

```bash
uv run --env-file .env robinhood collect
```

이후 배포에서는 DB와 `data/` 볼륨을 유지하고 worker가 주기적으로 갱신합니다.
이미 받은 원본으로 다시 가공하려면 `collect --no-fetch`, 정규화 자료를 조회 DB에 다시 적재하려면 `index`를 사용합니다.
실제 갱신 범위와 출처별 조건은 [서버 안내](../robinhood-server/README.md)에 있습니다.

## 로컬 웹과 API

서버 디렉터리의 터미널에서 API를 실행합니다.

```bash
uv run --env-file .env robinhood serve --port 8010
```

별도 터미널에서 저장소 루트 기준으로 웹을 실행합니다.

```bash
cd robinhood-web
ROBINHOOD_API_URL=http://127.0.0.1:8010 npm run dev
```

웹은 `http://localhost:5173`, API 명세는 `http://127.0.0.1:8010/api/docs`입니다.
Vite가 `/api` 요청을 API로 전달합니다.
다른 포트를 사용하면 API의 `--port`와 웹의 `ROBINHOOD_API_URL`을 함께 맞춥니다.

웹을 빌드하면 FastAPI가 웹과 API를 같은 출처에서 제공합니다.
저장소 루트에서 빌드한 뒤 API를 실행하면 `http://127.0.0.1:8010`에서 확인할 수 있습니다.

```bash
npm run build --prefix robinhood-web
```

웹 빌드는 코드 변경 시 수행합니다.
수집 데이터 갱신은 다음 API 요청에 반영됩니다.

## 주기 수집

`robinhood-server/`에서 API와 별도 프로세스로 worker를 실행합니다.

```bash
uv run --env-file .env robinhood worker --interval-hours 24
```

위 설정에서 worker는 수집에 성공하면 완료 시각에서 24시간 뒤에 다시 수집합니다.
실패하면 1분, 5분, 15분 뒤에 차례로 재시도합니다.
DB 적재에 실패해도 이전 조회 자료는 그대로 제공됩니다.
`serve`는 조회 API를 실행하고, 주기 수집은 `worker`가 담당합니다.

Linux 상시 실행과 외부 스케줄러 구성은 [운영 배포 안내](../deploy/README.md)를 참고하세요.

## 지도와 선택적 OCR 문구 정정

네이버 지도를 쓰려면 서버의 `NAVER_MAPS_CLIENT_ID`에 공개 키 ID를 지정하고 Maps 애플리케이션에 웹 서비스 URL을 등록합니다.
키가 없으면 행정구역 경계 지도를 표시합니다.
현재 장소 지도는 각 구의 대표 좌표에 거래처 수를 표시합니다.
지도 설정과 동작은 [웹 안내](../robinhood-web/README.md)에 있습니다.

OCR 표 텍스트 정정은 기본으로 꺼져 있습니다.
선택 기능을 사용하려면 서버 디렉터리에서 SDK를 설치하고 전용 ChatGPT 로그인 환경과 `ROBINHOOD_OCR_*` 설정을 준비합니다.

```bash
uv sync --extra ocr-correction
uv run --env-file .env robinhood ocr-correct --plan
```

`--plan`은 모델 호출·DB 저장 없이 대상을 확인합니다.
정정 범위·입력 제한·이력과 활성화 설정은 [서버 안내](../robinhood-server/README.md)에 있습니다.

## 검증

`robinhood-server/`에서 서버 테스트를 실행합니다.

```bash
uv run pytest -q
```

`robinhood-web/`에서 빌드와 코드 형식을 확인합니다.

```bash
npm run build
npm run format:check
```

저장소 루트에서는 테스트 실행용 pytest를 추가한 뒤 수집·정규화 테스트를 실행합니다.

```bash
uv pip install --python .venv/bin/python 'pytest>=9.1,<10'
.venv/bin/python -m pytest -q tests
```

서버의 예제 입력 기반 테스트는 수집 자료 없이 실행됩니다.
실제 수집본 대조 테스트는 조회 인덱스가 필요하고, PostgreSQL 통합 테스트는 별도 테스트 DB의 `TEST_POSTGRES_URL`이 필요합니다.
브라우저 검사는 [웹 안내](../robinhood-web/README.md), PostgreSQL 엔진 검사는 [서버 안내](../robinhood-server/README.md)에 있습니다.

## 기존 정적 사이트

기존 자료로 정적 사이트 데이터를 다시 만들려면 저장소 루트에서 실행합니다.

```bash
pipeline/run_all.sh --no-fetch
```

완료 후 `site/index.html`을 브라우저에서 열거나 `site/` 전체를 정적 호스팅에 배포합니다.
이 방식은 `site/data/*.js`를 사용하며, 새 React 웹의 API 조회 방식과 별도로 유지됩니다.
