# 나랏일보고서

국회의원 정치자금, 지방의회 경비, 신고재산·의정활동, 국가재정 공개자료를 살펴보는 서비스입니다. 지역 지도, 순위, 그래프와 상세 내역으로 정보를 제공하고 원자료까지 확인할 수 있도록 합니다. 금액은 기간과 재원을 구분해 비교합니다.

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

- `robinhood-web/`: React·TypeScript 웹 대시보드. FastAPI가 반환하는 JSON으로 화면을 표시합니다.
- `robinhood-server/`: FastAPI 조회 API와 주기적인 수집·가공·DB 반영 작업.
- `pipeline/`: 공개자료 수집, 문서·표 추출, 정규화와 분석.
- PostgreSQL: 서비스 조회 데이터와 수집·정정 이력 저장. 로컬 개발에서는 SQLite도 지원합니다.
- `site/`: 기존 정적 사이트.
- `deploy/Dockerfile`: ARM64 `api` (React 빌드 포함), `worker` (Chromium·수집 의존성) target.
- `deploy/helm/`: 웹과 API를 함께 제공하는 Service `robinhood:80`, API·worker·PreSync migration·원본 PVC. Namespace·DB 계정·Secret·운영 values·ArgoCD·Cloudflare는 homelab-infra가 소유.
- `.github/workflows/images.yml`: PR 빌드 검증, `vMAJOR.MINOR.PATCH` 태그 push 시 두 ARM64 이미지를 OCIR에 게시한 뒤 `deploy/production` 브랜치를 승격해 ArgoCD 자동 배포. `deploy/promote_release.py`가 태그 소스의 차트·이미지 버전과 `deploy/release.json`을 기록하며 이전 버전으로의 자동 강등을 막음. 수동 workflow 실행은 이미지만 게시. CI 인증은 repository Secrets `OCI_REGISTRY_USERNAME`, `OCI_AUTH_TOKEN`과 승격용 `GITHUB_TOKEN`; 클러스터 pull Secret은 homelab-infra가 관리.
- 나라 살림은 공식 수집 자료의 결산·확정 예산·정부안을 구분해 연도별 증감·비중 추세를 제공. 정부안은 전년도 확정 예산과 비교하며 결측·0원 기준액·부처명 변경에서 계산할 수 없는 증감률은 null.

원본·중간 결과는 파일로 보관하고 검증한 조회 데이터를 DB에 반영합니다. 원본 문서와 정정 이력은 구분해 관리합니다. 데이터 갱신은 다음 API 조회에 반영되며 웹을 다시 빌드할 필요가 없습니다.

이 문서는 서비스 목적과 시스템 개요만 유지합니다. 설치·실행과 시스템·Python 의존성은 [설치 안내](docs/INSTALL.md), 플랫폼별 OCR 요구사항은 [OCR 실행 환경](docs/INSTALL.md#ocr-실행-환경), 세부 동작과 데이터 구조는 관련 소스코드와 테스트를 확인합니다.
