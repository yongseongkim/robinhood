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

원본·중간 결과는 파일로 보관하고 검증한 조회 데이터를 DB에 반영합니다. 원본 문서와 정정 이력은 구분해 관리합니다. 데이터 갱신은 다음 API 조회에 반영되며 웹을 다시 빌드할 필요가 없습니다.

이 문서는 서비스 목적과 시스템 개요만 유지합니다. 설치·실행은 [설치 안내](docs/INSTALL.md), 세부 동작과 데이터 구조는 관련 소스코드와 테스트를 확인합니다.
