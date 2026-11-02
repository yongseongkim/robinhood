#!/usr/bin/env bash
# 전체 파이프라인: 수집 → 파싱 → 정규화 → 탐지 → 사이트 데이터 생성
# 사용법: pipeline/run_all.sh            (수집부터 전부)
#        pipeline/run_all.sh --no-fetch  (이미 받은 원본으로 재처리만)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${ROBIN_HOOD_PIPELINE_PYTHON:-.venv/bin/python}"
if [[ "${1:-}" != "--no-fetch" ]]; then
  $PY pipeline/collect_ka_money.py
  $PY pipeline/collect_assembly.py   # 열린국회정보 (credentials.yaml의 인증키 필요, 없으면 건너뜀)
  $PY pipeline/collect_votes.py      # 본회의 표결: 새로 처리된 의안만 받음 (처음엔 약 1.5시간, 1초에 1회)
  $PY pipeline/collect_fiscal.py     # 열린재정 나라 살림 (openfiscal_api_key 필요, 없으면 건너뜀)
  $PY pipeline/collect_assets.py     # 국회공보 정기재산공개 PDF (최신 호만, 이미 받았으면 건너뜀)
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
# 스캔·이미지 PDF OCR (macOS Vision, 로컬 처리). 다른 OS에서는 건너뛰고 이전 결과를 쓴다.
$PY pipeline/parse_ocr.py || echo "OCR 건너뜀: macOS Vision을 쓸 수 없음 (이전 data/staging/*_ocr.jsonl 유지)"
# 서버 job이 지정한 정정 단계. 원본·OCR 추출본은 유지하고 별도 정정본만 만든다.
if [[ -n "${ROBIN_HOOD_OCR_CORRECTION_PYTHON:-}" ]]; then
  "$ROBIN_HOOD_OCR_CORRECTION_PYTHON" -m robin_hood_server.ocr_correction
fi
$PY pipeline/build_geo.py        # 지도 경로·시군구 인접 정보 (detect의 관할 지역 판단에도 사용)
$PY pipeline/normalize.py
$PY pipeline/detect.py
$PY pipeline/assembly.py           # 의정활동 ↔ 의원 연결
$PY pipeline/parse_assets.py       # 국회의원 재산 (항목 합계·총계 검증, 부동산 위치는 읍·면·동까지만)
if [[ "${ROBIN_HOOD_SKIP_LEGACY_SITE:-0}" != "1" ]]; then
  $PY pipeline/build_site.py
fi
echo "done: open site/index.html"
