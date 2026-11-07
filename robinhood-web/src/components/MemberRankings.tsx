import type { ReactNode } from "react";
import { query, useMeta, useResource } from "../api";
import { count, externalUrl, percent, shortWon, won } from "../format";
import { changeFilters, href, Link, useLocation } from "../router";
import type { MemberRankings as RankingsData, Ranking } from "../types";
import {
  Empty,
  External,
  ResourceState,
  Select,
  SourceNote,
  shortReportLabel,
} from "./ui";

export type RankingView = "assets" | "changes" | "funds" | "parties";

function RankingBoard({
  title,
  ranking,
  report,
  assetUrl,
  level = 2,
  showNote = true,
  showScope = true,
}: {
  title: string;
  ranking: Ranking;
  report: string;
  assetUrl?: string;
  level?: 2 | 3;
  showNote?: boolean;
  showScope?: boolean;
}) {
  const Heading = level === 3 ? "h3" : "h2";
  const share = ranking.metric === "share";
  const format = share ? percent : shortWon;
  return (
    <section className="panel member-ranking-card">
      <div className="member-board-heading">
        <Heading>{title}</Heading>
        {showScope && <p className="caption">{ranking.scope.label}</p>}
      </div>
      {ranking.n > 0 ? (
        <>
          <div className="member-ranking-summary">
            <span>
              비교 대상 <strong>{count(ranking.n)}명</strong>
            </span>
            <span>
              중앙값 <strong>{format(ranking.median)}</strong>
            </span>
          </div>
          <div className="member-ranking-columns" aria-hidden="true">
            <span>순위 · 의원</span>
            <span>{share ? "비중 · 신고액 / 총자산" : "금액"}</span>
          </div>
          <ol className="member-ranking-list" aria-label={title}>
            {ranking.rows.map((row) => {
              const destination = row.id
                ? href("/members/" + row.id, {
                    report,
                    tab: ranking.target === "assets" ? "assets" : "money",
                  })
                : undefined;
              const source = externalUrl(
                assetUrl && assetUrl + (row.page ? "#page=" + row.page : ""),
              );
              const contents = (
                <>
                  <span className="member-ranking-position numeric">
                    {row.rank}
                  </span>
                  <span className="member-ranking-person">
                    <strong>{row.name}</strong>
                    <small>
                      {row.party || "정당 미기재"}
                      {row.district && " · " + row.district}
                    </small>
                  </span>
                  <span
                    className="member-ranking-value numeric"
                    title={
                      share
                        ? won(row.amount) + " / 총자산 " + won(row.grossAssets)
                        : won(row.value)
                    }
                  >
                    {format(row.value)}
                    {share && (
                      <small>
                        {shortWon(row.amount)} / {shortWon(row.grossAssets)}
                      </small>
                    )}
                  </span>
                </>
              );
              return (
                <li key={row.id || row.name + ":" + row.page}>
                  {destination ? (
                    <Link className="member-ranking-row" href={destination}>
                      {contents}
                    </Link>
                  ) : source ? (
                    <a
                      className="member-ranking-row"
                      href={source}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={row.name + " 재산공개 원자료 보기 (새 창)"}
                    >
                      {contents}
                    </a>
                  ) : (
                    <div className="member-ranking-row">{contents}</div>
                  )}
                </li>
              );
            })}
          </ol>
        </>
      ) : (
        <Empty>이 조건에서 비교할 수 있는 자료가 없습니다.</Empty>
      )}
      {showNote && <p className="member-ranking-note">{ranking.scope.note}</p>}
    </section>
  );
}

function AssetSource({
  data,
  children,
}: {
  data: RankingsData;
  children?: ReactNode;
}) {
  return (
    <SourceNote>
      {children || "신고대상 가족을 포함하고 고지거부 재산은 제외합니다."}{" "}
      정당·지역구는 공개자료의 표기로 현재 소속과 다를 수 있습니다.{" "}
      {data.assetSource.url && (
        <External url={data.assetSource.url}>
          {data.assetSource.title || "재산공개 원자료"}
        </External>
      )}
    </SourceNote>
  );
}

