# SPEC — Public spending reading room

Project name: **Robin Hood**. Current public service name: **나랏일보고서**.

Related files:
- [README.md](README.md): pages and counts.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): pipeline, site, entity mapping, per-screen calculations, next steps.
- [docs/data-sources.json](docs/data-sources.json): every source checked, with date and URL.
- [docs/expansion-candidates.json](docs/expansion-candidates.json): sources not yet collected.
- [docs/legal-notes.json](docs/legal-notes.json): 23 laws and rules behind the detection rules and publishing limits.
- [pipeline/rules.py](pipeline/rules.py): the 28 detection rules, each with purpose, fields, method, thresholds, laws, normal cases, false-positive risks and missing-data handling.

## 1. Purpose

**Origin.** The project started from the KOBINHOOD design brief (2026-10-21). Its goal:

> 시민들이 국회의원, 광역의원, 기초의원, 지방의회, 공공기관 등의 자금 사용 내역을 쉽게 확인하고, 공개된 데이터에서 일반적이지 않은 지출 패턴을 발견할 수 있도록 한다.

**What it is.** More than a spending-statistics site. It collects, normalizes and links public data scattered across many sources, then uses statistical comparison and regulatory checks to find spending that deserves a closer look. Detection results are not evidence of wrongdoing. Confirmed legal violations, audit findings, statistical outliers and plain data errors must stay strictly separate.

**The user's own framing** (from later messages):
- Track where the state's money goes, down to the shop, the way Toss showed card spending.
- Show where the state gets money and where it spends it.
- Show what politicians spend on, by category.
- Let people judge for themselves. The site never declares what is "excessive."
- People mostly want to know whether their own district's representatives are doing a good job.

**Audience.** Citizens first, mainly people checking their own area's representatives. Journalists and researchers second.

**Targets, by priority**

| # | Target | Status |
|---|---|---|
| 1 | National Assembly members: political funds and related expenses | Collected |
| 2 | Metropolitan council members (서울시의원 etc.) | Collected (Seoul) |
| 3 | Basic council members (구의원 etc.) | Collected (25 Seoul districts) |
| 4 | Councils as bodies: secretariat and shared council expenses | Collected (Seoul) |
| 5 | Public institutions: heads and operating expenses | Not started |

The MVP scope is National Assembly members plus Seoul local councils.

**What it is not.** It is not a verdict machine, a "bad politicians" ranking or a news outlet. It is a reading room: organized public records, with clear signs where a closer look might be useful.

## 2. Requirements (what the user asked for)

| # | Requirement | Status |
|---|---|---|
| R1 | Research every legally accessible data source as of October 2026. Separate verified from assumed. Record the check date and URL. Separate "data exists" from "can be collected automatically", and real fields from estimated ones. Never invent APIs or endpoints. | Done (`docs/data-sources.json`, `docs/expansion-candidates.json`) |
| R2 | Detection indicators for groups A (meals and expense budgets), B (spending patterns), C (political funds), D (contracts) and E (transparency): at least 15 rules, each with purpose, fields, formula, missing-data handling, laws, normal cases, false-positive risks, extra data needed, difficulty, and whether it can be built with public data. | Done: 28 rules (§6). D group and part of C3 not possible yet. |
| R3 | Data model with a raw layer kept unchanged and a separate normalized layer; every finding traceable to its source document. Handle: differing Excel columns, scanned PDFs and OCR, one shop under several names, same-name officials, party changes, role changes, duplicate rows across sources, linking cancellations and refunds, corrected source documents, missing values and OCR confidence, reprocessing after deletion or correction. | Done (`docs/ARCHITECTURE.md`) |
| R4 | Screens: official detail, merchant detail, finding detail, as listed in §7. Make clear what the data shows and what it does not. | Done in code; review/correction history open |
| R5 | Legal and reliability review: 정치자금법, 공직선거법, 업무추진비 집행 규칙, 회계관리 훈령, council disclosure ordinances, 개인정보 보호법, public-data reuse terms, information-disclosure rules, plus the six questions in the brief (republishing disclosed data, restricted fields, attribution to individuals, corrections, explaining repeated merchants, audit findings vs statistical outliers). | Done (`docs/legal-notes.json`) |
| R6 | MVP roadmap: collect and normalize, then basic analysis, then detection, then service (official page, merchant search, source per transaction, review and correction). | Phases 1–3 done; Phase 4 partly (review/correction open) |
| R7 | Originally static-only; superseded on 2026-10-31 by the explicit request for a server/job and web application. | Implemented: `robin-hood-server` (FastAPI, PostgreSQL storage, collector CLI) and `robin-hood-web` (React, TypeScript, Vite). Legacy `site/` remains usable. |
| R8 | Map-based regional view of representatives' spending, so people can check their own district. | Done (우리 동네 + map). The design adds a 읍·면·동 → 선거구 step. |
| R9 | Keep finding more data to collect. | Ongoing (§5) |
| R10 | Use an OCR tool for scanned PDFs. | Done (Apple Vision, `pipeline/ocr.py`, `pipeline/parse_ocr.py`) |
| R11 | Manage API keys inside the project with SOPS, encrypted with GCP KMS. | Done (`credentials.yaml`) |
| R12 | Pre-collect all plenary vote records if there is no rate limit. | Done |
| R13 | Show where the state gets money and where it spends it. | Done (나라 살림). The design splits 결산, enacted budget and proposal into separate tabs. |
| R14 | Spending by category for National Assembly members and council members. | Done (정치인의 돈) |
| R15 | Show which shop each payment went to, Toss-style. | Done (merchant pages and search) |
| R16 | Let users judge. Build Top 10 boards for National Assembly members and local council members, places they commonly use, who spends the most, and other statistics. | Done (순위판) |
| R17 | Filter payments far above normal prices. Prompted by news of 이준석 의원 pointing out price gaps. | Done, using each shop's usual price per person. Market-price comparison is not possible (§8.5). |
| R18 | Asset rankings, asset composition, and the location and value of real estate. | Done for National Assembly members; local council members open |
| R19 | Review of an external UX critique. Points adopted: entry by my area; menu cut to 5; funding badge on every amount; rankings as comparisons with context; fictional or human-reviewed home example; separate budget tabs; member-page tabs; rules in a few groups; lighter mobile. Fixed during that review: source-format label and README counts. | Implemented in the new web; names are pseudonymous by default and amounts come from the collected dataset. |
| R20 | A data list with purposes for design work, and an English service description. | Done (this file) |
| R21 | Robin Hood is the project name only; the public service needs a different name. | Selected: 나랏일보고서. The project remains Robin Hood. Trademark and domain checks remain open. |
| R22 | Update the Pencil design (`robinhood.pen`) with these requirements. | Done |
| R23 | Use one example-data wireframe set, merge duplicate pages and group sections/pages on the canvas. | Done: 40 screens consolidated to 10 desktop + 2 mobile; five page sections plus orientation/components (§7). |
| R24 | Use NAVER Maps for 자주 결제한 장소. | SDK adapter implemented with `ncpKeyId`, regional clusters, map/list sync and boundary-map fallback. Live authentication requires an application key and registered service URL; exact merchant coordinates remain unavailable. |
| R25 | State whether spending is monthly, annual, a selected-period total or a single transaction. | Reflected in scope bars, metric labels, ranking/table headers, merchant cards and desktop/mobile charts; definitions below. |
| R26 | Implement the agreed design as server/API/collector jobs and web; choose project naming. | Implemented as `robin-hood-server` and `robin-hood-web`. Public name remains 나랏일보고서. Periodic collection is an explicit worker command; no daemon or live schedule was installed. |
| R27 | Store service data in the existing main PostgreSQL and configure periodic update jobs. | Implemented: isolated `robin_hood` schema, JSONB/relations, COPY publication in one transaction, request-level repeatable reads, shared advisory lock, durable run history/schedule, retries, and Linux service definitions. Existing supported collector scope remains explicit. Operational connection and service activation await deployment configuration. |
| R28 | Use Codex only to correct extracted OCR wording/table text; preserve original documents and avoid PDF/image model input. | Implemented as an optional server-job stage: bounded text-only SDK calls, separate correction records, source/extraction hash checks, protected numerical/attribution fields, cached reviews, and normalization overlays. Raw/staging files are preserved; actual model execution awaits SDK/login configuration and activation. |

