import { useEffect, useState } from "react";
import type { ReactNode, FormEvent } from "react";
import {
  ArrowRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Info,
  Search,
} from "lucide-react";
import { changeFilters, Link } from "../router";
import { useMeta } from "../api";
import { count, externalUrl, shortWon, won } from "../format";
import type { Category, Month, Scope, Transaction } from "../types";

export function PageHeader({
  title,
  description,
  context,
  children,
}: {
  title: string;
  description?: string;
  context?: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="eyebrow">나랏일보고서{context && " / " + context}</div>
      <h1>{title}</h1>
      {description && <p>{description}</p>}
      {children}
    </header>
  );
}
export function ScopeBar({
  scope,
  children,
}: {
  scope: Scope;
  children?: ReactNode;
}) {
  const meta = useMeta();
  return (
    <div className="scope-bar">
      <CalendarDays size={16} aria-hidden="true" />
      <div>
        <span>{scope.label}</span>
        <span className="scope-dates">
          {scope.start} {scope.end !== scope.start && "– " + scope.end}
        </span>
        {scope.fundingType && (
          <span className="fund-label">
            {meta.fundingTypes[scope.fundingType]?.label || scope.fundingType}
          </span>
        )}
        {children}
      </div>
    </div>
  );
}
export function Panel({
  title,
  description,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + className}>
      {title && <h2>{title}</h2>}
      {description && <p className="caption">{description}</p>}
      {children}
    </section>
  );
}
export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section-heading">
        <h2>{title}</h2>
        {description && <p className="caption">{description}</p>}
      </div>
      {children}
    </section>
  );
}
export function Stat({
  label,
  value,
  detail,
  exact,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  exact?: number | null;
  accent?: boolean;
}) {
  return (
    <div className={"stat" + (accent ? " stat-accent" : "")}>
      <div className="stat-label">{label}</div>
      <div
        className="stat-value"
        title={exact === undefined ? undefined : won(exact)}
      >
        {value}
      </div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}
export function SourceNote({ children }: { children: ReactNode }) {
  return (
    <aside className="source-note">
      <span aria-hidden="true" /> <div>{children}</div>
    </aside>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Info size={16} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}
export function External({
  url,
  children,
}: {
  url?: string;
  children: ReactNode;
}) {
  const safe = externalUrl(url);
  return safe ? (
    <a
      className="external"
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
      <ExternalLink size={12} aria-hidden="true" />
    </a>
  ) : (
    <span>{children}</span>
  );
}
export function ButtonLink({
  to,
  children,
  primary = false,
}: {
  to: string;
  children: ReactNode;
  primary?: boolean;
}) {
  return (
    <Link className={"button-link" + (primary ? " primary" : "")} href={to}>
      {children}
      <ArrowRight size={14} aria-hidden="true" />
    </Link>
  );
}
export function Tabs({
  items,
  value,
  onChange,
  label,
}: {
  items: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={value === item.value}
          tabIndex={value === item.value ? 0 : -1}
          className={value === item.value ? "selected" : ""}
          onClick={() => onChange(item.value)}
          onKeyDown={(event) => {
            const direction =
              event.key === "ArrowRight"
                ? 1
                : event.key === "ArrowLeft"
                  ? -1
                  : 0;
            if (!direction && event.key !== "Home" && event.key !== "End")
              return;
            event.preventDefault();
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? items.length - 1
                  : (index + direction + items.length) % items.length;
            onChange(items[next].value);
            event.currentTarget.parentElement
              ?.querySelectorAll("button")
              [next]?.focus();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="select-control">
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
export function SearchForm({
  value = "",
  placeholder,
  onSearch,
}: {
  value?: string;
  placeholder: string;
  onSearch: (value: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <form
      className="search-field"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(text.trim());
      }}
    >
      <Search size={16} aria-hidden="true" />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button type="submit">검색</button>
    </form>
  );
}
export function ResourceState({
  error,
  retry,
}: {
  error?: string;
  retry: () => void;
}) {
  return error ? (
    <div className="empty error" role="alert">
      <h2>데이터를 읽지 못했습니다</h2>
      <p>{error}</p>
      <button onClick={retry} className="button-link">
        다시 시도
      </button>
    </div>
  ) : (
    <div className="loading" role="status" aria-label="데이터를 불러오는 중">
      <div className="skeleton skeleton-title" />
      <div className="metrics">
        {[1, 2, 3, 4].map((i) => (
          <div className="skeleton skeleton-metric" key={i} />
        ))}
      </div>
      <div className="skeleton skeleton-chart" />
      <span className="sr-only">데이터를 불러오는 중입니다.</span>
    </div>
  );
}
export function Empty({
  children = "선택한 조건에 해당하는 기록이 없습니다.",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <p>{children}</p>
    </div>
  );
}
export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="pagination" aria-label="페이지 이동">
      <span>
        {total ? count((page - 1) * pageSize + 1) : 0}–
        {count(Math.min(page * pageSize, total))} / {count(total)}건
      </span>
      <div>
        <button
          aria-label="이전 페이지"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <span aria-live="polite">
          {page} / {last}
        </span>
        <button
          aria-label="다음 페이지"
          disabled={page >= last}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </nav>
  );
}
export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="key-values">
      {rows.map(([label, value], i) => (
        <div key={i}>
          <dt>{label}</dt>
          <dd>
            {value === undefined || value === null || value === ""
              ? "미기재"
              : value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Bars({
  rows,
  total,
  max = 7,
  color = "blue",
}: {
  rows: Category[];
  total?: number | null;
  max?: number;
  color?: string;
}) {
  const values = rows.slice(0, max);
  const largest = Math.max(...values.map((r) => Math.abs(r.amount)), 1);
  return values.length ? (
    <div className={"bars " + color}>
      {values.map((r, i) => (
        <div className="bar-row" key={r.name}>
          <div>
            <span>{r.name}</span>
            <span className="numeric" title={won(r.amount)}>
              {shortWon(r.amount)}
              {total && total > 0
                ? " · " + ((r.amount / total) * 100).toFixed(1) + "%"
                : ""}
            </span>
          </div>
          <div className="bar-track">
            <span
              className={i === 0 ? "leading" : ""}
              style={{
                width:
                  Math.max(0.5, (Math.abs(r.amount) / largest) * 100) + "%",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  ) : (
    <Empty />
  );
}
export function MonthlyChart({
  data,
  mode = "amount",
}: {
  data: Month[];
  mode?: "amount" | "payments";
}) {
  const amounts = data.map((d) =>
    mode === "payments" ? (d.hasRecords ? d.payments : null) : d.amount,
  );
  const max = Math.max(...amounts.map((a) => Math.abs(a || 0)), 1);
  const signed = amounts.some((a) => a !== null && a < 0);
  const baseline = signed ? 100 : 180;
  const amplitude = signed ? 76 : 144;
  const width = data.length * 62 + 24;
  return (
    <figure className="monthly-chart">
      <svg
        viewBox={`0 0 ${width} 218`}
        role="img"
        aria-label={
          mode === "amount" ? "월별 지출 합계 그래프" : "월별 결제 건수 그래프"
        }
      >
        <line
          x1="12"
          x2={width - 12}
          y1={baseline}
          y2={baseline}
          stroke="#dce0e3"
        />
        {data.map((d, i) => {
          const value = amounts[i];
          const bar = (Math.abs(value || 0) / max) * amplitude;
          const x = i * 62 + 20;
          const y = value !== null && value >= 0 ? baseline - bar : baseline;
          return (
            <g key={d.month}>
              <title>
                {d.month}:{" "}
                {value === null
                  ? "해당 범위에 기록 없음"
                  : mode === "amount"
                    ? won(value)
                    : count(value) + "건"}
              </title>
              <rect
                x={x}
                y={y}
                width="38"
                height={value === null ? 0 : Math.max(1, bar)}
                rx="1"
                fill={Math.abs(value || 0) === max ? "#e2ff3a" : "#1e4d7b"}
              />
              <text
                className="chart-values"
                x={x + 19}
                y={value !== null && value < 0 ? y + bar + 13 : y - 8}
                textAnchor="middle"
              >
                {value === null
                  ? "—"
                  : mode === "payments"
                    ? count(value)
                    : shortWon(value)}
              </text>
              <text x={x + 19} y="209" textAnchor="middle">
                {Number(d.month.slice(5))}월
              </text>
            </g>
          );
        })}
      </svg>
      <details className="chart-data">
        <summary>월별 수치 보기</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>월</th>
                <th>{mode === "amount" ? "월 합계" : "결제 건수"}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((d, i) => (
                <tr key={d.month}>
                  <td>{d.month}</td>
                  <td>
                    {amounts[i] === null
                      ? "해당 범위에 기록 없음"
                      : mode === "amount"
                        ? won(amounts[i])
                        : count(amounts[i]) + "건"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
export function Transactions({
  rows,
  showSubject = false,
}: {
  rows: Transaction[];
  showSubject?: boolean;
}) {
  return rows.length ? (
    <div className="table-scroll">
      <table className="transaction-table">
        <thead>
          <tr>
            <th>거래일</th>
            {showSubject && <th>보고 주체</th>}
            <th>사용처 · 목적</th>
            <th className="right">건별 금액</th>
            <th>분류</th>
            <th>상세·출처</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td className="numeric">
                {t.date}
                <small>{t.time || "시각 미기재"}</small>
              </td>
              {showSubject && (
                <td>
                  <Link
                    href={
                      "/members/" +
                      encodeURIComponent(t.subjectId) +
                      "?" +
                      (t.fundingType === "POLITICAL_FUND"
                        ? "report=" + encodeURIComponent(t.docId)
                        : "fundingType=" +
                          encodeURIComponent(t.fundingType) +
                          "&year=" +
                          t.date.slice(0, 4))
                    }
                  >
                    {t.subjectName}
                  </Link>
                </td>
              )}
              <td>
                {t.merchantId ? (
                  <Link href={"/places/" + t.merchantId}>{t.payee}</Link>
                ) : (
                  t.payee || "미기재"
                )}
                <small>{t.description || "목적 미기재"}</small>
              </td>
              <td className="right numeric">
                {won(t.amount)}
                {t.amount < 0 && <small>취소·반환</small>}
              </td>
              <td>
                <small>{t.category?.replaceAll("_", " · ")}</small>
              </td>
              <td>
                <Link
                  className="text-link"
                  href={"/transactions/" + encodeURIComponent(t.id)}
                >
                  거래 확인 <ArrowRight size={12} />
                </Link>
                {t.quality.ocr && <small>OCR 정제 자료</small>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty />
  );
}
export function reportDates(params: URLSearchParams) {
  const month = params.get("month");
  if (!month || !/^\d{4}-\d{2}$/.test(month)) return {};
  const [year, number] = month.split("-").map(Number);
  const last = new Date(year, number, 0).getDate();
  return { start: month + "-01", end: month + "-" + last };
}
export function shortReportLabel(id: string, title: string) {
  const labels: Record<string, string> = {
    "ka:2024-22": "2024 · 22대",
    "ka:2024-21": "2024 · 21대",
    "ka:2023": "2023 · 21대",
  };
  return labels[id] || title;
}

export function ReportControls({
  params,
  compact = false,
}: {
  params: URLSearchParams;
  compact?: boolean;
}) {
  const meta = useMeta();
  const report = params.get("report") || "ka:2024-22";
  const year = report.includes("2023") ? "2023" : "2024";
  return (
    <>
      <Select
        label="정치자금 보고서"
        value={report}
        options={meta.reports.map((r) => ({
          value: r.id,
          label: compact
            ? shortReportLabel(r.id, r.title)
            : r.id === "ka:2024-22"
              ? "2024년 제22대 보고분"
              : r.id === "ka:2024-21"
                ? "2024년 제21대 보고분"
                : "2023년 제21대 보고분",
        }))}
        onChange={(report) => changeFilters({ report, month: "" })}
      />
      <Select
        label="집계 월"
        value={params.get("month") || ""}
        options={[
          {
            value: "",
            label: compact ? "보고분 전체 기간" : "선택 보고분 전체 기간",
          },
          ...Array.from({ length: 12 }, (_, i) => ({
            value: year + "-" + String(i + 1).padStart(2, "0"),
            label: year + "년 " + (i + 1) + "월",
          })),
        ]}
        onChange={(month) => changeFilters({ month })}
      />
    </>
  );
}
export function RangeControls({
  start,
  end,
  onChange,
}: {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}) {
  const [from, setFrom] = useState(start),
    [to, setTo] = useState(end);
  useEffect(() => {
    setFrom(start);
    setTo(end);
  }, [start, end]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (from && to && from <= to) onChange(from, to);
  };
  return (
    <form className="range-control" onSubmit={submit}>
      <label>
        <span className="sr-only">시작일</span>
        <input
          aria-label="시작일"
          type="date"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          required
        />
      </label>
      <span>–</span>
      <label>
        <span className="sr-only">종료일</span>
        <input
          aria-label="종료일"
          type="date"
          value={to}
          min={from}
          onChange={(e) => setTo(e.target.value)}
          required
        />
      </label>
      <button type="submit">기간 적용</button>
    </form>
  );
}