export function MemberRankings({
  view,
  navigation,
}: {
  view: RankingView;
  navigation: ReactNode;
}) {
  const { params } = useLocation();
  const meta = useMeta();
  const report = params.get("report") || "ka:2024-22";
  const party = params.get("party") || "";
  const resource = useResource<RankingsData>(
    "member-rankings?" +
      query({ report, party: view === "parties" ? "" : party }),
  );
  const data = resource.data;
  const updateFilters = (values: Record<string, string>) => {
    const toolbar = document.querySelector<HTMLElement>(".members-toolbar");
    const result = document.querySelector<HTMLElement>(
      view === "parties"
        ? ".member-party-comparison .member-ranking-card"
        : ".members-results",
    );
    const top =
      toolbar && result
        ? Math.max(
            0,
            window.scrollY +
              result.getBoundingClientRect().top -
              toolbar.offsetHeight -
              16,
          )
        : null;
    changeFilters(values);
    if (top !== null && (view === "parties" || window.scrollY > top))
      window.scrollTo({ top });
  };
  const parties = data?.parties || meta.parties;
  const metrics = data
    ? [
        { id: "net", label: "신고 순재산", ranking: data.assets },
        ...[
          "realestate",
          "land",
          "buildings",
          "securities",
          "deposits",
          "cash",
          "crypto",
          "debt",
        ].flatMap((id) => {
          const ranking = data.assetCategories.find((item) => item.id === id);
          return ranking ? [{ id, label: ranking.label, ranking }] : [];
        }),
        ...data.assetConcentration.map((ranking) => ({
          id: "share-" + ranking.id,
          label: ranking.label,
          ranking,
        })),
      ]
    : [];
  const selectedMetric =
    metrics.find((item) => item.id === params.get("asset")) || metrics[0];
  const partyGroups = data?.partyAssets || [];
  const selectedParty =
    party || data?.partyWealth.rows[0]?.party || partyGroups[0]?.party || "";
  const selectedGroup = partyGroups.find(
    (group) => group.party === selectedParty,
  );
  const partyOptions = partyGroups.map((group) => ({
    value: group.party,
    label: group.party + " · " + count(group.n) + "명",
  }));
  if (
    selectedParty &&
    !partyOptions.some((option) => option.value === selectedParty)
  ) {
    partyOptions.push({
      value: selectedParty,
      label: selectedParty + " · 수록 자료 없음",
    });
  }
  const scopeLabel =
    view === "funds"
      ? (meta.reports.find((item) => item.id === report)?.period || report) +
        " 정치자금 회계자료"
      : view === "changes"
        ? data?.assetChanges.increases.scope.label || "연간 증감 자료"
        : data
          ? (data.assetSource.basis || "기준일 미기재") + " 재산공개 기준"
          : resource.error
            ? "재산 자료를 확인해 주세요"
            : "재산 자료를 불러오는 중";
  return (
    <>
      <div className="members-toolbar">
        {navigation}
        <div className="members-controls">
          {view === "assets" && (
            <div className="member-field">
              <span aria-hidden="true">재산 지표</span>
              <Select
                label="재산 지표"
                value={selectedMetric?.id || "net"}
                options={
                  metrics.length
                    ? metrics.map((item) => ({
                        value: item.id,
                        label: item.label,
                      }))
                    : [{ value: "net", label: "신고 순재산" }]
                }
                onChange={(asset) => updateFilters({ asset })}
              />
            </div>
          )}
          {view !== "parties" ? (
            <div className="member-field">
              <span aria-hidden="true">비교 정당</span>
              <Select
                label="순위 정당"
                value={party}
                options={[
                  { value: "", label: "전체 정당" },
                  ...parties.map((name) => ({ value: name, label: name })),
                ]}
                onChange={(party) => updateFilters({ party })}
              />
            </div>
          ) : (
            <div className="member-field">
              <span aria-hidden="true">Top 10 정당</span>
              <Select
                label="Top 10 정당"
                value={selectedParty}
                options={
                  partyOptions.length
                    ? partyOptions
                    : [{ value: "", label: "정당 자료 불러오는 중" }]
                }
                onChange={(party) => updateFilters({ party })}
              />
            </div>
          )}
          {view === "funds" && (
            <div className="member-field member-report-field">
              <span aria-hidden="true">회계보고분</span>
              <Select
                label="지출·수입 비교 대상 보고자료"
                value={report}
                options={meta.reports.map((item) => ({
                  value: item.id,
                  label: shortReportLabel(item.id, item.title),
                }))}
                onChange={(report) => updateFilters({ report, month: "" })}
              />
            </div>
          )}
          <p className="members-basis">{scopeLabel}</p>
        </div>
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <div
          className="members-results"
          role="tabpanel"
          aria-label={
            {
              assets: "재산 순위",
              changes: "연간 증감",
              funds: "정치자금",
              parties: "정당 비교",
            }[view]
          }
        >
          {view === "assets" && selectedMetric && (
            <>
              <RankingBoard
                title={selectedMetric.label + " Top 10"}
                ranking={selectedMetric.ranking}
                report={report}
                assetUrl={data.assetSource.url}
                showScope={false}
              />
              <AssetSource data={data} />
            </>
          )}
          {view === "changes" && (
            <>
              <div className="section-heading members-view-heading">
                <h2>
                  {data.assetChanges.year
                    ? data.assetChanges.year + "년 연간 재산 증감"
                    : "연간 재산 증감"}
                </h2>
                <p>
                  {data.assetChanges.year
                    ? "수집된 최신 연말 공보의 전년 말 대비 값입니다. 현재는 " +
                      data.assetChanges.year +
                      "년 자료만 제공됩니다."
                    : "연간 비교 기준일을 확인할 수 없습니다."}
                </p>
              </div>
              <div className="two-columns asset-change-rankings">
                <RankingBoard
                  title="재산 증가 Top 10"
                  ranking={data.assetChanges.increases}
                  report={report}
                  assetUrl={data.assetSource.url}
                  level={3}
                  showNote={false}
                  showScope={false}
                />
                <RankingBoard
                  title="재산 감소 Top 10"
                  ranking={data.assetChanges.decreases}
                  report={report}
                  assetUrl={data.assetSource.url}
                  level={3}
                  showNote={false}
                  showScope={false}
                />
              </div>
              <AssetSource data={data}>
                {data.assetChanges.increases.scope.note}
              </AssetSource>
            </>
          )}
          {view === "funds" && (
            <>
              <div className="section-heading members-view-heading">
                <h2>정치자금 수입·지출 순위</h2>
                <p>
                  지출은 선택한 회계보고분, 수입은 해당 연도 합계입니다.
                  정당·지역구는 자료의 표기로 현재 소속과 다를 수 있습니다.
                </p>
              </div>
              <div className="two-columns member-fund-rankings">
                <RankingBoard
                  title="지출 Top 10"
                  ranking={data.spending}
                  report={report}
                  level={3}
                />
                <RankingBoard
                  title="정치자금 수입 Top 10"
                  ranking={data.politicalIncome}
                  report={report}
                  level={3}
                />
              </div>
              <SourceNote>
                정치자금 수입은 후원금·차입금·본인 자산 등을 포함합니다. 개인
                연간 소득으로 계산하지 않습니다.{" "}
                <Link href="/sources">집계 기준과 출처 확인</Link>
              </SourceNote>
            </>
          )}
          {view === "parties" && (
            <>
              <div className="section-heading members-view-heading">
                <h2>정당별 신고재산 비교</h2>
                <p>
                  중앙값은 전체 정당을 비교하고, Top 10은 선택한 정당 안에서
                  비교합니다.
                </p>
              </div>
              <div className="member-party-comparison">
                <section className="panel member-party-medians">
                  <h3>전체 정당 순재산 중앙값</h3>
                  <p className="caption">
                    공보에 수록된 인원 기준 · 정당을 선택하면 Top 10이 바뀝니다.
                  </p>
                  {data.partyWealth.rows.length ? (
                    <div className="table-scroll party-wealth-ranking">
                      <table>
                        <thead>
                          <tr>
                            <th>순위</th>
                            <th>정당</th>
                            <th className="numeric right">수록 인원</th>
                            <th className="numeric right">중앙값</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.partyWealth.rows.map((row) => (
                            <tr
                              key={row.party}
                              className={
                                row.party === selectedParty
                                  ? "selected-party"
                                  : ""
                              }
                            >
                              <td className="numeric">{row.rank}</td>
                              <td>
                                <Link
                                  href={href("/members", {
                                    view: "parties",
                                    party: row.party,
                                    report,
                                    asset: params.get("asset"),
                                  })}
                                  aria-current={
                                    row.party === selectedParty
                                      ? "true"
                                      : undefined
                                  }
                                >
                                  {row.party}
                                </Link>
                              </td>
                              <td className="numeric right">
                                {count(row.n)}명
                              </td>
                              <td
                                className="numeric right"
                                title={won(row.median)}
                              >
                                {shortWon(row.median)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty>중앙값을 비교할 신고재산 자료가 없습니다.</Empty>
                  )}
                </section>
                {selectedGroup ? (
                  <RankingBoard
                    title={selectedParty + " 재산 Top 10"}
                    ranking={selectedGroup}
                    report={report}
                    assetUrl={data.assetSource.url}
                    level={3}
                    showNote={false}
                    showScope={false}
                  />
                ) : (
                  <Empty>선택한 정당에 연결된 신고재산 자료가 없습니다.</Empty>
                )}
              </div>
              <AssetSource data={data}>
                {data.assets.scope.note} 정당별 중앙값은 전체 수록 인원으로
                계산합니다. 10명 미만인 정당은 수록된 인원만 표시합니다.
              </AssetSource>
            </>
          )}
        </div>
      )}
    </>
  );
}