## 3. Principles and constraints

**Presentation**
1. **Highlight, don't accuse.** A flag means "worth a second look," never a violation. Only audits, investigations or courts confirm violations. The visual language is a highlighter pen, not a red alert.
2. **No scores or grades for people.** Rankings are raw amounts and counts within the same funding type, period and role. Each one shows the comparison group, n and the median. Detection findings are never turned into a per-person score.
3. **Never mix or add funding types.** Political funds, council expense budgets, shared council expenses, subsidies and contracts are separate accounting types. Political funds come mainly from donations; council expense budgets come from taxes.
4. **Every number is traceable** to its source document, format (OCR, PDF table, Excel), collection date and known limits.
5. **Say what the data does not show:** who actually paid or attended, the reason written in the receipts, OCR errors, and confirmed violations.
6. The UI is in Korean.

**Detection rules** (from the brief)
- Keep legal thresholds and statistical thresholds separate. Never present an arbitrary amount as a legal limit.
- Account for differences in role, term, region, accounting type and year.
- Skip a comparison when the sample is too small.
- Clean up duplicates, cancellations and refunds before adding anything up.
- Keep payer, user, attendee and responsible manager distinct.
- Present transaction-level patterns with their evidence.
- Don't compute per-person meal cost without a headcount.
- Don't call a schedule mismatch when no official schedule is public.
- Treat missing fields as violations only when disclosure rules require them.

**Attribution**
- Do not attribute shared council expenses (의회 공동경비) to every member personally.
- Never show public contracts as a person's own spending.
- Link same-name officials only when the match is unambiguous (by member code, then unique name, then party).

**Privacy**
- Mask individual payees.
- Publish no donor details (정치자금법 제42조⑤).
- Show property locations only down to 읍·면·동; never 지번, building name or unit.
- Attribute council spending to roles, never to private individuals.
- Publish no birthdates, phone numbers, emails, staff names or bios.

**Data honesty**
- Separate verified from assumed sources and fields.
- Check the original documents behind press OCR data where possible.
- Label each finding with the actual format of its source document.

**Security**
- API keys live only in the SOPS/GCP-KMS-encrypted `credentials.yaml`. Never print, log or commit a key.
- Per the 열린국회 terms, the key must not be shared or published.

**Licensing**
- KA-money: MIT.
- 국회공보: free to use.
- 열린국회: follow its terms.
- 정보공개센터 asset sheet: CC BY-NC-ND. Use it for local verification only; never publish or store it in the project.
- Newstapa data: copyrighted; don't use it without permission.

**Process**
- The user explicitly authorized repository creation and a pull request on 2026-11-01. Keep datasets, credentials, generated output and local runtime files out of version control.
- The site has not been published. Deciding to publish is the user's call, because it shows real politicians next to flags.

## 4. Data collected (in the pipeline and on the site)

