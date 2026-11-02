import { query, useMeta, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, shortWon, won } from "../format";
import {
  Bars,
  Empty,
  KeyValues,
  MonthlyChart,
  PageHeader,
  Panel,
  ReportControls,
  reportDates,
  ResourceState,
  ScopeBar,
  Section,
  Select,
  SourceNote,
  Stat,
  Tabs,
} from "../components/ui";
import type { Ranking } from "../types";

export function Rankings() {
  const { params } = useLocation();
  const meta = useMeta();
  const target = params.get("target") || "members",
    metric =
      params.get("metric") ||
      (target === "councils" ? "monthly_average" : "amount");
  const party =
      params.get("party") ?? (target === "members" ? "더불어민주당" : "all"),
    category = params.get("category") || "";
  const report = params.get("report") || "ka:2024-22",
    year = params.get("year") || "2024";
  const resource = useResource<Ranking>(
    "rankings?" +
      query({
        target,
        metric,
        party: party === "all" ? "" : party,
        category: target === "members" ? category : "",
        report,
        year,
        ...reportDates(params),
      }),
  );
  const data = resource.data;
  const isMonthly = target === "councils" && metric === "monthly_average";
  const scopeLabel =
    target === "assets"
      ? metric === "change"
        ? "신고액 증감"
        : "신고 순재산"
      : isMonthly
        ? "월평균 지출"
        : "보고분 지출 합계";
  return (
    <div className="page stack">
      <PageHeader
        title="비교·랭킹"
        context="비교와 장소"
        description="대상·정당·항목을 골라 같은 기준에서 금액을 비교합니다."
      />
      <div className="subnav">
        <Link className="active" href="/rankings">
          비교·랭킹
        </Link>
        <Link href="/places">자주 결제한 장소</Link>
      </div>
      <Tabs
        value={target}
        items={[
          { value: "members", label: "국회의원" },
          { value: "councils", label: "지방의회" },
          { value: "assets", label: "신고재산" },
        ]}
        onChange={(target) =>
          changeFilters({
            target,
            metric: target === "councils" ? "monthly_average" : "amount",
            category: "",
            month: "",
            party: target === "members" ? "더불어민주당" : "all",
          })
        }
      />
      <div className="filters">
        {target !== "councils" && (
          <Select
            label="비교 정당"
            value={party}
            options={[
              { value: "all", label: "정당 · 전체" },
              ...meta.parties.map((p) => ({ value: p, label: p })),
            ]}
            onChange={(party) => changeFilters({ party })}
          />
        )}
        {target === "members" && <ReportControls params={params} />}
        {target === "councils" && (
          <Select
            label="비교 연도"
            value={year}
            options={["2024", "2023", "2025", "2026", "2022"].map((y) => ({
              value: y,
              label: y + "년",
            }))}
            onChange={(year) => changeFilters({ year })}
          />
        )}
        {target !== "members" && (
          <Select
            label="비교 지표"
            value={metric}
            options={
              target === "councils"
                ? [
                    { value: "monthly_average", label: "월평균 집행액" },
                    { value: "amount", label: "선택 연도 집행 합계" },
                  ]
                : [
                    { value: "amount", label: "신고 순재산" },
                    { value: "change", label: "1년 신고액 증감" },
                  ]
            }
            onChange={(metric) => changeFilters({ metric })}
          />
        )}
      </div>
      {target === "members" && (
        <Tabs
          value={category}
          items={["", "홍보", "사무실", "차량", "간담회", "교통", "후원"].map(
            (value) => ({ value, label: value || "전체 지출" }),
          )}
          onChange={(category) => changeFilters({ category })}
        />
      )}
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <ScopeBar scope={data.scope}>
            {isMonthly && (
              <span className="scope-dates">
                순위 지표: 각 의회의 합계 ÷ 거래 수록 개월
              </span>
            )}
          </ScopeBar>
          <div className="metrics">
            <Stat
              accent
              label="비교 대상"
              value={count(data.n) + (target === "councils" ? "개 의회" : "명")}
              detail={
                target === "members"
                  ? (party === "all" ? "전체 정당" : party) +
                    " · " +
                    (category || "전체 지출")
                  : data.scope.label
              }
            />
            <Stat
              label={isMonthly ? "비교 지표 평균" : "선택 지표 합계"}
              value={shortWon(isMonthly ? data.mean : data.total)}
              exact={isMonthly ? data.mean : data.total}
              detail={isMonthly ? "각 의회 월평균의 산술평균" : scopeLabel}
            />
            <Stat
              label="중앙값"
              value={shortWon(data.median)}
              exact={data.median}
              detail={scopeLabel + " 기준"}
            />
            <Stat
              label="1위 금액"
              value={shortWon(data.rows[0]?.value)}
              exact={data.rows[0]?.value}
              detail="표시 건수로 사람에게 점수를 매기지 않습니다."
            />
          </div>
          {target === "members" ? (
            <div className="two-columns">
              <Panel
                title="선택 정당의 전체 항목 구성"
                description="지출 항목 선택과 별개로, 해당 정당 전체 보고분의 구성을 봅니다."
              >
                <Bars
                  rows={data.categories}
                  total={data.categories.reduce((s, r) => s + r.amount, 0)}
                />
              </Panel>
              <Panel
                title="선택 정당의 월별 전체 지출"
                description={
                  data.scope.start.slice(0, 4) +
                  "년 · 모든 항목을 합산한 각 월 금액"
                }
              >
                <MonthlyChart data={data.monthly || []} />
              </Panel>
            </div>
          ) : (
            <div className="two-columns">
              <Panel title="상위 금액 비교" description={scopeLabel}>
                <Bars
                  rows={data.rows.map((r) => ({
                    name: r.name,
                    amount: r.value,
                  }))}
                  max={10}
                />
              </Panel>
              <Panel title="비교 기준">
                <KeyValues
                  rows={[
                    [
                      "대상",
                      target === "assets"
                        ? "국회의원 신고재산"
                        : "기초 지방의회",
                    ],
                    ["지표", scopeLabel],
                    ["집계 범위", data.scope.label],
                    ["표본", count(data.n)],
                  ]}
                />
                <p className="caption">{data.note || data.scope.note}</p>
              </Panel>
            </div>
          )}
          <Section
            title={
              (target === "members" && party !== "all" ? party + " " : "") +
              (category || scopeLabel) +
              " Top 10"
            }
            description={
              "같은 범위의 대상 " +
              count(data.n) +
              " · 중앙값 " +
              shortWon(data.median)
            }
          >
            {data.rows.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>순위</th>
                      <th>{target === "councils" ? "의회" : "보고자"}</th>
                      <th>
                        {target === "councils" ? "집계 개월" : "정당 · 지역구"}
                      </th>
                      <th className="right">{scopeLabel}</th>
                      <th className="right">중앙값 대비</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.map((r) => (
                      <tr key={r.id || r.name}>
                        <td className="numeric">{r.rank}</td>
                        <td>
                          {r.id ? (
                            <Link
                              href={
                                target === "councils"
                                  ? href("/councils", { council: r.id, year })
                                  : href("/members/" + r.id, {
                                      report,
                                      month: params.get("month"),
                                      tab:
                                        target === "assets"
                                          ? "assets"
                                          : "money",
                                    })
                              }
                            >
                              {r.name}
                            </Link>
                          ) : (
                            r.name
                          )}
                        </td>
                        <td>
                          {target === "councils" ? (
                            r.months + "개월"
                          ) : (
                            <>
                              {r.party}
                              <small>{r.district}</small>
                            </>
                          )}
                        </td>
                        <td className="numeric right" title={won(r.value)}>
                          {shortWon(r.value)}
                        </td>
                        <td className="numeric right">
                          {r.ratioToMedian
                            ? r.ratioToMedian.toFixed(2) + "배"
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>선택한 조건에 비교 가능한 기록이 없습니다.</Empty>
            )}
          </Section>
          <SourceNote>
            {data.note || data.scope.note}{" "}
            {target === "members" &&
              "정당 표기는 해당 회계자료 기준입니다. 정당 회계의 지출과는 별개입니다."}
          </SourceNote>
        </>
      )}
    </div>
  );
}
