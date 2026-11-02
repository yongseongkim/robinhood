import { useState } from "react";
import { query, useMeta, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, percent, shortWon, won } from "../format";
import {
  Bars,
  Empty,
  External,
  KeyValues,
  MonthlyChart,
  Notice,
  PageHeader,
  Pagination,
  Panel,
  ReportControls,
  reportDates,
  ResourceState,
  ScopeBar,
  SearchForm,
  Section,
  Select,
  SourceNote,
  Stat,
  Tabs,
  Transactions,
} from "../components/ui";
import type { Document, Profile as ProfileData } from "../types";

function DocumentCard({ id }: { id?: string }) {
  const resource = useResource<Document>(
    id ? "documents/" + encodeURIComponent(id) : null,
  );
  if (!id) return <Empty>선택한 범위에 연결된 거래 문서가 없습니다.</Empty>;
  if (!resource.data) return <ResourceState {...resource} />;
  const d = resource.data;
  return (
    <Panel title="출처 문서" description={d.publisher}>
      <h3>{d.title}</h3>
      <KeyValues
        rows={[
          ["형식", d.format],
          ["대상 기간", d.period],
          ["수집일", d.fetched_at?.slice(0, 10)],
        ]}
      />
      <External url={d.url}>
        {d.format.includes("OCR") ? "정제자료 확인" : "공식 문서 확인"}
      </External>
      {d.origin_note && <p className="caption">{d.origin_note}</p>}
    </Panel>
  );
}