| # | Dataset | Source | Coverage | Key fields | Caveats |
|---|---|---|---|---|---|
| 1 | National Assembly political fund spending (정치자금 지출) | KA-money (OhmyNews, Kyunghyang, Newstapa; MIT), OCR'd from 선관위 reports | 257,687 rows; 455 members (21st–22nd); 2023-01 to 2024-12 | date, payee, amount, 선관위 category, description | Secondary OCR data. No time and no headcount, so no per-person cost. Can't tell whether the member or staff paid. |
| 2 | Political fund income (정치자금 수입) | same | 455 members, 2023 and 2024 | 후원회 기부금, interest, carry-over, other | No donor-level data (by law). |
| 3 | Council expense spending (지방의회 업무추진비) | Each council's website: 2,616 PDFs and 1,288 XLSX files; scanned PDFs read with OCR | 174,815 rows. Seoul Metropolitan Council: 30,464 (2022-07 to 2026-09). All 25 Seoul district councils: 144,351; start dates vary from 2018 to 2025-06. | date, time (mostly), payee, amount, headcount (mostly), purpose, payment method, funding type (8 kinds), role | Disclosed by role, not by name. Role holders identified only for 관악, 마포 and 서울시의회 (99 people). |
| 4 | Legislative activity (열린국회 Open API) | 국회사무처; API key in SOPS | 299 current members (279 matched). Bills: 43,735 (21st: 23,655; 22nd: 20,080). Plenary votes on 5,183 bills (21st: 3,272; 22nd: 1,911). | party, district, committees, terms, bills led/co-sponsored and results, per-member votes, participation rate, votes that differed from the party | The key must not be shared, logged or published. |
| 5 | Assembly member assets (재산, 국회공보 제2026-54호) | 국회 홈페이지 PDF (free to use) | 287 members, as of 2025-12-31. 5,440 items, of which 2,100 are real estate. | net assets, 1-year change and valuation change, 11 asset groups, 고지거부, each property's relation/type/시·군·구/읍·면·동/area/filed value/value a year earlier/reason for change, source page | 신고가액 is not market value. Family members who refused disclosure are excluded. Three successor members have no political-fund link. |
| 6 | National finances (열린재정) | 기획재정부 Open API | Settled accounts 2014–2024. National tax by item 2013–2026. Spending by sector 2013–2025 (결산). By ministry: 2026 enacted budget and 2027 proposal. National debt 1997–2025. | revenue, spending, fiscal balance, debt, GDP ratio | 결산, enacted budget and proposal stay on separate tabs. |
| 7 | Maps | OhmyNews district maps; admdongkor 행정동 | 시·도, 256 시·군·구, 25 Seoul 구, 22nd districts (254), 21st districts (253), 행정동 polygons | boundaries | Can derive 읍·면·동 → 선거구 (verified for 마포갑/을). |
| 8 | Legal references | 국가법령정보센터 | 23 laws and rules | articles behind each rule | — |

**Derived data**
- 64,053 payees linked across sources (23,126 with a business number).
- 28 rules producing 4,705 flags (§6).
- 670 cross-file duplicates removed: 433,172 rows in the source files, 432,502 analyzed.
- Rankings, shared venues, and 313 price-gap payments (out of 29,657 checked meals).

## 5. Data we can collect next

| Priority | Candidate | Source / access | What it adds | Effort / blockers |
|---|---|---|---|---|
| 1 | KA-money 2012–2022 | GitHub, MIT, no key | Year-over-year trends; before/after elections | Low (file-name encoding quirk) |
| 2 | Earlier 국회공보 asset disclosures | 국회 홈페이지 PDFs | Asset trends per member | Low (same parser) |
| 3 | 서울시의원 and 구의원 assets | 서울시 공보 / 공직윤리시스템; 서울시보 | Asset boards for local councils | Medium (new PDF layouts) |
| 4 | Council overseas trip reports (공무국외출장) | Council sites, HTML/PDF | Who went where and at what cost; names are public | Medium |
| 5 | Other metropolitan councils: 경기 (XLSX), 부산 (XLSX, no time), 인천 (PDF) | Council sites, no key | Coverage beyond Seoul | Medium |
| 6 | Local council member lists and districts; 선관위 당선인 API | Council sites; data.go.kr (key) | 동 → district → "my 구의원" | Medium. The API returns birthdates and addresses, which must be dropped. |
| 7 | KA-money_addr 2018–2020 | GitHub, MIT | Payee 시·군·구: spent inside or outside the district | Low. Publish 시·군·구 only. |
| 8 | Council outside jobs (겸직현황) | Council sites | Overlap between outside jobs and payees (facts only) | Medium |
| 9 | Attendance (출석) | Only 부산 has a proper table so far | "Do they show up?" | Medium; sparse elsewhere |
| 10 | Executive-side expenses: 서울시 정보소통광장, 구청장 | Seoul and 구 sites, no API | Compare the executive and the council in the same city | High; must be a separate funding type |
| 11 | 지방재정365 local budgets | lofin365 | Local-government version of 나라 살림 | Unknown API |
| 12 | 나라장터 contracts | data.go.kr (key) | Contract concentration, split and changed contracts (rules D1–D3); public institutions (target 5) | Medium; separate module, never shown as personal spending |
| 13 | 감사원 and 권익위 findings | PDF/HTML | Confirmed violations, kept distinct from flags (rule D4) | High; manual |
| 14 | Council member pay (의정비) | Local notices | Context only | High; low value |

**Blocked or permission needed**
- **Newstapa asset and political-fund datasets:** copyrighted; needs permission.
- **정보공개센터 asset sheet:** CC BY-NC-ND. Use it for local verification only; never publish or store it in the project.
- **Original 선관위 political fund reports:** viewable for 6 months only, on paper. Only 선거비용 is online.
- **Members' official travel schedules:** not machine-readable, so the C3 schedule check can't be implemented.
- **Market-price comparison for goods:** only 4 of 13,108 council goods purchases list quantities.

## 6. Detection rules

Implemented: 28 rules producing 4,705 flags. The table shows their group on the site and which codes from the brief they cover.

