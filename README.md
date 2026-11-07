# 나랏일보고서 · robinhood

국회의원 정치자금, 지방의회 경비, 신고재산·의정활동, 국가재정 공개자료를 기간·재원·출처별로 살펴보는 대시보드입니다. 지역 지도, 순위, 그래프와 거래 상세를 통해 공개된 돈의 흐름을 이해하고 근거 문서까지 확인할 수 있도록 합니다.

[설치·실행 안내](docs/INSTALL.md) · [데이터 출처와 수집본 기록](docs/DATA_SOURCES.md) · [운영 배포 안내](deploy/README.md)

## 제공하는 정보

- 내 지역 의원·의회와 의원·정당별 지출 항목, 기간별 변화와 순위.
- 의원·정당의 지출·신고재산·정치자금 수입 Top 10, 부동산·증권·예금·가상자산별 Top 10과 정당별 신고재산 Top 10.
- 자주 결제한 장소, 거래 상세와 원문 근거.
- 신고재산, 법안·표결, 국가 재정의 수입·지출·수지.
- 자료의 수집 시각, 대상 기간, 출처와 분석 기준.

금액은 같은 기간·재원 안에서 비교하고 공동경비는 개인 지출로 귀속하지 않습니다. 통계적 확인 표시는 추가 검토를 돕는 정보이며, 위반 판단과 구분합니다. 인물·상호는 공개자료의 원래 이름을 표시하며 개인 수령인과 개인사업자 번호의 마스킹은 유지합니다.

## 시스템 개요

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

수집 worker가 공개자료를 가져오고, 원본과 파싱·정규화 중간 결과를 파일로 보관합니다. 선택적인 OCR 문구 정정은 원문을 보존하고 별도 이력으로 관리합니다. 검증한 조회 데이터는 PostgreSQL에 반영하며, 적재에 실패하면 이전 조회 데이터를 유지합니다.

React 웹은 사용자가 고른 지역·기간·정당 등에 맞춰 `/api/v1/`을 호출합니다. FastAPI가 DB를 조회·집계한 JSON을 반환하고 웹이 화면을 표시합니다. 데이터 갱신 후에는 다음 API 요청부터 새 자료를 보여주므로 웹을 다시 빌드할 필요가 없습니다. 운영 저장소는 PostgreSQL이며, 로컬 개발에서는 SQLite도 지원합니다.

| 구성 | 역할 |
|---|---|
| `robinhood-web/` | React·TypeScript 웹 대시보드 |
| `robinhood-server/` | FastAPI 조회 API, 수집 worker, DB 반영 |
| `pipeline/` | 자료 수집, 파싱·OCR, 정규화와 분석 |
| `data/` | 원본과 중간·정규화 파일을 보관하는 별도 데이터 볼륨 |
| `site/` | 기존 정적 사이트 |

`site/`는 가공 자료를 정적 파일로 제공하는 기존 방식입니다. 새 웹은 API로 조회하며, 서버 worker는 기존 정적 사이트 생성을 건너뜁니다. 원본·가공 데이터와 DB는 최초 배포 후 수집·가공으로 채우고 이후에는 보존하며 주기 갱신합니다. 데이터·로컬 DB·캐시는 Git에서 제외합니다. SOPS 암호문인 `credentials.yaml`과 KMS 설정인 `.sops.yaml`은 버전 관리하고, 평문 키와 실행 환경의 인증 파일은 별도로 주입합니다.

현재 OCR은 macOS Vision을 사용하며 OCI/Linux OCR 어댑터는 구현 전입니다. Tesseract 설치 준비와 현재 지원 범위는 [OCR 실행 환경](docs/INSTALL.md#ocr-실행-환경)에 정리했습니다.

## 데이터 출처

| 자료 | 가져오는 곳 | 수집 내용 |
|---|---|---|
| 국회의원 정치자금 | [오마이뉴스·경향신문·뉴스타파 공동 KA-money](https://github.com/OhmyNews/KA-money) | 2023~2024년 회계보고 XLSX. 선관위 원문을 OCR로 변환한 2차 자료 |
| 지방의회 경비·직책 보유자 | [서울특별시의회](https://www.smc.seoul.kr/board/BoardList.do?boardTypeId=158&menuId=001007013001)와 [관악구의회](https://www.ga21c.seoul.kr/kr/costBBS.do)·[마포구의회](https://council.mapo.seoul.kr/kr/news/bbsCost.do) 등 서울 25개 구의회의 공식 홈페이지 | 업무추진비·의정운영공통경비의 PDF·엑셀, 공식 직책 선출 기록 |
| 의원 인적사항·법안·표결 | [국회사무처 열린국회정보](https://open.assembly.go.kr) | 공적 의원 정보, 대표발의 법률안, 본회의 표결 API |
| 신고재산 | [국회공보 정기재산공개](https://www.assembly.go.kr/portal/cnts/cntsNamgzn/gongbo.do) | 공보 원문 PDF의 재산 항목과 신고가액 |
| 국가재정 | [열린재정](https://www.openfiscaldata.go.kr) | 재정수입·총지출·재정수지·국가채무 등 API |
| 지도 경계 | [vuski/admdongkor](https://github.com/vuski/admdongkor), [오마이뉴스 선거구 지도](https://github.com/OhmyNews/2024_22_elec_map) | 통계청 SGIS 행정동 경계를 가공한 행정구역 자료와 국회의원 선거구 경계 |

자료별 공개 주기와 지원 기간이 다릅니다. 실제 수집 범위·건수·정제 기준·라이선스와 검증 기록은 [데이터 출처 문서](docs/DATA_SOURCES.md)에 정리했습니다. 서비스에서는 자료의 대상 기간과 수집 시각을 함께 표시합니다.

## 문서

- [설치·실행 안내](docs/INSTALL.md): 시스템·Python 의존성, OCR 실행 환경, 데이터 준비, 인증키, 로컬 실행과 검증.
- [데이터 출처와 수집본 기록](docs/DATA_SOURCES.md): 출처, 수집본 통계와 해석 기준.
- [시스템 설계](docs/ARCHITECTURE.md): 저장·발행·정정 계층과 데이터 모델.
- [기획·요구사항 기록](SPEC.md): 제품 범위와 설계 결정. 현재 실행 방법과 지원 상태는 설치 안내와 소스코드를 기준으로 확인.
- [서버 안내](robinhood-server/README.md) / [웹 안내](robinhood-web/README.md): 구성별 상세 설명.
- [운영 배포 안내](deploy/README.md): PostgreSQL 권한과 상시 실행 구성.