export function Profile({ id }: { id: string }) {
  const { params } = useLocation();
  const meta = useMeta();
  const report = params.get("report") || "ka:2024-22",
    year = params.get("year") || "2024",
    funding = params.get("fundingType") || "COUNCIL_OPERATION";
  const resource = useResource<ProfileData>(
    "subjects/" +
      encodeURIComponent(id) +
      "?" +
      query({
        report,
        year,
        fundingType: funding,
        page: params.get("page") || 1,
        ...reportDates(params),
      }),
  );
  const data = resource.data;
  const tab = params.get("tab") || "overview";
  const [billQuery, setBillQuery] = useState("");
  if (!data) return <ResourceState {...resource} />;
  const leg = data.subject.type === "LEGISLATOR";
  const age = report.includes("2023") || report.endsWith("-21") ? "21" : "22";
  const bills = data.activity?.bills[age],
    votes = data.activity?.votes[age];
  const asset = data.assets;
  const preview = data.transactions.rows[0];
  const showMoney = tab === "money";
  const current = (next: string) => changeFilters({ tab: next, page: "" });
  return (
    <div className="page stack">
      <PageHeader
        title={data.subject.name}
        context={leg ? "의원 프로필" : "직책 프로필"}
        description={[
          data.subject.district || data.subject.org,
          data.subject.party,
          data.subject.role,
          data.subject.term,
          data.activity?.committees,
          data.activity?.reelection,
        ]
          .filter(Boolean)
          .join(" · ")}
      />
      <Tabs
        items={[
          { value: "overview", label: "한눈에" },
          { value: "money", label: leg ? "정치자금" : "직책 경비" },
          { value: "assets", label: "신고재산" },
          { value: "activity", label: "법안·표결" },
          { value: "sources", label: "출처" },
        ]}
        value={tab}
        onChange={current}
      />
      <div className="filters">
        {leg ? (
          <ReportControls params={params} />
        ) : (
          <>
            <Select
              label="집계 연도"
              value={year}
              options={Array.from({ length: 9 }, (_, i) => ({
                value: String(2026 - i),
                label: 2026 - i + "년",
              }))}
              onChange={(year) => changeFilters({ year })}
            />
            <Select
              label="경비 재원"
              value={funding}
              options={Object.entries(meta.fundingTypes)
                .filter(([f]) => f !== "POLITICAL_FUND")
                .map(([value, f]) => ({ value, label: f.label }))}
              onChange={(fundingType) => changeFilters({ fundingType })}
            />
          </>
        )}
      </div>
      {(tab === "overview" || tab === "money") && (
        <>
          <ScopeBar scope={data.scope} />
          <div className="metrics">
            <Stat
              accent
              label={leg ? "보고분 정치자금 지출" : "선택 기간 직책 경비"}
              value={shortWon(data.summary.amount)}
              exact={data.summary.amount}
              detail={
                data.scope.label + " · " + count(data.summary.count) + "건"
              }
            />
            <Stat
              label="신고 순재산"
              value={shortWon(asset?.total.cur)}
              exact={asset?.total.cur}
              detail={
                asset ? asset.source.basis + " 기준" : "현재 수집 자료와 미연결"
              }
            />
            <Stat
              label="대표발의"
              value={bills ? count(bills.lead) + "건" : "미연결"}
              detail={"제" + age + "대 · 수집본 기준"}
            />
            <Stat
              label="본회의 표결 참여"
              value={percent(votes?.participation)}
              detail="찬성·반대·기권 / 전체 표결"
            />
          </div>
          {!leg && (
            <Notice>
              {data.subject.attribution ||
                "개인의 전체 지출이 아니라 해당 직책에 편성된 경비입니다."}
            </Notice>
          )}
          <div className="two-columns">
            <Panel title="항목별 지출 합계" description={data.scope.label}>
              <Bars
                rows={data.categories}
                total={data.summary.amount}
                color={leg ? "blue" : "green"}
              />
            </Panel>
            <Panel
              title="월별 지출 추이"
              description={
                data.scope.start.slice(0, 4) + "년 · 선택 범위의 각 월 합계"
              }
            >
              <MonthlyChart data={data.monthly} />
            </Panel>
          </div>
        </>
      )}
      {tab === "overview" && (
        <div className="three-columns">
          <Panel
            title={leg ? "정치자금" : "직책 경비"}
            description={data.scope.label}
          >
            {preview ? (
              <>
                <div className="preview-amount">
                  단건 지출 {won(preview.amount)}
                </div>
                <p>
                  {preview.payee} · {preview.description}
                </p>
                <p className="caption">
                  {preview.date} · {preview.payment || "결제수단 미기재"}
                </p>
                <Link
                  className="text-link"
                  href={"/transactions/" + preview.id}
                >
                  거래 한 건 확인 →
                </Link>
              </>
            ) : (
              <Empty />
            )}
            <button className="button-link" onClick={() => current("money")}>
              지출 내역 보기 →
            </button>
          </Panel>
          <Panel
            title="신고재산"
            description={
              asset ? asset.source.basis + " 기준" : "수집 자료와 미연결"
            }
          >
            {asset ? (
              <>
                <KeyValues
                  rows={[
                    [
                      "전년 → 당년",
                      shortWon(asset.total.prev) +
                        " → " +
                        shortWon(asset.total.cur),
                    ],
                    ["1년 증감", won(asset.total.change)],
                  ]}
                />
                <p className="caption">
                  신고가액은 시세와 다를 수 있습니다. 가족 신고분과 정치자금
                  계좌가 포함됩니다.
                </p>
                <button
                  className="button-link"
                  onClick={() => current("assets")}
                >
                  재산 항목 보기 →
                </button>
              </>
            ) : (
              <Empty>이 인물의 재산 자료는 아직 연결되지 않았습니다.</Empty>
            )}
          </Panel>
          <Panel
            title="법안·표결"
            description={"제" + age + "대 · 수집본 기준"}
          >
            {bills ? (
              <>
                <p>
                  대표발의 {count(bills.lead)} · 공동발의 {count(bills.co)}
                </p>
                {bills.list[0] && (
                  <>
                    <h3>{bills.list[0][1]}</h3>
                    <p className="caption">
                      의안 {bills.list[0][0]} · {bills.list[0][3]}
                    </p>
                    <p className="caption">
                      처리 결과: {bills.list[0][4] || "수집 필드 미기재"}
                    </p>
                  </>
                )}
                <button
                  className="button-link"
                  onClick={() => current("activity")}
                >
                  법안·표결 내역 보기 →
                </button>
              </>
            ) : (
              <Empty>지방의회 의정활동은 아직 연결되지 않았습니다.</Empty>
            )}
          </Panel>
        </div>
      )}
      {showMoney && (
        <>
          <Section
            title="거래 내역"
            description="표의 금액은 각 거래 1건입니다. 취소·반환은 음수로 표시합니다."
          >
            <Transactions rows={data.transactions.rows} />
            <Pagination
              {...data.transactions}
              onChange={(page) => changeFilters({ page })}
            />
          </Section>
          {data.income.length > 0 && (
            <Panel
              title="정치자금 수입 유형"
              description={
                data.incomeYear +
                "년 수입 항목별 합계 · 지출 보고분과 범위가 다를 수 있음"
              }
            >
              <Bars
                rows={data.income.sort((a, b) => b.amount - a.amount)}
                color="green"
              />
              <Notice>
                이월·누계 항목은 중복 가능성이 있어 별도로 둡니다. 잔액이나 개인
                이익을 계산하지 않습니다.
              </Notice>
              <details>
                <summary>이월·누계 수록값 확인</summary>
                <KeyValues
                  rows={Object.entries(data.incomeCarry).map(([k, v]) => [
                    k,
                    won(v),
                  ])}
                />
              </details>
            </Panel>
          )}
        </>
      )}
      {tab === "assets" &&
        (asset ? (
          <>
            <SourceNote>
              {asset.source.basis} 기준 · {asset.source.published} 공개 ·
              신고가액 · 가족 신고분 포함
            </SourceNote>
            <div className="metrics">
              <Stat
                accent
                label="당년 신고 순재산"
                value={shortWon(asset.total.cur)}
                exact={asset.total.cur}
                detail={asset.source.basis + " 기준"}
              />
              <Stat
                label="전년 신고액"
                value={shortWon(asset.total.prev)}
                exact={asset.total.prev}
              />
              <Stat
                label="1년 증감"
                value={shortWon(asset.total.change)}
                exact={asset.total.change}
              />
              <Stat
                label="가액변동분"
                value={shortWon(asset.total.valuation)}
                exact={asset.total.valuation}
              />
            </div>
            <Section title="종류별 신고가액 비교">
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>분류</th>
                      <th className="right">전년 신고액</th>
                      <th className="right">당년 신고액</th>
                      <th className="right">변화</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(asset.cats).map(([name, v]) => (
                      <tr key={name}>
                        <td>{name}</td>
                        <td className="right numeric">{won(v.prev)}</td>
                        <td className="right numeric">{won(v.cur)}</td>
                        <td className="right numeric">{won(v.cur - v.prev)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
            <Section title="부동산 항목">
              <div className="two-columns">
                {asset.realestate.map((v, i) => (
                  <Panel
                    key={i}
                    title={v.kind}
                    description={v.relation + " 신고분"}
                  >
                    <KeyValues
                      rows={[
                        ["소재지", [v.sido, v.sgg, v.emd].join(" ")],
                        ["면적", v.area.join(" · ")],
                        ["권리", v.lease ? "전세·임차권" : "소유"],
                        ["전년 → 당년", won(v.prev) + " → " + won(v.cur)],
                        ["변동 사유", v.reason || "미기재"],
                      ]}
                    />
                  </Panel>
                ))}
              </div>
            </Section>
            <SourceNote>
              <External url={asset.source.url}>{asset.source.title}</External> ·{" "}
              {asset.page}쪽. 고지거부:{" "}
              {asset.refused.length
                ? asset.refused.join(" · ")
                : "수집 결과 표기 없음"}
              . 재산 증가액은 소득이나 수익률이 아닙니다.
            </SourceNote>
          </>
        ) : (
          <Empty>
            이 인물에 연결된 신고재산 자료가 없습니다. 지방의원 재산은 아직
            수집하지 않았습니다.
          </Empty>
        ))}
      {tab === "activity" &&
        (data.activity ? (
          <>
            <Tabs
              value={params.get("activity") || "bills"}
              onChange={(activity) => changeFilters({ activity })}
              items={[
                { value: "bills", label: "대표발의 법안" },
                { value: "votes", label: "본회의 표결" },
              ]}
            />
            {(params.get("activity") || "bills") === "bills" ? (
              <Section
                title={"대표발의 " + count(bills?.lead) + "건"}
                description={
                  "공동발의 " +
                  count(bills?.co) +
                  "건은 별도 집계 · 제" +
                  age +
                  "대"
                }
              >
                <SearchForm
                  value={billQuery}
                  placeholder="법안명 검색"
                  onSearch={setBillQuery}
                />
                {bills?.list
                  .filter((b) => b[1].includes(billQuery))
                  .map((b) => (
                    <Panel
                      key={b[0]}
                      title={b[1]}
                      description={"의안번호 " + b[0]}
                    >
                      <div className="record-meta">
                        {b[3]} · {b[2]} · 처리 결과: {b[4] || "미기재"}
                      </div>
                      <External url={b[5]}>국회 의안정보에서 확인</External>
                    </Panel>
                  ))}
                {!bills?.list.length && (
                  <Empty>선택한 대수의 대표발의 자료가 없습니다.</Empty>
                )}
              </Section>
            ) : votes ? (
              <>
                <div className="metrics">
                  {Object.entries(votes.counts).map(([name, value], i) => (
                    <Stat
                      key={name}
                      label={name}
                      value={count(value) + "건"}
                      accent={i === 0}
                      detail={
                        "제" + age + "대 · 전체 " + count(votes.total) + "건"
                      }
                    />
                  ))}
                </div>
                <Notice>
                  참여율은 (찬성+반대+기권) ÷ 전체 표결입니다. 불참 사유나
                  위원회 출석 여부를 나타내지 않습니다.
                </Notice>
                {[
                  ["최근 표결 기록", votes.recent],
                  ["반대·기권 기록", votes.dissent],
                ].map(([title, list]) => (
                  <Section
                    key={String(title)}
                    title={String(title)}
                    description="표결 날짜 · 안건명 · 선택"
                  >
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>표결일</th>
                            <th>안건</th>
                            <th>선택</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(list as [string, string, string][]).map((r, i) => (
                            <tr key={i}>
                              <td>{r[0]}</td>
                              <td>{r[1]}</td>
                              <td>{r[2]}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Section>
                ))}
              </>
            ) : (
              <Empty>선택한 대수의 표결 자료가 없습니다.</Empty>
            )}
            <SourceNote>
              열린국회 수집본 · {data.activity.fetchedAt?.slice(0, 10)}. 처리
              결과가 비어 있으면 미기재로 표시합니다. 법안 목록과 표결 기록을
              임의로 연결하지 않습니다.
            </SourceNote>
          </>
        ) : (
          <Empty>현재 수집한 의정활동 자료와 연결되지 않았습니다.</Empty>
        ))}
      {tab === "sources" && (
        <>
          <DocumentCard id={leg ? report : preview?.docId} />
          {asset && (
            <Panel title="재산 출처" description={asset.source.basis + " 기준"}>
              <External url={asset.source.url}>
                {asset.source.title} · {asset.page}쪽
              </External>
            </Panel>
          )}
          {data.subject.holders.length > 0 && (
            <Section title="직책 보유자 확인 근거">
              {data.subject.holders.map((h, i) => (
                <Panel
                  title={h.name}
                  description={h.start + "–" + h.end}
                  key={i}
                >
                  <External url={h.sourceUrl}>
                    {h.sourceTitle || "의회 공식 연혁"}
                  </External>
                </Panel>
              ))}
            </Section>
          )}
        </>
      )}
      <SourceNote>
        {data.scope.note}{" "}
        {data.subject.attribution ||
          "회계 보고 명의와 실제 결제·참석자는 다를 수 있습니다."}
      </SourceNote>
    </div>
  );
}