| Site group | Rules | Flags | Brief codes covered |
|---|---|---|---|
| 법령 기준 대조 (regulatory) | 1인당 식사비 기준 초과; 심야(23–6시); 주말·공휴일; 업무추진비 현금 사용; 관할·인접 지역 밖 사용 | 927 | A1, A3, A5 |
| 통계 비교 (statistical) | 고액 식사 결제(정치자금); 특정 업소 반복 이용; 주말·공휴일 식사 비중; 임기 종료 직전 증가; 총선 직전 증가; 항목별로 유난히 큰 의원; 같은 직책보다 큰 업무추진비; 특정 월 집중; 상위 거래처 집중도; 목적이 불분명한 고액 용역·홍보비 | 984 | A1, A2, A3, B1, B2, B6, C1, C2 |
| 같은 패턴 반복 (exact match) | 같은 날 같은 업소 복수 결제; 같은 거래처 동일 금액 반복; 중복 거래 의심; 원거래 없는 취소·반환; 특정 업체 반복 용역·홍보; 같은 날 교통·주유 반복 | 1,755 | A4, B3, B4, B5, C1, C3 |
| 상호·내용 단어 (keyword) | 사용 제한 업종 의심 상호; 사적 경비와 겹치는 내역; 식대 분류와 업종 불일치; 착오·사적 사용 정정 기록 | 645 | A5, B5 |
| 공개·자료 품질 (disclosure) | 공개 누락·오첨부; 집행목적 구체성 부족; 공개 기간과 다른 날짜 | 394 | E1, E2, data quality |

**Not implemented**
- **C3 schedule check:** official travel schedules are not public.
- **D1–D3 contract rules:** need the 나라장터 API key and a separate contract module.
- **D4 audit history:** 감사원 and 권익위 results are unstructured PDF/HTML and need manual verification.

## 7. Screens

**Required by the brief**
- Official or role profiles show public basic information, funding types and periods, spending categories, monthly trends, assets and legislative records where collected.
- Merchant details show spending records, report-name counts, monthly trends, matching confidence and source transactions.
- Findings expose the rule, observed values, comparison basis, evidence, normal explanations, source quality and review state within the methods or transaction context.

**Web, current code** (`robin-hood-web/`)
- The grouped Pencil architecture is implemented as responsive routes and tab/filter states, backed by the collected data through `robin-hood-server`. See each package README for setup, API and limitations. The legacy static site retains its own routes and navigation.

**Canonical wireframes** (`robinhood.pen` in Pencil)
- One wireframe set uses pseudonymous example names with collected fields and snapshot values. There are no separate legacy, example-data or real-data page sets.
- The canvas has six top-level groups: an orientation/component group plus five page sections. The page count is **10 desktop + 2 mobile**, reduced from 40 by removing 28 redundant frames.
- Navigation: **내 지역 · 의원·정당 · 비교·장소 · 나라 살림 · 출처·방법**.
- Pages use stable labels P01–P10 and M01–M02. The Pencil controls remain static wireframes; the corresponding web tabs, filters, pagination and source links are implemented application interactions.

| Canvas section | Page | Contents and states |
| --- | --- | --- |
| 01 · 지역과 의원 | P01 · 홈 · 내 지역 | Region picker and staged maps: 전국 → 서울 → 마포구 → 동/국회 선거구. Regional representatives, council figures, a short role-spending ranking and routes to profiles, council records and places. |
| 01 · 지역과 의원 | P02 · 의원 · 정당 목록 | Member search, party/district/report filters, reporting-population metrics, one paginated list and links to profiles or comparison. |
| 01 · 지역과 의원 | P03 · 의원 프로필 | 한눈에 / 정치자금 / 신고재산 / 법안·표결 / 출처 tabs. Spending charts and compact examples expose transaction, income, property and bill/vote fields. Full category tables, property items and legislative records belong to these tabs rather than separate pages. Local-role profiles use the same information pattern where fields exist. |
| 01 · 지역과 의원 | P04 · 지방의회 | City/district council and region selectors, funding/period scope, coverage, role-holder cards, monthly/category charts and role × half-term records. The selected example is 마포구의회; 서울시의회 is another selector state rather than another screen. |
| 02 · 비교와 장소 | P05 · 비교 · 랭킹 | A shared comparison page for National Assembly members, councils and declared assets. Party, funding type, category and metric selectors replace separate party and category-ranking pages. The visible example is Democratic Party spending Top 10 with category/monthly charts. Price-per-person comparisons apply only where headcount exists. |
| 02 · 비교와 장소 | P06 · 장소 지도 | NAVER Maps integration surface with district clusters, region/map-type/zoom controls, search-this-area action, funding/period filters and payment-frequency cards. Shared-place and individual-report views are filter states. |
| 02 · 비교와 장소 | P07 · 장소 상세 | Retained payment count, net spending, refunds, report-name ranking, monthly counts, transaction rows, merchant matching and location limits. Council funding stays in a separate section. |
| 03 · 나라 살림 | P08 · 나라 살림 | Revenue, expenditure, integrated/managed balance, sectors and debt. Actuals, enacted budget and proposal are separate basis tabs. Tax-item and source details stay inside the page or link to the official document. |
| 04 · 기록과 출처 | P09 · 거래 상세 | One shared transaction template with 정치자금 / 의회 경비 modes. Common date, amount, purpose, payee, payment and source fields; mode-specific time/headcount/budget/role or funding-account/receipt fields. The visible example is a 330,000원 council record for 12 recorded people. |
| 04 · 기록과 출처 | P10 · 데이터 · 방법 | Collected-field inventory, missing-field coverage, funding/period and refund rules, source formats, rule groups and finding interpretation. Source-document and analysis-rule pages are consolidated here; evidence can expand in context. |
| 05 · 모바일 흐름 | M01 · 모바일 · 장소 지도 | Compact NAVER Maps surface with region/layer/zoom controls, search-this-area action and place cards in a bottom sheet. Same records and definitions as P06. |
| 05 · 모바일 흐름 | M02 · 모바일 · 장소 상세 | Same merchant detail structure as P07, arranged as stacked mobile sections with separate funding scopes. |

**Primary routes**
- 내 지역 → 의원·의회 → 내역 → 거래 상세 → original source.
- 의원 목록 or 비교·랭킹 → 의원 프로필 → the relevant profile tab.
- 장소 지도 → 장소 상세 → 거래 상세.
- Each record links to its source; P10 explains the source and calculation conventions.

