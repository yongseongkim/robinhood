# 나랏일보고서

나랏일보고서는 국회의원 정치자금, 지방의회 경비, 신고재산·의정활동, 국가재정 공개자료를 살펴보는 서비스다.
지역 지도와 순위, 그래프에서 상세 내역을 열어 원자료를 확인할 수 있다.
금액은 같은 기간과 재원 안에서 비교한다.

## 전체 시스템

```text
Public sources -> Worker -> Raw files
                                |
                                v
                      Parse / OCR / normalize
                                |
                                v
                        Processed files
                                |
                                v
                           PostgreSQL
                                ^
                                | SQL / rows
                                v
                             FastAPI
                                ^
                                | HTTP / JSON
                                v
                          React browser
```

- `robinhood-web/`의 React·TypeScript 대시보드는 FastAPI가 반환한 JSON으로 화면을 그린다.
- `robinhood-server/`에는 FastAPI 조회 API와 자료를 주기적으로 수집·가공해 DB에 반영하는 worker가 있다.
- `pipeline/`에서 공개자료를 수집하고 문서의 표를 추출해 정규화·분석한다.
- PostgreSQL에는 조회 데이터와 수집·정정 이력을 저장한다.
  로컬 개발에서는 SQLite도 쓸 수 있다.
- `site/`는 가공한 자료를 정적 파일로 제공하는 사이트다.
- `deploy/Dockerfile`: ARM64 `api` (React 빌드 포함), `worker` (Chromium·수집 의존성) target.
- `deploy/helm/`: 웹과 API를 함께 제공하는 Service `robinhood:80`, API·worker·PreSync migration·PostSync 컬럼 정리·원본 PVC. 인물·상호는 공개자료의 원래 이름을 쓰고 개인 수령인·개인사업자 번호는 마스킹. Namespace·DB 계정·Secret·운영 values·ArgoCD·Cloudflare는 homelab-infra가 소유.
- `.github/workflows/images.yml`: PR 빌드 검증, `vMAJOR.MINOR.PATCH` 태그 push 시 두 ARM64 이미지를 OCIR에 게시한 뒤 `deploy/production` 브랜치를 승격해 ArgoCD 자동 배포. `deploy/promote_release.py`가 태그 소스의 차트·이미지 버전과 `deploy/release.json`을 기록하며 이전 버전으로의 자동 강등을 막음. 수동 workflow 실행은 이미지만 게시. CI 인증은 repository Secrets `OCI_REGISTRY_USERNAME`, `OCI_AUTH_TOKEN`과 승격용 `GITHUB_TOKEN`; 클러스터 pull Secret은 homelab-infra가 관리.
- 나라 살림은 공식 수집 자료의 결산·확정 예산·정부안을 구분해 연도별 증감·비중 추세를 제공. 정부안은 전년도 확정 예산과 비교하며 결측·0원 기준액·부처명 변경에서 계산할 수 없는 증감률은 null.

원본과 중간 결과는 파일로 보관하고, 검증을 마친 조회 데이터를 DB에 반영한다.
원본 문서와 정정 이력은 따로 보관한다.
DB에 반영한 자료는 웹을 다시 빌드하지 않아도 다음 API 요청부터 조회할 수 있다.

이 문서에는 서비스 목적과 시스템 개요만 둔다.
설치·실행 절차와 시스템·Python 의존성은 [설치 안내](docs/INSTALL.md), 플랫폼별 요구사항은 [OCR 실행 환경](docs/INSTALL.md#ocr-실행-환경)에서 확인한다.
세부 동작과 데이터 구조는 해당 소스코드와 테스트에서 확인한다.
