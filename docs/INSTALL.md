# 설치·실행 안내

서비스 목적과 구성은 [루트 README](../README.md), 자료의 출처·수집 범위는 [데이터 출처 문서](DATA_SOURCES.md)를 참고하세요. 아래 개발 예시는 API에 8010, 웹 개발 서버에 5173 포트를 사용합니다.

이 문서의 설치·최초 적재·로컬 실행 절차를 공통 안내로 사용합니다. 운영 권한과 서비스 활성화는 [배포 안내](../deploy/README.md), 서버의 저장·갱신 정책은 [서버 안내](../robinhood-server/README.md)에 있습니다.

현재 Linux에서 API·일반 자료 수집은 실행할 수 있지만, 새 스캔 PDF의 OCR은 macOS Vision 구현에 의존합니다. 아래 Tesseract 설치 절차는 Linux 연동을 위한 준비이며, OCI에서 모든 스캔 자료까지 처리하는 수집 환경은 아직 완성되지 않았습니다.

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

루트 `.venv`는 수집·파싱용이고 `robinhood-server/.venv`는 API·worker용입니다. 두 환경 모두 필요합니다.

처음 설정할 때 서버의 예제 환경 파일을 복사하고 사용할 값을 입력합니다. 기존 `.env`가 있으면 그 파일을 수정합니다.

```bash
cp robinhood-server/.env.example robinhood-server/.env
```

`DATABASE_URL`을 비워 두면 로컬 SQLite를 사용합니다. PostgreSQL을 쓰면 기존 메인 DB의 연결 URL을 설정하고 `ROBINHOOD_DATABASE_SCHEMA=robinhood` 전용 스키마를 사용합니다. API 조회 역할과 적재 역할을 분리할 때는 `ROBINHOOD_JOB_DATABASE_URL`도 설정합니다. 권한 구성은 [운영 배포 안내](../deploy/README.md)에 있습니다.

## OCR 실행 환경

Python 패키지는 `pipeline/requirements.txt`로 설치하고, OCR 엔진 같은 시스템 의존성은 OS 패키지 관리자로 별도 설치합니다. Tesseract 본체와 언어 데이터는 `pip install -r pipeline/requirements.txt`로 설치되지 않습니다.

| 실행 환경 | OCR 엔진과 시스템 의존성 | 현재 연동 상태 |
|---|---|---|
| macOS | Apple Vision. Python 바인딩 `pyobjc-framework-Vision`, `pyobjc-framework-Quartz`는 requirements의 macOS 조건으로 설치 | 파이프라인에 연결됨 |
| OCI/Linux | Tesseract CLI와 한국어 `kor`·영어 `eng` 언어 데이터 | 어댑터 구현 전. 설치만으로 현재 파이프라인의 Linux OCR이 활성화되지는 않음 |

현재 `pipeline/ocr.py`는 Apple Vision을 직접 호출합니다. Linux에서 새 스캔 PDF를 처리하려면 Tesseract 출력을 기존 문자·좌표·신뢰도 형식에 맞추는 어댑터와 실제 표의 금액·행 검증이 추가로 필요합니다. 아래 명령은 그 연동을 위한 실행 환경 준비입니다.

