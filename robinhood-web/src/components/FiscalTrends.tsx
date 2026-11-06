import { changeFilters, useLocation } from "../router";
import { percent, shortWon, won } from "../format";
import { Empty, Notice, Panel, Select, Stat, Tabs } from "./ui";
import type { Fiscal, FiscalPoint, FiscalTrend } from "../types";

const basisLabel = (basis: FiscalPoint["basis"]) =>
  ({ actual: "결산", budget: "확정 예산", proposal: "정부 예산안" })[
    basis || "actual"
  ];
const delta = (value: number | null) =>
  value === null ? "비교 자료 없음" : (value > 0 ? "+" : "") + shortWon(value);
const rate = (value: number | null) =>
  value === null ? "비교 불가" : (value > 0 ? "+" : "") + percent(value);

function TrendChart({ trend }: { trend: FiscalTrend }) {
  const points = trend.points;
  const observed = points.filter((point) => point.amount !== null);
  if (!observed.length)
    return <Empty>이 기준의 연간 추세 자료가 없습니다.</Empty>;
  const amounts = observed.map((point) => point.amount!);
  const min = Math.min(0, ...amounts),
    max = Math.max(1, ...amounts);
  const x = (i: number) => 55 + (i * 590) / Math.max(points.length - 1, 1);
  const y = (amount: number) => 190 - ((amount - min) / (max - min)) * 135;
  return (
    <figure className="history-chart fiscal-trend-chart">
      <svg
        viewBox="0 0 700 235"
        role="img"
        aria-label={`${trend.name} 연도별 금액 추세`}
      >
        {[min, (max + min) / 2, max].map((value, index) => (
          <g key={index}>
            <line
              x1="55"
              x2="660"
              y1={y(value)}
              y2={y(value)}
              stroke="#e0e4e6"
            />
            <text x="48" y={y(value) + 4} textAnchor="end">
              {shortWon(value)}
            </text>
          </g>
        ))}
        {points.map((point, i) => {
          if (point.amount === null) return null;
          const previous = points[i - 1];
          return (
            <g key={point.year}>
              <title>
                {point.year}년 {basisLabel(point.basis)} · {won(point.amount)}
              </title>
              {previous?.amount !== null && previous?.amount !== undefined && (
                <line
                  x1={x(i - 1)}
                  y1={y(previous.amount)}
                  x2={x(i)}
                  y2={y(point.amount)}
                  stroke="#1e4d7b"
                  strokeWidth="3"
                  strokeDasharray={
                    point.basis === "proposal" ? "7 5" : undefined
                  }
                />
              )}
              <circle
                cx={x(i)}
                cy={y(point.amount)}
                r="5"
                stroke="#141414"
                fill={point.basis === "proposal" ? "#e2ff3a" : "#fff"}
              />
              {(points.length <= 7 ||
                i % 2 === 0 ||
                i === points.length - 1) && (
                <text x={x(i)} y="218" textAnchor="middle">
                  {point.year}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption>
        단위: 원 · 정부안 연결 구간은 점선 · 누락 연도는 선을 잇지 않습니다.
      </figcaption>
      <details className="chart-data">
        <summary>연도별 금액과 비중 표로 보기</summary>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">{trend.name} 연도별 원자료</caption>
            <thead>
              <tr>
                <th>연도</th>
                <th>기준</th>
                <th className="right">금액</th>
                <th className="right">비중</th>
              </tr>
            </thead>
            <tbody>
              {points.map((point) => (
                <tr key={point.year}>
                  <td>{point.year}</td>
                  <td>
                    {point.amount === null
                      ? "자료 없음"
                      : basisLabel(point.basis)}
                  </td>
                  <td className="right numeric">{won(point.amount)}</td>
                  <td className="right numeric">{percent(point.share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

export function FiscalTrends({ data }: { data: Fiscal }) {
  const { params } = useLocation();
  const series = data.trends.series;
  const selected =
    series.find((row) => row.id === params.get("series")) || series[0];
  const group = params.get("breakdown") === "ministry" ? "ministry" : "sector";
  const rows = series
    .filter((row) => row.dimension === group && row.current?.amount != null)
    .sort((a, b) => Math.abs(b.delta || 0) - Math.abs(a.delta || 0))
    .slice(0, 10);
  const current = selected.current,
    previous = selected.previous;
  const direction =
    selected.delta === null
      ? ""
      : selected.delta > 0
        ? "증가"
        : selected.delta < 0
          ? "감소"
          : "변동 없음";
  return (
    <section
      className="stack fiscal-trends"
      aria-labelledby="fiscal-trend-heading"
    >
      <div className="section-heading">
        <h2 id="fiscal-trend-heading">얼마나 달라졌나</h2>
        <p className="caption">
          연도별 금액 · 전년 대비 변화 · 같은 통계 안에서의 비중
        </p>
      </div>
      <Select
        label="추세를 볼 항목"
        value={selected.id}
        options={series.map((row) => ({
          value: row.id,
          label:
            (row.dimension === "sector"
              ? "분야 · "
              : row.dimension === "ministry"
                ? "부처 · "
                : "") + row.name,
        }))}
        onChange={(value) => changeFilters({ series: value })}
      />
      <div className="metrics">
        <Stat
          accent
          label={selected.name}
          value={shortWon(current?.amount)}
          exact={current?.amount}
          detail={`${data.selectedYear}년 · ${current?.amount === null ? "연간 자료 없음" : basisLabel(current?.basis || null)}`}
        />
        <Stat
          label="전년 대비 금액"
          value={delta(selected.delta)}
          exact={selected.delta}
          detail={
            previous?.amount !== null && previous
              ? `${previous.year}년 ${basisLabel(previous.basis)} 대비`
              : "전년도 같은 항목이 있어야 비교합니다."
          }
        />
        <Stat
          label="전년 대비 증감률"
          value={rate(selected.rate)}
          detail="전년도 금액이 0이면 증감률을 계산하지 않습니다."
        />
        <Stat
          label={
            selected.dimension === "total"
              ? "비교 대상 연도"
              : "수록 항목 내 비중"
          }
          value={
            selected.dimension === "total"
              ? previous?.amount !== null && previous
                ? previous.year + "년"
                : "비교 자료 없음"
              : percent(current?.share)
          }
          detail={
            selected.dimension === "total"
              ? previous?.label || "전년도 자료 미수집"
              : selected.shareDeltaPp === null
                ? "전년도 비중 비교 자료 없음"
                : `전년 대비 ${selected.shareDeltaPp > 0 ? "+" : ""}${selected.shareDeltaPp.toFixed(1)}%p`
          }
        />
      </div>
      {selected.delta !== null && current && previous ? (
        <p className="fiscal-change-story">
          <strong>{selected.name}</strong>의 {current.year}년{" "}
          {basisLabel(current.basis)} 금액은{" "}
          <strong>{shortWon(current.amount)}</strong>입니다. {previous.year}년{" "}
          {basisLabel(previous.basis)}와 비교하면
          {selected.delta === 0 ? (
            " 금액 변동이 없습니다."
          ) : (
            <>
              {" "}
              <strong>{shortWon(Math.abs(selected.delta))}</strong>
              {selected.rate === null
                ? " "
                : ` (${percent(Math.abs(selected.rate))}) `}
              {direction}했습니다.
            </>
          )}
        </p>
      ) : (
        <Notice>
          전년도 같은 항목의 자료가 없거나 연간 결산이 완료되지 않아 증감을
          계산하지 않았습니다. 누락은 0원이 아닙니다.
        </Notice>
      )}
      <Panel
        title={`${selected.name} 추세`}
        description={
          selected.denominator
            ? `비중의 분모: ${selected.denominator}`
            : data.values
              ? "월간 재정동향의 12월 누계가 있는 연도만 연간 비교합니다."
              : "예산은 수집된 부처 항목 합계이며 결산 총지출과 기준이 다릅니다."
        }
      >
        <TrendChart trend={selected} />
      </Panel>
      <Panel
        title="변화가 큰 분야와 부처"
        description="전년 대비 금액 변화의 절댓값 순 · 최대 10개 · 항목을 누르면 해당 추세를 봅니다."
      >
        <Tabs
          value={group}
          items={[
            { value: "sector", label: "분야별 변화" },
            { value: "ministry", label: "부처별 변화" },
          ]}
          onChange={(value) => changeFilters({ breakdown: value })}
        />
        {rows.length ? (
          <div className="table-scroll">
            <table className="fiscal-change-table">
              <caption className="sr-only">
                전년도 대비 분야·부처별 금액과 비중 변화
              </caption>
              <thead>
                <tr>
                  <th>항목</th>
                  <th className="right">금액</th>
                  <th className="right">증감액</th>
                  <th className="right">증감률</th>
                  <th className="right">비중</th>
                  <th className="right">비중 변화</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <th scope="row">
                      <button
                        className="text-link"
                        onClick={() => changeFilters({ series: row.id })}
                      >
                        {row.name}
                      </button>
                    </th>
                    <td className="right numeric">
                      {shortWon(row.current?.amount)}
                    </td>
                    <td className="right numeric">{delta(row.delta)}</td>
                    <td className="right numeric">{rate(row.rate)}</td>
                    <td className="right numeric">
                      {percent(row.current?.share)}
                    </td>
                    <td className="right numeric">
                      {row.shareDeltaPp === null
                        ? "—"
                        : `${row.shareDeltaPp > 0 ? "+" : ""}${row.shareDeltaPp.toFixed(1)}%p`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>
            해당 기준·연도에 수록된 {group === "sector" ? "분야" : "부처"}{" "}
            자료가 없습니다.
          </Empty>
        )}
      </Panel>
      <Notice>
        {data.trends.note} 항목 이름이나 분류가 바뀌어 동일 항목을 찾지 못한
        경우에도 전년 비교를 표시하지 않습니다.
      </Notice>
    </section>
  );
}
