#!/usr/bin/env bash
# 기관별 자료를 수집·파싱하고 정규화와 탐지를 실행한다. 정적 사이트를 배포할 때는 화면용 데이터도 만든다.
# 사용법: pipeline/run_all.sh            (수집부터 전부)
#        pipeline/run_all.sh --no-fetch  (이미 받은 원본으로 재처리만)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${ROBINHOOD_PIPELINE_PYTHON:-.venv/bin/python}"
if [[ "${1:-}" != "--no-fetch" ]]; then
  $PY pipeline/collect_ka_money.py
  $PY pipeline/collect_assembly.py   # 열린국회정보 인증키는 환경변수 또는 credentials.yaml에서 읽는다.
  $PY pipeline/collect_votes.py      # 의안별 표결을 1초 간격으로 조회한다. 최초 수집 예상 시간은 약 1.5시간이며 이후에는 저장본을 재사용한다.
  $PY pipeline/collect_fiscal.py     # 열린재정 나라 살림 (openfiscal_api_key 필요, 없으면 건너뜀)
  $PY pipeline/collect_assets.py     # 국회공보 정기재산공개 PDF (최신 호만, 이미 받았으면 건너뜀)
  $PY pipeline/collect_peti.py
  $PY pipeline/filing_totals.py
  $PY pipeline/collect_gwanak.py
  $PY pipeline/collect_mapo.py
  $PY pipeline/collect_seoul.py
  $PY pipeline/collect_roles.py   # 의회 홈페이지의 직책 보유자(의장단·위원장) 기록
  $PY pipeline/collect_roles_seoul.py
  for g in pipeline/districts/g*.py; do [[ "$g" == *_* ]] || $PY "$g" collect; done
fi
$PY pipeline/parse_gwanak.py
$PY pipeline/parse_mapo.py
$PY pipeline/parse_seoul.py
for g in pipeline/districts/g*.py; do [[ "$g" == *_* ]] || $PY "$g" parse; done
$PY pipeline/parse_ocr.py
# 서버 worker가 지정한 Python으로 정정 단계를 실행한다. 검증된 정정본은 원본·OCR 추출본과 별도로 보관한다.
if [[ -n "${ROBINHOOD_OCR_CORRECTION_PYTHON:-}" ]]; then
  "$ROBINHOOD_OCR_CORRECTION_PYTHON" -m robinhood_server.ocr_correction
fi
# 지도 경로·시군구 인접 정보. 원본 재처리에서는 지도도 내려받지 않는다.
if [[ "${1:-}" == "--no-fetch" ]]; then
  $PY pipeline/build_geo.py --no-fetch
else
  $PY pipeline/build_geo.py
fi
$PY pipeline/normalize.py
$PY pipeline/detect.py
$PY pipeline/assembly.py           # 의정활동 ↔ 의원 연결
$PY pipeline/parse_assets.py       # 국회의원 재산 (항목 합계·총계 검증, 부동산 위치는 읍·면·동까지만)
if [[ "${ROBINHOOD_SKIP_LEGACY_SITE:-0}" != "1" ]]; then
  $PY pipeline/build_site.py
fi
echo "done: open site/index.html"