OCI의 Ubuntu/Debian 인스턴스에서는 다음 시스템 패키지를 설치합니다. Oracle Linux 등 다른 배포판에서는 해당 OS에 맞는 패키지 관리자를 사용합니다.

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng
tesseract --version
tesseract --list-langs
```

언어 목록에 `kor`와 `eng`가 있어야 합니다. worker를 컨테이너로 실행하면 Tesseract와 언어 데이터도 worker 이미지 안에 설치합니다. 설치 확인과 실제 파이프라인 OCR 검증은 별도로 수행합니다.

설치 기준: [Tesseract 공식 설치 안내](https://tesseract-ocr.github.io/tessdoc/Installation.html), [Ubuntu 한국어 언어 데이터 패키지](https://packages.ubuntu.com/noble/tesseract-ocr-kor), [Tesseract CLI 안내](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

## API 인증키

열린국회정보와 열린재정 API 키는 저장소의 SOPS 암호문 `credentials.yaml`에 포함되어 있습니다. `.sops.yaml`에는 GCP KMS 키와 암호화 규칙이 들어 있습니다. 두 파일은 함께 버전 관리하며 평문으로 복호화한 사본은 커밋하지 않습니다.

수집 worker의 실행 주체에 해당 KMS 키의 `roles/cloudkms.cryptoKeyDecrypter` 권한과 ADC 인증 경로를 준비합니다. 운영에서는 서비스 계정이나 Workload Identity를 사용하고, 로컬에서는 `gcloud auth application-default login`을 사용할 수 있습니다. 권한 범위는 [GCP KMS 역할 안내](https://docs.cloud.google.com/kms/docs/reference/permissions-and-roles)를 참고하세요. ADC·서비스 계정 인증 파일은 Git에 넣지 않고 배포 환경에서 관리합니다.

기존 암호문을 사용하면 재클론 후 파일을 따로 복원할 필요가 없습니다. 환경별 키로 덮어쓸 때는 worker 환경변수 또는 로컬 `.env`에 설정합니다.

```dotenv
ASSEMBLY_API_KEY=YOUR_ASSEMBLY_KEY
OPENFISCAL_API_KEY=YOUR_OPENFISCAL_KEY
```

`uv run --env-file .env`로 시작한 worker는 수집 프로세스에도 이 값을 전달합니다. 루트에서 `pipeline/run_all.sh`를 직접 실행하면 같은 변수를 현재 셸에 설정해야 합니다. 인증키가 없으면 해당 수집기는 이전 자료를 유지하거나 수집을 건너뜁니다.

환경변수가 우선이며 SOPS는 메모리에서 복호화합니다. 배포 DB URL이나 평문 API 키가 담긴 `.env`도 Git에서 제외합니다.

SOPS와 KMS 인증이 준비된 환경에서는 저장소 루트에서 암호문 상태와 키 읽기 권한을 확인합니다. 확인 명령은 키 값 자체를 출력하지 않습니다.

```bash
python3 scripts/check_encrypted_credentials.py
sops filestatus credentials.yaml
.venv/bin/python pipeline/credentials.py
.venv/bin/python pipeline/credentials.py openfiscal_api_key
```

키를 변경할 때는 별도로 `sops credentials.yaml`을 사용합니다. 최초 실행을 위해 암호문을 편집할 필요는 없습니다.

## 데이터 준비와 최초 적재

원본·중간 결과·정규화 자료와 로컬 DB는 Git에 포함되지 않습니다. 최초 배포에서는 빈 데이터 볼륨과 DB에서 실제 자료를 새로 수집해 채웁니다. 데이터가 준비되지 않은 동안 `/api/health`는 503을 반환합니다.

지도 생성기는 `data/raw/geo/`에 없는 지도 원본·출처 문서를 처음 실행할 때 내려받습니다. 다운로드와 JSON 검증이 완료된 파일만 보관하고, 이미 받은 파일은 재사용합니다. `--no-fetch` 재처리에서는 지도도 내려받지 않습니다. 출처와 라이선스는 [지도 원본 파일](DATA_SOURCES.md#지도-원본-파일)에 기록했습니다.

로컬 설치에서는 이후 서버 명령을 `robinhood-server/` 디렉터리에서 실행합니다. 운영 환경 파일을 사용하는 경우에는 [배포 안내](../deploy/README.md)의 명령을 따릅니다.

```bash
cd robinhood-server
```

PostgreSQL을 설정했다면 먼저 전용 스키마와 테이블을 준비합니다. SQLite 모드에서는 이 단계를 생략합니다.

```bash
uv run --env-file .env robinhood migrate
```

최초 수집부터 가공·검증·DB 반영까지 실행합니다. 이 명령은 마지막에 조회 데이터를 발행하므로 별도 `index` 실행이 필요하지 않습니다.

```bash
uv run --env-file .env robinhood collect
```

이후 배포에서는 DB와 `data/` 볼륨을 유지하고 worker가 주기적으로 갱신합니다. 이미 받은 원본으로 다시 가공하려면 `collect --no-fetch`, 정규화 자료를 조회 DB에 다시 적재하려면 `index`를 사용합니다. 실제 갱신 범위와 출처별 조건은 [서버 안내](../robinhood-server/README.md)에 있습니다. 새 스캔 문서를 모두 처리하려면 macOS OCR 수집 환경이 필요합니다.

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

웹은 `http://localhost:5173`, API 명세는 `http://127.0.0.1:8010/api/docs`입니다. Vite가 `/api` 요청을 API로 전달합니다. 다른 포트를 사용하면 API의 `--port`와 웹의 `ROBINHOOD_API_URL`을 함께 맞춥니다.

