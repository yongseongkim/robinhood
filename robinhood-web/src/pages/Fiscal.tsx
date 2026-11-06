import { query, useResource } from "../api";
import { changeFilters, useLocation } from "../router";
import { count, shortWon, won } from "../format";
import {
  Bars,
  Empty,
  External,
  KeyValues,
  Notice,
  PageHeader,
  Panel,
  ResourceState,
  ScopeBar,
  Section,
  Select,
  SourceNote,
  Stat,
  Tabs,
} from "../components/ui";
import type { Fiscal as FiscalData } from "../types";
import { FiscalTrends } from "../components/FiscalTrends";

function HistoryChart({
  rows,
  balance = false,
}: {
  rows: FiscalData["history"];
  balance?: boolean;
}) {
  const data = rows.slice(-7);
  const width = 700,
    height = 245;
  const values = data.flatMap((r) =>
    balance ? [r.integrated_balance] : [r.total_revenue, r.total_expenditure],
  );
  const min = balance ? Math.min(...values, 0) : 0,
    max = Math.max(...values, 1);
  const y = (v: number) => 196 - ((v - min) / (max - min || 1)) * 160;
  const x = (i: number) => 40 + i * 100;
  const line = (
    key: "total_revenue" | "total_expenditure" | "integrated_balance",
  ) => data.map((r, i) => (i ? "L" : "M") + x(i) + "," + y(r[key])).join(" ");
  return (
    <figure className="history-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={balance ? "연도별 통합재정수지" : "연도별 수입과 지출"}
      >
        <line x1="25" x2="675" y1={y(0)} y2={y(0)} stroke="#cbd1d5" />
        {balance ? (
          <path
            d={line("integrated_balance")}
            fill="none"
            stroke="#1e4d7b"
            strokeWidth="3"
          />
        ) : (
          <>
            <path
              d={line("total_revenue")}
              fill="none"
              stroke="#141414"
              strokeWidth="3"
            />
            <path
              d={line("total_expenditure")}
              fill="none"
              stroke="#1e4d7b"
              strokeWidth="3"
            />
          </>
        )}
        {data.map((r, i) => (
          <g key={r.year}>
            <title>
              {r.year}:{" "}
              {balance
                ? shortWon(r.integrated_balance)
                : "총수입 " +
                  shortWon(r.total_revenue) +
                  ", 총지출 " +
                  shortWon(r.total_expenditure)}
            </title>
            <circle
              cx={x(i)}
              cy={y(balance ? r.integrated_balance : r.total_expenditure)}
              r="5"
              fill="#e2ff3a"
              stroke="#141414"
            />
            <text x={x(i)} y="228" textAnchor="middle">
              {r.year}
            </text>
          </g>
        ))}
      </svg>
      <figcaption>
        {balance
          ? "통합재정수지 · 같은 연도 결산"
          : "검정: 총수입 · 파랑: 총지출 · 같은 눈금의 연간 결산"}
      </figcaption>
    </figure>
  );
}
export function Fiscal() {
  const { params } = useLocation();
  const basis = params.get("basis") || "actual";
  const selectedYear = params.get("year");
  const resource = useResource<FiscalData>(
    "fiscal?" + query({ year: selectedYear, basis }),
  );
  const data = resource.data;
  const year = selectedYear || (data ? String(data.selectedYear) : "");
  const values = data?.values;
  return (
    <div className="page stack">
      <PageHeader
        title="나라 살림"
        context="국가재정"
        description="나라 살림이 얼마나 늘었고, 어느 분야와 부처의 비중이 달라졌는지 확인합니다."
      />
      <div className="filters">
        <Tabs
          value={basis}
          items={[
            { value: "actual", label: "결산" },
            { value: "budget", label: "확정 예산" },
            { value: "proposal", label: "예산안" },
          ]}
          onChange={(basis) =>
            changeFilters({
              basis,
              year: null,
            })
          }
        />
        <Select
          label="재정 연도"
          value={year}
          options={(
            data?.availableYears[basis as "actual" | "budget" | "proposal"] ||
            []
          ).map((y) => ({ value: String(y), label: y + "년" }))}
          onChange={(year) => changeFilters({ year })}
        />
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <ScopeBar scope={data.scope} />
          <FiscalTrends data={data} />
          {values ? (
            <>
              <div className="metrics">
                <Stat
                  accent
                  label={
                    values.through_month === 12 ? "연간 총수입" : "누계 총수입"
                  }
                  value={shortWon(values.total_revenue)}
                  exact={values.total_revenue}
                  detail={year + `.01–${values.through_month} · 집행 누계`}
                />
                <Stat
                  label={
                    values.through_month === 12 ? "연간 총지출" : "누계 총지출"
                  }
                  value={shortWon(values.total_expenditure)}
                  exact={values.total_expenditure}
                  detail={year + `.01–${values.through_month} · 집행 누계`}
                />
                <Stat
                  label={
                    values.through_month === 12
                      ? "연간 통합재정수지"
                      : "누계 통합재정수지"
                  }
                  value={shortWon(values.integrated_balance)}
                  exact={values.integrated_balance}
                  detail="총수입 − 총지출"
                />
                <Stat
                  label={
                    values.through_month === 12
                      ? "연간 관리재정수지"
                      : "누계 관리재정수지"
                  }
                  value={shortWon(values.managed_balance)}
                  exact={values.managed_balance}
                  detail="사회보장성기금 수지 제외"
                />
              </div>
              <div className="two-columns">
                <Panel
                  title="수입과 지출, 해마다"
                  description="12월 누계가 수집된 연도만 비교합니다."
                >
                  <HistoryChart rows={data.history} />
                </Panel>
                <Panel
                  title="통합재정수지 추이"
                  description="0보다 작으면 적자 · 관리재정수지와 구분"
                >
                  <HistoryChart rows={data.history} balance />
                </Panel>
              </div>
              <div className="two-columns">
                <Panel
                  title="총수입은 어디서 왔나"
                  description={year + "년 연간 집행 실적 · 동일 통계의 구성"}
                >
                  <Bars
                    rows={[
                      { name: "국세", amount: values.national_tax },
                      { name: "세외수입", amount: values.non_tax },
                      { name: "기금수입", amount: values.fund_revenue },
                    ]}
                    total={values.total_revenue}
                  />
                </Panel>
                <Panel
                  title="어디에 썼나 · 분야별"
                  description={year + "년 분야별 결산 통계"}
                >
                  <Bars
                    rows={[...(data.sectors?.items || [])].sort(
                      (a, b) => b.amount - a.amount,
                    )}
                    max={6}
                    color="green"
                  />
                </Panel>
              </div>
            </>
          ) : (
            <>
              <div className="metrics">
                <Stat
                  accent
                  label="수집된 부처 항목 합계"
                  value={shortWon(
                    data.ministries?.items.reduce((s, i) => s + i.amount, 0),
                  )}
                  detail={data.scope.label + " · 부처 수록 항목만 합산"}
                />
                <Stat
                  label="수록 부처"
                  value={count(data.ministries?.items.length) + "개"}
                  detail={data.ministries?.basis}
                />
                <Stat
                  label="분야별 자료"
                  value={
                    data.sectors
                      ? count(data.sectors.items.length) + "개 분야"
                      : "미수집"
                  }
                />
                <Stat
                  label="재정수지"
                  value="실적과 별도"
                  detail="예산을 결산 실적으로 해석하지 않습니다."
                />
              </div>
              <Notice>
                확정 예산과 정부 예산안은 집행 결과가 아닙니다. 수록된 부처 항목
                합계는 결산 총지출과 집계 기준이 다릅니다.
              </Notice>
              <div className="two-columns">
                <Panel title="부처별 예산" description={data.ministries?.basis}>
                  <Bars rows={data.ministries?.items || []} max={10} />
                </Panel>
                <Panel title="예산 수입 항목" description={data.revenue?.basis}>
                  {data.revenue ? (
                    <Bars rows={data.revenue.items} color="green" />
                  ) : (
                    <Empty>
                      해당 연도·기준의 수입 구성은 수집되지 않았습니다.
                    </Empty>
                  )}
                </Panel>
              </div>
            </>
          )}
          {data.ministries && (
            <Section
              title="부처별 세부 항목"
              description={data.ministries.basis}
            >
              <div className="ministry-list">
                {data.ministries.items.slice(0, 15).map((m) => (
                  <details key={m.name}>
                    <summary>
                      <span>{m.name}</span>
                      <span className="numeric">{won(m.amount)}</span>
                    </summary>
                    {m.top_programs?.length ? (
                      <KeyValues
                        rows={m.top_programs.map((p) => [
                          p.name,
                          won(p.amount),
                        ])}
                      />
                    ) : (
                      <p className="caption">
                        수집본에는 해당 부처 합계가 수록돼 있습니다.
                      </p>
                    )}
                  </details>
                ))}
              </div>
            </Section>
          )}
          <div className="two-columns">
            <Panel
              title="연말 국가채무"
              description={year + ".12.31 기준 · 잔액(D1)"}
            >
              {data.debt ? (
                <>
                  <div className="large-number">
                    {shortWon(data.debt.national_debt)}
                  </div>
                  <p>GDP 대비 {data.debt.gdp_ratio_pct}%</p>
                </>
              ) : (
                <Empty>이 기준·연도에 연결된 국가채무 자료가 없습니다.</Empty>
              )}
            </Panel>
            <Panel title="지역의 재정수지도 보려면">
              <p>
                지방자치단체 전체 수입·결산은 아직 수집되지 않았습니다. 지방의회
                업무추진비만으로 지역의 흑자·적자를 계산하지 않습니다.
              </p>
            </Panel>
          </div>
          <SourceNote>
            <External url={data.source.url}>{data.source.name}</External> ·{" "}
            {data.scope.note} 분야·부처 통계와 월간 재정동향 누계는 각각의 집계
            기준을 따릅니다.
          </SourceNote>
        </>
      )}
    </div>
  );
}
