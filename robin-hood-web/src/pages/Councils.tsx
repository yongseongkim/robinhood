import { query, useMeta, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, shortWon, won } from "../format";
import {
  Bars,
  ButtonLink,
  Empty,
  External,
  MonthlyChart,
  PageHeader,
  Panel,
  ResourceState,
  ScopeBar,
  Section,
  Select,
  SourceNote,
  Stat,
  Transactions,
} from "../components/ui";
import type { Council } from "../types";

export function Councils() {
  const meta = useMeta();
  const { params } = useLocation();
  const council = params.get("council") || "mapo",
    year = params.get("year") || "2024",
    funding = params.get("fundingType") || "COUNCIL_OPERATION";
  const resource = useResource<Council>(
    "councils/" +
      encodeURIComponent(council) +
      "?" +
      query({ year, fundingType: funding }),
  );
  const data = resource.data;
  const available = Object.entries(meta.fundingTypes).filter(
    ([key]) => key !== "POLITICAL_FUND",
  );
  return (
    <div className="page stack">
      <PageHeader
        title="지방의회 · 직책 경비"
        context="지역과 의원"
        description="의회 공개 자료를 직책·반기·재원별로 확인합니다."
      />
      <div className="filters">
        <Select
          label="지방의회"
          value={council}
          options={meta.councils.map((c) => ({
            value: c.source_id || c.id,
            label: c.name,
          }))}
          onChange={(council) => changeFilters({ council })}
        />
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
          options={available.map(([value, f]) => ({ value, label: f.label }))}
          onChange={(fundingType) => changeFilters({ fundingType })}
        />
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <ScopeBar scope={data.scope} />
          <div className="metrics">
            <Stat
              accent
              label="선택 기간 집행액"
              value={shortWon(data.summary.amount)}
              exact={data.summary.amount}
              detail={year + ".01–12 · " + data.council.name}
            />
            <Stat
              label="거래 확인 개월"
              value={count(data.summary.months) + " / 12개월"}
              detail="선택 재원의 거래가 수록된 달"
            />
            <Stat
              label="월평균 집행액"
              value={shortWon(data.summary.monthlyAverage)}
              exact={data.summary.monthlyAverage}
              detail={"합계 ÷ 집계 " + data.summary.months + "개월"}
            />
            <Stat
              label="거래 내역"
              value={count(data.summary.count) + "건"}
              detail="직책·반기별 기록"
            />
          </div>
          <Section
            title="이 기간의 직책과 보유자"
            description="직책 수행을 위한 경비입니다. 실제 결제자나 참석자를 뜻하지 않습니다."
          >
            <div className="person-grid">
              {data.roles.slice(0, 3).map((r) => (
                <Panel
                  key={r.id}
                  title={
                    r.subject.holders.map((h) => h.name).join(" · ") ||
                    "보유자 미확인"
                  }
                  description={r.subject.role + " · " + r.subject.term}
                >
                  <div className="person-amount green" title={won(r.amount)}>
                    {shortWon(r.amount)}
                  </div>
                  <p className="caption">
                    {r.firstDate}–{r.lastDate} · 해당 직책 합계
                  </p>
                  <ButtonLink
                    to={href("/members/" + r.id, {
                      year,
                      fundingType: funding,
                    })}
                  >
                    직책 프로필 · 근거
                  </ButtonLink>
                </Panel>
              ))}
            </div>
            {!data.roles.length && (
              <Empty>선택한 기간·재원에 연결된 직책 기록이 없습니다.</Empty>
            )}
          </Section>
          <div className="two-columns">
            <Panel
              title="항목별 집행액"
              description={year + "년 · 선택한 경비 재원만 집계"}
            >
              <Bars
                rows={data.categories}
                total={data.summary.amount}
                color="green"
              />
            </Panel>
            <Panel
              title="월별 집행액 추이"
              description={year + "년 1–12월 · 각 월 합계"}
            >
              <MonthlyChart data={data.monthly} />
            </Panel>
          </div>
          <Section
            title="직책·반기별 집행 현황"
            description="역할과 집계 기간을 함께 확인합니다."
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>직책</th>
                    <th>기간</th>
                    <th>확인된 보유자</th>
                    <th className="right">해당 기간 합계</th>
                    <th>상세</th>
                  </tr>
                </thead>
                <tbody>
                  {data.roles.map((r) => (
                    <tr key={r.id}>
                      <td>{r.subject.role || r.subject.name}</td>
                      <td>
                        {r.subject.term}
                        <small>
                          {r.firstDate}–{r.lastDate}
                        </small>
                      </td>
                      <td>
                        {r.subject.holders.map((h) => h.name).join(" · ") ||
                          "미확인"}
                      </td>
                      <td className="right numeric">{won(r.amount)}</td>
                      <td>
                        <Link
                          href={href("/members/" + r.id, {
                            year,
                            fundingType: funding,
                          })}
                        >
                          직책 내역 →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <Section
            title="최근 집행 내역"
            description="표시된 금액은 거래 1건 금액입니다."
          >
            <Transactions rows={data.transactions} showSubject />
          </Section>
          <SourceNote>
            <External url={data.council.board}>의회 공식 공개자료</External> ·
            공개되지 않은 기간과 거래가 없는 기간은 구분해야 합니다.
            정치자금·공동경비·사무국 경비는 합산하지 않습니다.
          </SourceNote>
        </>
      )}
    </div>
  );
}