**Data basis and state definitions**
- Monetary values and spending rankings display an aggregation type and explicit dates in the same block. Desktop scopes appear before the metrics; card labels, table headings and mobile sections repeat the relevant scope where needed. This is a labeling change; snapshot amounts and page count remain unchanged.
- Use these period definitions consistently: calendar-year council totals are `2024.01–12 · 연간 합계`; monthly averages state the denominator (`연간 집행액 ÷ 공개 12개월` in the Mapo example); monthly charts state the year, `각 월 합계` and the monetary/count unit; selected place data is `2023.01.01–2024.12.31 · 2년 합계`; transaction detail is `거래 1건` with the transaction date/time. A record appearing in a September disclosure is not the September total.
- Political-fund amounts use `2024년 제22대 보고분 합계` or `보고분 지출 합계` with the 2024.01–12 scope. They are report-subset totals, not an assertion of a member's complete calendar-year spending. The 제21대 2024 report is separate, and an individual may have records only for part of the year in the selected report. All 70,652 duplicate-excluded rows in the selected 제22대 report have 2024 transaction dates; charts group those recorded dates by month.
- Keep snapshot/stock measures distinct from spending flows: declared assets show their basis date, and national debt shows the year-end balance. Do not label either as monthly or annual spending. Incomplete disclosures show their actual covered months; do not extrapolate them to a full-year amount or replace missing periods with zero.
- Display names are consistent pseudonyms. Parties, regions, institutions, dates and amounts retain their collected labels and values. The canvas orientation explains the example-data convention once; individual pages retain concise reporting-scope and source notes. Source datasets are unchanged.
- Political-fund comparisons use `ka:2024-22`, exclude cross-file duplicates and include refunds: 301 positive-net reporting subjects, 70,652 transactions and 39,320,879,698원. The Democratic Party subset has 171 subjects. This is a reporting population, not a current-member list. Party attribution is linked to the 제22대 report, not current membership. Dates remain as recorded in the report.
- Council charts use 2024 `COUNCIL_OPERATION` only, exclude dates flagged outside the report period, and retain role × half-term attribution. Mapo has 916 transactions, 12 disclosed months and 107,890,640원; Seoul has 2,721 transactions and 488,906,234원. Role spending is not a person's total expenditure. Local member/constituency links and local assets remain incomplete; local-government revenue and settlements are not collected.
- The political-fund transaction mode retains funding account, payment method, receipt number, category provenance and source-row fields. Time and attendance are unpopulated. Receipt numbers do not establish possession of receipt images. The selected snapshot includes a 90,000원 error withdrawal, −90,000원 refund and separate 83,000원 payment; their net is 83,000원.
- The visible council transaction is `mapo-f0a850f38629-28`: 2024-09-03 17:42, 330,000원, 12 recorded people, credit card, budget item and role/term. 27,500원 per recorded person is derived by division. The role holder is linked separately from official council history and is not asserted to be the payer or attendee. Source: official PDF, row 28.
- Asset states retain previous/current category values and changes, relation, property kind, area, district/neighborhood, lease status, change reason, debt, crypto count, refusal state and source page. The profile example uses 2025-12-31 values published on 2026-03-26, page 662 of the source gazette. Reported values are not market prices; asset change is not personal income or investment return.
- Legislative states retain bill title/number/date/committee/outcome/official URL and vote counts, dates, agenda titles and individual choices. The snapshot was collected on 2026-10-24. Missing outcomes remain 미기재. Bill and vote datasets are not joined without a verified match.
- Place scope: political-fund hospitality in 2023–2024, separately from 2024 council-operation hospitality. Duplicate rows and completed cancellation/refund pairs are excluded from positive payment counts; net spending includes refunds. Matching uses existing chain, payment-platform and non-place filters. The snapshot contains 6,345 political-fund and 8,208 council merchant entities with positive net spending and retained payments. 영등포구 has 1,127 political-fund merchant entities and 14,334 retained payments. 여의도밥상 (pseudonym) has 424 retained payments, 79,713,893원 net spending and 132 report names.
- Store coordinates and verified street addresses are unavailable, so map markers are district clusters on real geography. Payment records do not establish actual visitors, attendees, present operation status, distance, ratings or public popularity. Merchant matching confidence is separate from location accuracy.
- NAVER Maps is the chosen basemap provider for P06/M01 and the P07 region preview. The current Pencil surface is explicitly a wireframe with real administrative-boundary overlays, not a captured NAVER basemap or a live SDK. The map controls, area re-search and card selection describe intended interactions. The page count remains 12.
- Whole-collection inventory after duplicate exclusion: 257,687 political-fund transactions, 174,815 council transactions across all funding types, 3,907 document records and 64,053 merchant entities. Council time is populated in 155,898 rows and headcount in 160,484. Presence does not establish correctness; raw purpose, inferred category, derived metric and parsing quality are distinguished.
- Reproducible snapshot scripts: `.artifacts/pencil-dashboard/build_snapshot.mjs`, `build_spots_snapshot.py` and `build_detail_snapshot.py`. Political-fund source references identify KA-money's secondary OCR-cleaned XLSX; official scans should be checked before quotation. The design remains a static snapshot and does not install periodic fetching or a Toss platform integration.

## 8. Decisions and considerations

Decisions made while we worked, with the reason behind each. Technical detail lives in `docs/ARCHITECTURE.md`; this section records the why.

### 8.1 Product and editorial

- **Readers judge, not the site.** When asked what looked "excessive", I first gave my own view. You redirected: "그런 판단들은 유저들이 할 수 있도록". So the site shows factual boards and statistics and never labels spending as excessive. That includes the copy, the colors and the order of things on a page.
- **Rankings are kept but framed as comparisons.** An external review warned that readers remember names and ranks more than disclaimers, and suggested demoting the Top 10 boards. You had asked for the boards directly, so they stay. Each board leads with its comparison basis: funding type, period, role, n and median. Every row shows "multiple of median". Council boards show how many months each council has disclosed. Whether the menu says "순위판" or "비교" is still open.
- **The home example must not accuse anyone.** The home page used to pick the latest "1인당 식사비 기준 초과" finding automatically, from 은평구의회, even though no person had reviewed it. Putting an unreviewed flag on the front page amounts to an editorial accusation. Use a fictional example labeled "예시", or only cases checked against the original document.
- **Highlighter, not red alerts.** The external review singled this out as a strength: it reads as "let's check together", not "here is the culprit".
- **Entry by area, not by free-text address.**
  - Free-text address search needs a geocoding API, and a static site would expose that API key.
  - Instead: pick a 시·군·구, then a 읍·면·동, using the boundary data we already have.
  - One 구 can have several National Assembly districts (마포구 → 마포갑 7 동, 마포을 9 동), so picking the 동 matters.
  - The national map stays as a secondary way in.