웹을 빌드하면 FastAPI가 웹과 API를 같은 출처에서 제공합니다. 저장소 루트에서 빌드한 뒤 API를 실행하면 `http://127.0.0.1:8010`에서 확인할 수 있습니다.

```bash
npm run build --prefix robinhood-web
```

웹 빌드는 코드 변경 시 수행합니다. 수집 데이터 갱신은 다음 API 요청에 반영됩니다.

## 주기 수집

API와 별도의 프로세스로 worker를 실행합니다. 아래 명령은 서버 디렉터리에서 실행합니다.

```bash
uv run --env-file .env robinhood worker --interval-hours 24
```

worker는 저장된 다음 실행 시각을 확인하고 성공 완료 후 24시간 뒤에 다시 수집합니다. 실패하면 1·5·15분 간격으로 재시도하며, 실패한 발행은 이전 조회 데이터를 유지합니다. `serve`만 실행하면 주기 수집은 시작되지 않습니다.

Linux 상시 실행과 외부 스케줄러 구성은 [운영 배포 안내](../deploy/README.md)를 참고하세요.

## 지도와 선택적 OCR 문구 정정

네이버 지도를 쓰려면 서버 환경의 `NAVER_MAPS_CLIENT_ID`에 공개 키 ID를 설정하고 웹 서비스 URL을 등록합니다. 키가 없으면 행정구역 지도를 표시합니다. 현재 장소 데이터의 좌표는 구별 대표 위치입니다. 상세 설명은 [웹 안내](../robinhood-web/README.md)에 있습니다.

OCR 표 텍스트 정정은 기본으로 꺼져 있습니다. 선택 기능을 사용하려면 서버 디렉터리에서 SDK를 설치하고 전용 ChatGPT 로그인 환경과 `ROBINHOOD_OCR_*` 설정을 준비합니다.

```bash
uv sync --extra ocr-correction
uv run --env-file .env robinhood ocr-correct --plan
```

`--plan`은 모델 호출·DB 저장 없이 대상을 확인합니다. 정정 범위·입력 제한·이력과 활성화 설정은 [서버 안내](../robinhood-server/README.md)에 있습니다.

## 검증

서버 디렉터리에서:

```bash
uv run pytest -q
```

웹 디렉터리에서:

```bash
npm run build
npm run format:check
```

저장소 루트에서는 테스트 실행용 pytest를 추가한 뒤 수집·정규화 테스트를 실행합니다.

```bash
uv pip install --python .venv/bin/python 'pytest>=9.1,<10'
.venv/bin/python -m pytest -q tests
```

서버의 예제 입력 기반 테스트는 수집 자료 없이 실행됩니다. 실제 수집본 대조 테스트는 조회 인덱스가 필요하고, PostgreSQL 통합 테스트는 별도 테스트 DB의 `TEST_POSTGRES_URL`이 필요합니다. 브라우저 검사는 [웹 안내](../robinhood-web/README.md), PostgreSQL 엔진 검사는 [서버 안내](../robinhood-server/README.md)에 있습니다.

## 기존 정적 사이트

기존 자료로 정적 사이트 데이터를 다시 만들려면 저장소 루트에서 실행합니다.

```bash
pipeline/run_all.sh --no-fetch
```

완료 후 `site/index.html`을 브라우저에서 열거나 `site/` 전체를 정적 호스팅에 배포합니다. 이 방식은 `site/data/*.js`를 사용하며, 새 React 웹의 API 조회 방식과 별도로 유지됩니다.
