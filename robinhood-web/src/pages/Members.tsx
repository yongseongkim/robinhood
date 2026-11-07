import { query, useMeta, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, shortWon, won } from "../format";
import {
  Empty,
  PageHeader,
  Pagination,
  ReportControls,
  reportDates,
  ResourceState,
  ScopeBar,
  SearchForm,
  Select,
  SourceNote,
  Stat,
  Tabs,
} from "../components/ui";
import type { MemberPage } from "../types";
import { MemberRankings } from "../components/MemberRankings";

export function Members() {
  const { params } = useLocation();
  const listRequested = ["q", "region", "sort", "page", "month"].some((key) =>
    params.has(key),
  );
  const view = params.get("view") || (listRequested ? "list" : "rankings");
  return (
    <div className="page stack members-page">
      <PageHeader
        title="의원·정당 찾아보기"
        context="의원과 정당"
        description="의원별 지출·신고재산·정치자금 수입 순위와 정당별 재산 Top 10을 비교합니다."
      />
      <Tabs
        value={view}
        items={[
          { value: "rankings", label: "순위 한눈에" },
          { value: "list", label: "의원 목록" },
        ]}
        onChange={(view) =>
          changeFilters({ view, q: "", region: "", sort: "", month: "" })
        }
      />
      {view === "list" ? <MemberList /> : <MemberRankings />}
    </div>
  );
}

function MemberList() {
  const { params } = useLocation();
  const meta = useMeta();
  const report = params.get("report") || "ka:2024-22",
    party = params.get("party") || "",
    q = params.get("q") || "",
    region = params.get("region") || "",
    sort = params.get("sort") || "name";
  const request = query({
    report,
    party,
    q,
    region,
    sort,
    page: params.get("page") || 1,
    ...reportDates(params),
  });
  const resource = useResource<MemberPage>("members?" + request);
  const data = resource.data;
  return (
    <>
      <div className="filters">
        <SearchForm
          value={q}
          placeholder="의원 이름 또는 지역구 검색"
          onSearch={(q) => changeFilters({ q })}
        />
        <Select
          label="정당"
          value={party}
          options={[
            { value: "", label: "정당 · 전체" },
            ...meta.parties.map((p) => ({ value: p, label: p })),
          ]}
          onChange={(party) => changeFilters({ party })}
        />
        <ReportControls params={params} />
        <Select
          label="목록 정렬"
          value={sort}
          options={[
            { value: "name", label: "이름순" },
            { value: "amount", label: "지출 많은 순" },
          ]}
          onChange={(sort) => changeFilters({ sort })}
        />
        {region && (
          <button
            className="chip"
            onClick={() => changeFilters({ region: "" })}
          >
            {region} ×
          </button>
        )}
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <ScopeBar scope={data.scope} />
          <div className="metrics">
            <Stat
              accent
              label="지출 보고자"
              value={count(data.total) + "명"}
              detail={data.scope.label}
            />
            <Stat
              label="보고분 지출 합계"
              value={shortWon(data.summary.amount)}
              exact={data.summary.amount}
              detail="정치자금 · 선택한 조건의 보고분"
            />
            <Stat
              label="의원별 지출 중앙값"
              value={shortWon(data.median)}
              exact={data.median}
              detail="동일 보고 범위의 보고자 기준"
            />
            <Stat
              label="보고분 거래"
              value={count(data.summary.count) + "건"}
              detail="재수록 중복 제외 · 반환액 반영"
            />
          </div>
          {data.rows.length ? (
            <div className="table-scroll">
              <table>
                <caption className="sr-only">
                  선택한 보고 범위의 의원 지출 목록
                </caption>
                <thead>
                  <tr>
                    <th>의원</th>
                    <th>정당</th>
                    <th>지역구</th>
                    <th className="right">보고분 지출 합계</th>
                    <th className="right">거래</th>
                    <th>상세</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <Link
                          href={href("/members/" + m.id, {
                            report,
                            month: params.get("month"),
                          })}
                        >
                          {m.name}
                        </Link>
                      </td>
                      <td>{m.party || "미기재"}</td>
                      <td>{m.district || "미기재"}</td>
                      <td className="numeric right" title={won(m.amount)}>
                        {shortWon(m.amount)}
                      </td>
                      <td className="numeric right">{count(m.count)}건</td>
                      <td>
                        <Link
                          className="text-link"
                          href={href("/members/" + m.id, {
                            report,
                            month: params.get("month"),
                          })}
                        >
                          지출·재산·활동 →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>
              조건에 맞는 보고자가 없습니다. 검색어·정당·기간을 바꿔 주세요.
            </Empty>
          )}
          <Pagination
            page={data.page}
            pageSize={data.pageSize}
            total={data.total}
            onChange={(page) => changeFilters({ page })}
          />
          <SourceNote>
            {data.scope.note} 정당은 해당 회계자료에 연결된 표기이며, 현직 의원
            명부와 기준 시점이 다릅니다.
          </SourceNote>
        </>
      )}
    </>
  );
}