- **The menu has five areas:** 내 지역 · 의원·정당 · 비교·장소 · 나라 살림 · 출처·방법. The consolidated wireframes group profile details into tabs, comparison variants into filters and transaction funding types into a shared template. Political funds and council budgets retain separate scopes.
- **Funding badge wording.** The review suggested "정치자금 — 세금 아님". That isn't accurate: a member's political funds can include party support, and parties receive 국고보조금. The badge reads "후원금 중심 · 세금 예산 아님". Council money reads "세금 · 업무추진비".
- **Count wording.** README said 433,172 and the site said 432,502. Both were right but looked inconsistent. Always say: 원본 수록 433,172건 · 재수록 중복 670건 제외 · 분석 대상 432,502건.
- **Service name.**
  - The first request was "robin hood". Later: project name only, with a different public name.
  - The user selected **나랏일보고서** as the current public service name. Use it in the design and user-facing name labels; the project name stays **Robin Hood**.
  - The public name should stay calm and non-accusatory, cover more than spending (bills, votes, assets, national finances), and not sound like an official service.
  - "한 줄씩" was an unconfirmed placeholder, not the selected name. Replace the book/reading metaphors in interface copy with direct terms such as 지역, 메뉴, 거래, 내역, 원문 and 출처.
  - Trademark and domain checks haven't been done.
- **Mobile is a first-class target.** Measured at 390px wide:
  - The header is 153px tall.
  - The home page is about 7,155px long, roughly 8.5 screens.
  - On a member page, spending starts 4,391px down, after activity and assets.
  - Plans: tabs on member pages, rules folded into groups on home, a collapsible menu, and card rows for tables on phones.

### 8.2 Political funds (KA-money)

- **Secondary OCR data.** It is a press OCR cleanup of scanned 선관위 reports, so rows are kept as published and marked `ocr: true`. Business numbers with a 1-digit OCR error are merged only when the shop name also matches (116 merged). Quote nothing without checking the original PDF.
- **No time and no headcount.** So the 1인당 meal limit and the 심야 rule don't apply. The political-fund meal rule is statistical ("고액 식사 결제": large among the same year's meal payments), never a legal limit.
- **The member and the payer may differ.** The accounting officer reports these rows, so the data can't say whether the member or staff paid. Every member page says so.
- **Who counts as 21st-term.** Only people in the 2023 file count as 21st-term members. The 109 people found only in the 2024 first-half file are pre-candidate accounts for the 22nd election.
- **Income** is shown as totals by type only. Donor-level data is never published.
- **Files differ by year.** 2016, 2020 and 2024 each have two files (one per term), and column names change by year. Only 2023–2024 is loaded so far.

### 8.3 Local council expense data

- **Spending is attributed to roles.** Councils disclose by role (의장, 위원장, …), not by name. The spending subject is role × term half (전반기·후반기), so different people's spending never mixes. Names come only from the council's own election records, and only 관악, 마포 and 서울시의회 have them. Even with a name attached, spending stays role spending.
- **Personal names in the user column are dropped** from OCR'd files. A value is kept only when it matches a known role title.
- **Monthly averages count disclosed months only.** Dates flagged as outside the report period are excluded. Before this, one council showed a range of 1900-08 to 2052-06 because of typo dates.
- **서울시의회 is compared separately.** It is a metropolitan council with 112 seats, so it is never ranked against 구의회.
- **Councils started disclosing at different times.** 관악, 마포 and 금천 from 2018; most from 2022-07; 송파 from 2024-10; 동대문 from 2025-06. Show coverage next to every comparison, and treat missing months as disclosure gaps (E1), not as zero spending.
- **Jurisdiction.** The 훈령 allows spending in 시·군·구 that border the workplace. Neighbors that touch at only one point count too (관악–영등포). This conservative reading flags less.
- **Meal limit by date:** 1인 40,000원 until 2024-09-22, 50,000원 from 2024-09-23 (행정안전부훈령 제360호). Exceeding it is allowed when a reason is written, so a flag is never a violation.
- **심야** means 23:00–06:00. For example, 21:20 is not 심야.

### 8.4 Merchants

- **Shop identity:** business number first, then (normalized name, 시·군·구), then normalized name alone, which is low confidence. When a row has no address and that name appears in only one 시·군·구 in the same source, it is assigned there.
- **Chains are excluded from "places" boards** (`CHAIN_STORE`): coffee chains, convenience stores, taxis, rail and so on. They are also excluded from the 관할 밖 rule; that change removed 12 findings (4,717 → 4,705).
- **Payees that aren't restaurants** (ad agencies, travel agencies, consultancies and so on) are left out of restaurant statistics even when booked as meals (`NOT_FOOD_PLACE`).
- **Individuals are masked:**
  - business-number fields shaped like birthdates
  - payees under 인건비
  - phone numbers and emails in free text
  - the last digits of individual business numbers
- **Addresses** are published to 시·군·구 only.

### 8.5 Price gaps

- **No market-price comparison.**
  - Only 4 of 13,108 council goods purchases list a quantity, so a unit price can't be computed.
  - Comparing 나라장터 goods to market prices would need its item/price API plus market-price data, each with its own key.
  - Political funds have no headcount.
- **The baseline is the shop itself:** the median price per person of the other headcount-listed meals at the same restaurant. A payment is flagged when all of these hold:
  - it is at least 2× the shop's usual price per person;
  - it is at least 15,000원 more per person;
  - the shop has 8 or more meals on record;
  - the shop's usual price is at least 8,000원 per person.
