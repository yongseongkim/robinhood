import { query, useMeta, useResource } from "../api";
import { count, shortWon, won } from "../format";
import { changeFilters, href, Link, useLocation } from "../router";
import type { MemberRankings as RankingsData, Ranking } from "../types";
import {
  Empty,
  External,
  Notice,
  Panel,
  ResourceState,
  Section,
  Select,
  SourceNote,
} from "./ui";

function RankingList({
  ranking,
  report,
  assetUrl,
}: {
  ranking: Ranking;
  report: string;
  assetUrl?: string;
}) {
  if (!ranking.rows.length)
    return <Empty>이 조건에서 비교할 수 있는 자료가 없습니다.</Empty>;
  return (
    <ol className="member-ranking-list" aria-label="상위 10명">
      {ranking.rows.map((row) => {
        const destination = row.id
          ? href("/members/" + row.id, {
              report,
              tab: ranking.target === "assets" ? "assets" : "money",
            })
          : undefined;
        return (
          <li key={row.id || row.name}>
            <span className="member-ranking-position numeric">{row.rank}</span>
            <div className="member-ranking-person">
              {destination ? (
                <Link href={destination}>{row.name}</Link>
              ) : assetUrl ? (
                <External
                  url={assetUrl + (row.page ? "#page=" + row.page : "")}
                >
                  {row.name}
                </External>
              ) : (
                <span>{row.name}</span>
              )}
              <small>
                {row.party || "정당 미기재"}
                {row.district && " · " + row.district}
              </small>
            </div>
            <span
              className="member-ranking-value numeric"
              title={won(row.value)}
            >
              {shortWon(row.value)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function RankingCard({
  title,
  ranking,
  report,
  assetUrl,
}: {
  title: string;
  ranking: Ranking;
  report: string;
  assetUrl?: string;
}) {
  return (
    <Panel
      className="member-ranking-card"
      title={title}
      description={ranking.scope.label}
    >
      <div className="member-ranking-summary">
        <span>비교 대상 {count(ranking.n)}명</span>
        <span>
          중앙값 <strong>{shortWon(ranking.median)}</strong>
        </span>
      </div>
      <RankingList ranking={ranking} report={report} assetUrl={assetUrl} />
      <p className="caption">{ranking.scope.note}</p>
    </Panel>
  );
}

export function MemberRankings() {
  const { params } = useLocation();
  const meta = useMeta();
  const report = params.get("report") || "ka:2024-22";
  const party = params.get("party") || "";
  const resource = useResource<RankingsData>(
    "member-rankings?" + query({ report, party }),
  );
  const data = resource.data;
  const parties = data?.parties || meta.parties;
  return (
    <>
      <div className="filters">
        <Select
          label="순위 정당"
          value={party}
          options={[
            { value: "", label: "정당 · 전체" },
            ...parties.map((name) => ({ value: name, label: name })),
          ]}
          onChange={(party) => changeFilters({ party })}
        />
        <Select
          label="지출·수입 비교 대상 보고자료"
          value={report}
          options={meta.reports.map((item) => ({
            value: item.id,
            label: item.title,
          }))}
          onChange={(report) => changeFilters({ report, month: "" })}
        />
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <Notice>
            지출·수입은 선택한 회계자료, 재산은 별도 신고 기준일로 비교합니다.
            정당·지역구는 자료에 연결된 표기로 현재 소속과 다를 수 있습니다.
          </Notice>
          <div className="three-columns member-rankings">
            <RankingCard
              title="지출 순위 Top 10"
              ranking={data.spending}
              report={report}
            />
            <RankingCard
              title="신고재산 순위 Top 10"
              ranking={data.assets}
              report={report}
              assetUrl={data.assetSource.url}
            />
            <RankingCard
              title="정치자금 수입 순위 Top 10"
              ranking={data.politicalIncome}
              report={report}
            />
          </div>
          <Section
            title="정당별 신고재산 Top 10"
            description={
              data.assets.scope.label +
              " · 각 정당 안에서 비교하며 자료가 10명 미만이면 수록된 인원만 표시합니다."
            }
          >
            {data.partyAssets.length ? (
              <div className="two-columns party-asset-rankings">
                {data.partyAssets.map((group) => (
                  <RankingCard
                    key={group.party}
                    title={group.party + " 재산 Top 10"}
                    ranking={group}
                    report={report}
                    assetUrl={data.assetSource.url}
                  />
                ))}
              </div>
            ) : (
              <Empty>선택한 정당에 연결된 신고재산 자료가 없습니다.</Empty>
            )}
          </Section>
          <SourceNote>
            재산은 신고대상 가족을 포함한 순재산이며 고지거부 재산은 제외합니다.
            재산 증가액은 개인 소득으로 계산하지 않습니다.{" "}
            {data.assetSource.url && (
              <External url={data.assetSource.url}>
                {data.assetSource.title || "재산공개 원자료"}
              </External>
            )}
          </SourceNote>
        </>
      )}
    </>
  );
}
