# 나랏일보고서 · robinhood

나랏일보고서는 국회의원 정치자금, 지방의회 경비, 신고재산·의정활동, 국가재정 공개자료를 기간·재원·출처별로 살펴보는 대시보드입니다.
지역 지도에서 내 지역 의원과 의회를 찾고, 지출 순위와 그래프에서 개별 거래와 근거 문서까지 확인할 수 있습니다.

[설치·실행 안내](docs/INSTALL.md) · [데이터 출처와 수집본 기록](docs/DATA_SOURCES.md) · [운영 배포 안내](deploy/README.md)

## 제공하는 정보

- 내 지역 의원·의회와 의원·정당별 지출 항목, 기간별 변화와 순위.
- 의원·정당의 지출·신고재산·정치자금 수입 Top 10, 자산·채무 종류별 순위, 연간 재산 증가·감소와 자산 구성 비중, 정당별 순재산 중앙값과 재산 Top 10.
- 자주 결제한 장소, 거래 상세와 원문 근거.
- 신고재산, 법안·표결, 국가 재정의 수입·지출·수지.
- 자료의 수집 시각, 대상 기간, 출처와 분석 기준.

금액은 같은 기간과 재원 안에서 비교합니다.
공동경비는 의회나 위원회의 지출로 표시합니다.
통계 비교에서 표시한 거래는 원자료를 더 살펴볼 대상입니다.
위반 여부는 통계만으로 판단할 수 없습니다.
인물과 상호는 공개자료의 원래 이름으로 표시하고, 개인 수령인과 개인사업자 번호는 가립니다.

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

수집 worker는 공개자료 원본과 파싱·정규화 결과를 파일로 보관합니다.
OCR 문구를 정정할 때는 원문을 보존하고 수정 전후 내용과 근거를 따로 기록합니다.
검증한 조회 데이터는 PostgreSQL에 반영합니다.
적재에 실패하면 API는 이전에 발행한 자료를 계속 제공합니다.

React 웹은 사용자가 고른 지역·기간·정당을 `/api/v1/`에 전달합니다.
FastAPI가 DB에서 해당 자료를 조회·집계해 JSON으로 반환하면 웹이 그 결과를 표시합니다.
DB를 갱신하면 웹을 다시 빌드하지 않아도 다음 요청부터 새 자료를 볼 수 있습니다.
운영에서는 PostgreSQL을 사용하고 로컬 개발에서는 SQLite도 쓸 수 있습니다.

| 구성 | 역할 |
|---|---|
| `robinhood-web/` | React·TypeScript 웹 대시보드 |
| `robinhood-server/` | FastAPI 조회 API, 수집 worker, DB 반영 |
| `pipeline/` | 자료 수집, 파싱·OCR, 정규화와 분석 |
| `data/` | 원본과 중간·정규화 파일을 보관하는 별도 데이터 볼륨 |
| `site/` | 기존 정적 사이트 |

`site/`는 가공한 자료를 정적 파일로 제공합니다.
React 웹은 API로 자료를 조회하므로 서버 worker는 정적 사이트 빌드를 건너뜁니다.

최초 배포 때 원자료를 수집해 데이터 볼륨과 DB를 채우고, 이후 배포에서는 둘 다 보존한 채 주기적으로 갱신합니다.
데이터·로컬 DB·캐시는 Git에서 제외합니다.
저장소에는 SOPS 암호문 `credentials.yaml`과 KMS 설정 `.sops.yaml`을 두고, 평문 키와 인증 파일은 실행 환경에서 제공합니다.

스캔 PDF는 macOS에서 Apple Vision, Linux에서 Tesseract로 읽습니다.
설치 방법과 금액 검증 기준은 [OCR 실행 환경](docs/INSTALL.md#ocr-실행-환경)에 정리했습니다.

## 데이터 출처

| 자료 | 가져오는 곳 | 수집 내용 |
|---|---|---|
| 국회의원 정치자금 | [오마이뉴스·경향신문·뉴스타파 공동 KA-money](https://github.com/OhmyNews/KA-money) | 2023년부터 발행된 회계보고 XLSX(2025년 포함). 선관위 원문을 OCR로 변환한 2차 자료 |
| 지방의회 경비·직책 보유자 | [서울특별시의회](https://www.smc.seoul.kr/board/BoardList.do?boardTypeId=158&menuId=001007013001)와 [관악구의회](https://www.ga21c.seoul.kr/kr/costBBS.do)·[마포구의회](https://council.mapo.seoul.kr/kr/news/bbsCost.do) 등 서울 25개 구의회의 공식 홈페이지 | 업무추진비·의정운영공통경비의 PDF·엑셀, 공식 직책 선출 기록 |
| 의원 인적사항·법안·표결 | [국회사무처 열린국회정보](https://open.assembly.go.kr) | 공적 의원 정보, 대표발의 법률안, 본회의 표결 API |
| 신고재산 | [국회공보 정기재산공개](https://www.assembly.go.kr/portal/cnts/cntsNamgzn/gongbo.do) | 정기공개 PDF의 재산 항목과 신고가액. [공직윤리시스템](https://www.peti.go.kr/peOptpListVie.do)의 수시공개 등록기준일·공개일을 해당 날짜 국회공보의 총계와 연결 |
| 국가재정 | [열린재정](https://www.openfiscaldata.go.kr) | 재정수입·총지출·재정수지·국가채무 등 API |
| 지도 경계 | [vuski/admdongkor](https://github.com/vuski/admdongkor), [오마이뉴스 선거구 지도](https://github.com/OhmyNews/2024_22_elec_map) | 통계청 SGIS 행정동 경계를 가공한 행정구역 자료와 국회의원 선거구 경계 |

자료별 공개 주기와 지원 기간이 다릅니다.
실제 수집 범위·건수·정제 기준·라이선스와 검증 기록은 [데이터 출처 문서](docs/DATA_SOURCES.md)에 정리했습니다.
서비스에서는 자료의 대상 기간과 수집 시각을 함께 표시합니다.

## 문서

- [설치·실행 안내](docs/INSTALL.md): 시스템·Python 의존성, OCR 실행 환경, 데이터 준비, 인증키, 로컬 실행과 검증.
- [데이터 출처와 수집본 기록](docs/DATA_SOURCES.md): 출처, 수집본 통계와 해석 기준.
- [시스템 설계](docs/ARCHITECTURE.md): 저장·발행·정정 계층과 데이터 모델.
- [기획·요구사항 기록](SPEC.md)에는 제품 범위와 설계 결정이 있습니다.
  현재 실행 방법은 설치 안내에서, 실제 지원 범위는 소스코드에서 확인합니다.
- [서버 안내](robinhood-server/README.md) / [웹 안내](robinhood-web/README.md): 구성별 상세 설명.
- [운영 배포 안내](deploy/README.md): PostgreSQL 권한과 상시 실행 구성.