- **Excluded:** 구내식당, 매점, 식권, 도시락, 케이터링, shopping and department stores, OCR rows, and anything outside the meal category.
- **Caveats shown on screen:**
  - Headcount is self-reported.
  - Course meals, takeaway gifts and extra orders vary at the same shop.
  - This is not a market-price comparison.

### 8.6 Assets

- **Source.** We read the 국회공보 original PDF ourselves, because it is free to use. The 정보공개센터 sheet (CC BY-NC-ND) is used only to verify. Newstapa data is copyrighted, so we don't use it.
- **Checks:** for each person, items add up to each subtotal, and subtotals minus debt equal the total. All 287 people also matched the 정보공개센터 sheet: totals, real-estate counts and real-estate sums. Parser pitfalls that were fixed:
  - rows split across pages (amounts printed twice)
  - repeated header rows
  - two units at one address merged by mistake
  - short 시·도 names ("서울시") read as overseas
- **What gets counted:**
  - 전세(임차)권 is filed under buildings but is a deposit on a rented place, so it is shown as "소유 아님" and kept out of owned real estate.
  - Composition ratios use assets before subtracting debt.
- **What the screen must say:**
  - 신고가액 is usually 공시가격 or the purchase price, not market value.
  - Unlisted shares may be filed at face value.
  - Family members who refused disclosure are excluded (131 members have at least one).
- **Linking members:** by unique 22nd-term name in the political-fund data. 13 people who left office after the June 2026 elections are linked this way. 3 successor proportional members have no political-fund data and appear by name and party only.
- **Scope:** National Assembly only for now. 서울시의원 assets are in 시 공보 or 공직윤리시스템, and 구의원 assets in 서울시보; each needs its own parser.

### 8.7 Legislative activity

- **Matching members.** Match by member code (MONA_CD) first. Fall back to the name only when it is unique, the subject isn't already linked to another code, and only one code with that name is unlinked. Same-name members are split by party. This fixed the new 박지원's bills and votes going to the old 박지원, and separated the two 김병욱.
- **Votes are collected in full.** Plenary vote records come one bill per call. With no rate limit, all of them were collected ahead of time: 3,272 bills for the 21st term, 1,911 for the 22nd.
- **Display.**
  - Participation = (찬성 + 반대 + 기권) / all vote records.
  - Every 반대 and 기권 is shown; other votes only for the latest 20.
  - Bill results are grouped as 가결, 대안반영, 임기만료 폐기, 철회, 부결 and 심사 중.

### 8.8 National finances

- **Units are 조원.** An earlier chart axis showed "20000000억".
- **결산, the enacted budget and the government proposal never share one chart.** On the 결산 tab, 부처별 points to the budget tabs, because ministry data exists only for the 2026 budget and the 2027 proposal.
- **Data years:** full-year actuals cover 2014–2024; sector 결산 runs to 2025.
- **Borrowing is not revenue.** It appears as national debt (D1, with GDP ratio).

### 8.9 Detection and data quality

- **The source-format label comes from the evidence documents.** It used to be a per-council default, so 912 findings from PDF-only councils were labeled "의회 공개 엑셀 원본".
- **Finding IDs are stable.** Each ID is a hash of rule, subject and evidence, so it stays the same across reruns while the evidence is unchanged.
- **Duplicates.** Rows republished in another file (670) are excluded from totals and flagged by B4. Receipt numbers and document IDs separate real repeats from loading duplicates.
- **Refunds and cancellations.** A negative row is paired with the original charge (same subject, payee and amount, from 180 days before to 7 days after) to get net spending. Unpaired refunds are flagged by B5.
- **Rerun detection after shared lists change.** The 4,717 → 4,705 change happened because the chain list was edited for the boards without rerunning detection.

### 8.10 Architecture and operations

- **Read API and legacy static site.** The new web reads an atomically published PostgreSQL dataset through FastAPI. The prior JS shards remain supported in `site/` for static/file use.
- **Size:** `site/data` is about 193 MB: 1,656 subject shards (96 MB) and 256 merchant shards (85 MB). This matters for hosting.
- **Path to a database.** If search or correction requests need a server, `data/normalized/` maps directly to PostgreSQL; the mapping table is in `docs/ARCHITECTURE.md`.
- **OCR runs on macOS only.** It uses Apple Vision at 300 dpi, cached in `data/ocr/`. Moving the pipeline to Linux would need another OCR engine.
- **Change detection.** Collectors record each file's sha256, and the pipeline is deterministic, so rerunning `run_all.sh` reproduces everything.
- **Browser checks** for this implementation used the connected Playwright browser with real API response snapshots; local shell browser launch and TCP binding were restricted. A reusable direct API/browser test is provided for normal environments.

### 8.11 Design file (`robinhood.pen`)

- **One canonical wireframe set.** The user requested consolidation instead of separate example and collected-data screens. The earlier 40 screens are now 12 canonical wireframes: P01–P10 desktop and M01–M02 mobile, grouped by section as described in §7. Person and merchant names are consistent pseudonyms; examples use collected fields and snapshot values. Twenty-eight redundant frames were removed. Original source files are unchanged.
- **Canvas hierarchy.** Top-level frames are 00 안내와 공통 요소, 01 지역과 의원, 02 비교와 장소, 03 나라 살림, 04 기록과 출처 and 05 모바일 흐름. Pages are nested inside their section frames; reusable components are kept under 00. Page and section counts exclude component definitions and in-page tabs.
- **Visible spending periods.** P01–P09 show scope bars for report totals, calendar-year totals, two-year selected totals or individual transactions. P04 separates annual amounts, disclosed-month averages and role/half-term totals. P06/M01 merchant card amounts explicitly say `2년 합계`; P07/M02 distinguish that total from the 2024 monthly count chart. P08 uses annual flow labels and a year-end debt date. Comparison headings and columns retain the selected report scope.
- **Place-map provider.** Use NAVER Cloud's standalone Maps product and Web Dynamic Map for the desktop and responsive mobile web surfaces. P06/M01 include region selection, map/layer controls, zoom and search-this-area; P07 includes a region-only map and NAVER region-view action. Preserve the live SDK's native logo and attribution area, including when the mobile sheet is open. The design's provider strip is a labeled wireframe placeholder. The integrated browser's NAVER Map capture timed out; no captured map asset is claimed. Product reference: [Maps overview](https://guide.ncloud-docs.com/docs/application-maps-overview), [Dynamic Map guide](https://guide.ncloud-docs.com/docs/application-maps-dynamic-sdk-vpc).
- **Map integration state.** The web SDK adapter is implemented; no NAVER account/application or key was created and live authentication has not been verified. Configure a Maps application with the web service URL registered: [Application registration](https://guide.ncloud-docs.com/docs/application-maps-app-vpc). The adapter uses `ncpKeyId` and keeps the SDK attribution. With no key or a loading/authentication failure it shows actual administrative boundaries. Regional representative coordinates were added to the boundary export; these are not merchant coordinates. Geocoding still requires verified addresses. Do not search fictional names as real places or turn district-level location into precise store pins.
- **Fixed errors in the first design:**
  - political-fund rows showed headcount and per-person cost
  - the political-fund source was labeled PDF
  - 21:20 was flagged as 심야
  - the asset page left out amounts and ratios, which you had explicitly asked for
- **Pencil's layout check** reported clipping on several new screens. Screenshots showed no problem, so that report is treated as a tool quirk.

### 8.12 OCR text correction

- The collection job calls a text-only Codex correction stage after OCR parsing and before normalization. The optional SDK uses an existing ChatGPT login and refuses API-key authentication. It runs in an empty read-only ephemeral workspace; the application passes table text, not PDF/image inputs, source URLs or paths.
- Raw source files and `data/staging/*_ocr.jsonl` are not rewritten. PostgreSQL migration 002 stores correction records separately; offline mode uses a separate audit SQLite file. Verified overlays affect derived normalization and are labeled in transaction details.
- Only bounded text edits and text-column moves are automatically applied. Amounts, dates/times, attendees, funding, role and address changes remain pending. Digits and row counts are preserved, and duplicate detection uses the original extracted wording. OCR confidence is not upgraded after a text correction.
- Fingerprints include source hash, extracted rows, prompt and model configuration. Completed unchanged batches are reused. Default limits: 5 batches/run, 40 rows/batch, 20,000 input characters and 120 seconds/call. The initial inventory was 117 documents, 5,614 rows and 203 batches, with a maximum payload of 8,587 characters and zero unverified source hashes.
- The scope is the existing local council OCR staging output. KA-money secondary OCR workbooks and documents with no extracted rows are outside this first stage. Unresolved issues, protected-field proposals and over-limit inputs are retained for review.
- Tests exercise immutable originals, stale/tampered correction rejection, no API-key fallback, read-only text-only SDK requests, bounded calls, timeout interruption and source-preserving normalization. Real model calls have not been run; no background AI processing was activated.

## 9. Current state

- **Pipeline:** Python in `pipeline/`. Run everything with `pipeline/run_all.sh`. Scanned PDFs are read with Apple Vision OCR (`pipeline/ocr.py`). Tests in `tests/` (36 passing).
- **Web/API:** React·TypeScript in `robin-hood-web`, FastAPI in `robin-hood-server`; actual normalized records are loaded into PostgreSQL through atomic COPY publication (SQLite is offline development/scratch only). The API also serves the production web build. Legacy `site/` remains available for static/file use.
- **Credentials:** `credentials.yaml`, encrypted with SOPS + GCP KMS.
- **Design:** one grouped Pencil wireframe set, 10 desktop + 2 mobile, implemented as ten responsive page types with tabs and filters. Default display names are pseudonymous; amounts, dates and source fields are collected data.
- **Collection:** CLI `migrate`, `index`, `collect`, `collect --no-fetch`, `run-due`, `ocr-correct --plan`, and `worker --interval-hours 24`. A shared lock prevents concurrent writers. Failed runs keep the previous published database. PostgreSQL stores run history and next-run timing; retries are 1/5/15 minutes and a restart preserves the schedule. Systemd services are provided but not activated.
- **Validation:** 57 backend tests cover isolated data, atomic publishing, durable schedules, bounded retries, timeout handling and reconciliation with the collection. Three live PostgreSQL integration tests require TEST_POSTGRES_URL and are skipped without it. An additional PostgreSQL 17.5 PGlite engine smoke check verifies 18 API paths, JSONB/foreign keys, rollback and shared job state; 36 pipeline tests pass, as do frontend typecheck/build/format checks. Browser checks use actual API response snapshots because this execution sandbox prohibits binding localhost ports and launching a browser process from the shell. The connected browser verified desktop/mobile pages and interactions; live NAVER authentication remains unverified. The reusable E2E script supports an in-process API or an existing server and still needs a normal environment where Playwright can launch a browser.

## 10. Open items

- **Name verification:** the current public service name is "나랏일보고서"; trademark and domain checks remain open. The project stays "Robin Hood".
- **Map setup and coverage:** register a NAVER Maps application and web URL, set the public key ID, and verify live SDK behavior. Precise merchant markers wait for verified addresses and coordinates. The current home picker is 시·도 → 서울 시·군·구 → 국회 선거구; 읍·면·동 selection and local councils outside Seoul remain open.
- **Review and correction (Phase 4):**
  - Check a random sample of 100 KA-money findings against the original PDFs and record false-positive rates per rule in `data/reviews.json` (currently empty).
  - Fill the review history that finding pages already display. Today every page says "아직 사람이 검토한 기록이 없습니다".
  - Publish a correction channel once an operator is decided.
- **Coverage:** local council assets; KA-money 2012–2022; other metropolitan councils; public institutions (target 5); the contract module (D1–D3); audit findings (D4).
- **Publishing:** the user decides whether and where to publish.
