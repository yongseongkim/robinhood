import { useEffect, useState } from "react";
import { ChevronRight, Utensils } from "lucide-react";
import { query, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { confidence, count, shortWon, won } from "../format";
import { PlaceMap } from "../components/maps";
import {
  Empty,
  External,
  KeyValues,
  MonthlyChart,
  Notice,
  PageHeader,
  Pagination,
  Panel,
  RangeControls,
  ResourceState,
  ScopeBar,
  Section,
  SearchForm,
  Select,
  SourceNote,
  Stat,
  Tabs,
  Transactions,
} from "../components/ui";
import type {
  Place,
  PlaceDetail as PlaceDetailData,
  Places as PlacesData,
  Scope,
} from "../types";

function periodLabel(scope: Scope) {
  if (scope.start === "2023-01-01" && scope.end === "2024-12-31")
    return "2년 합계";
  return scope.kind === "annual"
    ? "연간 합계"
    : scope.kind === "monthly"
      ? "월 합계"
      : "기간 합계";
}
function placeFilters(params: URLSearchParams) {
  const funding = params.get("fundingType") || "POLITICAL_FUND";
  return {
    funding,
    start:
      params.get("start") ||
      (funding === "POLITICAL_FUND" ? "2023-01-01" : "2024-01-01"),
    end: params.get("end") || "2024-12-31",
  };
}
function FundingTabs({ funding }: { funding: string }) {
  return (
    <Tabs
      value={funding}
      items={[
        { value: "POLITICAL_FUND", label: "정치자금" },
        { value: "COUNCIL_OPERATION", label: "의회 경비" },
      ]}
      onChange={(fundingType) =>
        changeFilters({
          fundingType,
          start: fundingType === "POLITICAL_FUND" ? "2023-01-01" : "2024-01-01",
          end: "2024-12-31",
          page: "",
        })
      }
    />
  );
}
function PlaceCard({ place, scope }: { place: Place; scope: Scope }) {
  return (
    <Link
      className="place-card"
      href={href("/places/" + place.id, {
        fundingType: scope.fundingType,
        start: scope.start,
        end: scope.end,
      })}
    >
      <div className="place-card-heading">
        <span className="place-category-icon">
          <Utensils size={19} />
        </span>
        <div>
          <h3>{place.name}</h3>
          <p>{place.region || "지역 미기재"} · 공개된 식사 기록</p>
        </div>
        <ChevronRight size={17} />
      </div>
      <div className="place-card-figures">
        <span>
          <b>{count(place.payments)}</b>건
        </span>
        <small>{count(place.payerCount)}명 명의 보고서</small>
        <span className="numeric">
          {periodLabel(scope)} {shortWon(place.amount)}
        </span>
      </div>
    </Link>
  );
}
function useNarrow() {
  const [narrow, setNarrow] = useState(
    () => window.matchMedia("(max-width: 700px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(max-width: 700px)");
    const change = () => setNarrow(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return narrow;
}
export function Places() {
  const { params } = useLocation();
  const { funding, start, end } = placeFilters(params);
  const narrow = useNarrow();
  const region = params.get("region") || "서울 영등포구",
    q = params.get("q") || "",
    sort = params.get("sort") || "payments";
  const resource = useResource<PlacesData>(
    "places?" +
      query({
        fundingType: funding,
        start,
        end,
        region,
        q,
        sort,
        page: params.get("page") || 1,
        pageSize: narrow ? 3 : 6,
      }),
  );
  const data = resource.data;
  return (
    <div className="page stack places-page">
      <PageHeader
        title="자주 결제한 장소"
        context="비교와 장소"
        description="공개 지출의 결제 기록이 많은 곳을 지역별로 확인합니다."
      />
      <div className="subnav">
        <Link href="/rankings">비교·랭킹</Link>
        <Link className="active" href="/places">
          자주 결제한 장소
        </Link>
      </div>
      <div className="filters">
        <FundingTabs funding={funding} />
        <RangeControls
          start={start}
          end={end}
          onChange={(start, end) => changeFilters({ start, end })}
        />
        <Select
          label="장소 정렬"
          value={sort}
          options={[
            { value: "payments", label: "결제 기록 많은 순" },
            { value: "amount", label: "순지출 많은 순" },
            { value: "payers", label: "여러 보고서에 나온 순" },
          ]}
          onChange={(sort) => changeFilters({ sort })}
        />
      </div>
      {!data ? (
        <ResourceState {...resource} />
      ) : (
        <>
          <ScopeBar scope={data.scope} />
          <div className="places-explorer">
            <section className="place-map-column">
              <div className="map-heading">
                <span>지역별 결제 장소</span>
                <small>숫자는 구별 거래처 수</small>
              </div>
              <PlaceMap
                clusters={data.clusters}
                region={region}
                onRegion={(region) => changeFilters({ region })}
                onRefresh={resource.retry}
              />
              <p className="caption map-precision">
                가게의 정확한 좌표가 없어 구별 묶음으로 표시합니다. 실제 방문자
                수와는 다릅니다.
              </p>
            </section>
            <section className="place-sidebar" aria-label="지역 장소 목록">
              <div className="sheet-handle" />
              <SearchForm
                value={q}
                placeholder="가게 이름 또는 지역 검색"
                onSearch={(q) => changeFilters({ q })}
              />
              <div className="place-results-title">
                <h2>
                  {region} · {count(data.total)}곳
                </h2>
                <Select
                  label="장소 지역"
                  value={region}
                  options={[
                    { value: "서울", label: "서울 전체" },
                    ...data.clusters
                      .filter((c) => c.region.startsWith("서울 "))
                      .sort((a, b) => a.region.localeCompare(b.region, "ko"))
                      .map((c) => ({
                        value: c.region,
                        label: c.region.replace("서울 ", ""),
                      })),
                  ]}
                  onChange={(region) => changeFilters({ region })}
                />
              </div>
              <p className="caption">
                {data.scope.start}–{data.scope.end} · {periodLabel(data.scope)}{" "}
                · 결제 {count(data.summary.payments)}건
              </p>
              <div className="place-card-list">
                {data.rows.map((p) => (
                  <PlaceCard key={p.id} place={p} scope={data.scope} />
                ))}
                {!data.rows.length && (
                  <Empty>
                    이 기간·지역에서 조건에 맞는 장소가 없습니다. 지역이나
                    기간을 바꿔 주세요.
                  </Empty>
                )}
              </div>
              <Pagination
                {...data}
                onChange={(page) => changeFilters({ page })}
              />
            </section>
          </div>
          <div className="three-columns discovery-panels">
            <Panel title="여러 보고서에 나온 가게">
              <p className="caption">
                동일 거래처가 몇 명의 보고 명의에 등장했는지 확인합니다.
              </p>
              <button
                className="text-link"
                onClick={() => changeFilters({ sort: "payers" })}
              >
                보고 명의 수로 보기 →
              </button>
            </Panel>
            <Panel title="결제 금액으로 비교">
              <p className="caption">
                취소·반환을 반영한 선택 기간 순지출을 봅니다.
              </p>
              <button
                className="text-link"
                onClick={() => changeFilters({ sort: "amount" })}
              >
                순지출로 보기 →
              </button>
            </Panel>
            <Panel title="기간을 맞춰 확인">
              <p className="caption">
                정치자금 2023–2024 합계와 의회 경비 2024 합계를 구분합니다.
              </p>
              <Link className="text-link" href="/sources">
                집계 기준 확인 →
              </Link>
            </Panel>
          </div>
          <SourceNote>
            중복·취소 짝을 제외한 양수 거래를 결제 건수로 셉니다. 순지출은
            반환을 반영합니다. 실제 결제자·방문자와 영업 여부는 확인되지
            않았습니다.
          </SourceNote>
        </>
      )}
    </div>
  );
}

export function PlaceDetail({ id }: { id: string }) {
  const { params } = useLocation();
  const { funding, start, end } = placeFilters(params);
  const resource = useResource<PlaceDetailData>(
    "places/" +
      encodeURIComponent(id) +
      "?" +
      query({
        fundingType: funding,
        start,
        end,
        page: params.get("page") || 1,
      }),
  );
  const data = resource.data;
  const [chartYear, setChartYear] = useState("2024"),
    [allPayers, setAllPayers] = useState(false);
  useEffect(() => {
    if (data) setChartYear(data.scope.end.slice(0, 4));
  }, [data?.scope.end]);
  if (!data) return <ResourceState {...resource} />;
  const years = [...new Set(data.monthly.map((m) => m.month.slice(0, 4)))]
    .sort()
    .reverse();
  const months = data.monthly.filter((m) => m.month.startsWith(chartYear));
  const merchant = data.merchant;
  const aggregate = periodLabel(data.scope);
  return (
    <div className="page stack merchant-page">
      <Link
        className="back-link"
        href={href("/places", {
          region: merchant.region || "서울",
          fundingType: funding,
          start,
          end,
        })}
      >
        ← 지역 지도
      </Link>
      <PageHeader
        title={merchant.name}
        context="장소 상세"
        description={(merchant.region || "지역 미기재") + " · 공개된 식사 기록"}
      />
      <Notice>
        가게 좌표 미확인 · 시·군·구까지만 확인됩니다. 보고 명의자가 직접
        결제·방문했는지는 알 수 없습니다.
      </Notice>
      <div className="filters">
        <FundingTabs funding={funding} />
        <RangeControls
          start={start}
          end={end}
          onChange={(start, end) => changeFilters({ start, end })}
        />
      </div>
      <ScopeBar scope={data.scope} />
      <div className="metrics">
        <Stat
          accent
          label={aggregate + " 결제 건수"}
          value={count(data.summary.payments) + "건"}
          detail="중복·취소 짝 제외"
        />
        <Stat
          label={aggregate + " 순지출"}
          value={shortWon(data.summary.amount)}
          exact={data.summary.amount}
          detail={won(data.summary.amount)}
        />
        <Stat
          label="등장하는 보고 명의"
          value={count(data.payerCount) + "명"}
          detail={aggregate + " · 실제 방문 인원과 구분"}
        />
        <Stat
          label="반환 거래"
          value={count(data.refunds) + "건"}
          detail={aggregate + " · 반환 금액을 순지출에 반영"}
        />
      </div>
      <div className="merchant-columns">
        <div className="stack">
          <Panel
            title="누구의 보고서에 등장하나"
            description={aggregate + " · 결제 건수순"}
          >
            {data.payers.length ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>보고 명의</th>
                      <th className="right">결제</th>
                      <th className="right">{aggregate} 순지출</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.payers
                      .slice(0, allPayers ? undefined : 5)
                      .map((p) => (
                        <tr key={p.id}>
                          <td>
                            <Link
                              href={href("/members/" + p.id, {
                                report:
                                  funding === "POLITICAL_FUND"
                                    ? p.subject.reports?.[0] || "ka:2024-22"
                                    : undefined,
                                year: end.slice(0, 4),
                                fundingType: funding,
                              })}
                            >
                              {p.subject.name}
                            </Link>
                          </td>
                          <td className="right numeric">
                            {count(p.payments)}건
                          </td>
                          <td className="right numeric" title={won(p.amount)}>
                            {shortWon(p.amount)}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>선택 기간과 재원에 식사 기록이 없습니다.</Empty>
            )}
            {data.payers.length > 5 && (
              <button
                className="button-link"
                onClick={() => setAllPayers((v) => !v)}
              >
                {allPayers ? "접기" : count(data.payerCount) + "명 전체 보기"}
              </button>
            )}
          </Panel>
          <Panel
            title="월별 결제 건수"
            description={
              chartYear +
              "년 · 선택 범위의 월별 건수 · 합계 " +
              count(months.reduce((s, m) => s + m.payments, 0)) +
              "건"
            }
          >
            <Select
              label="월별 그래프 연도"
              value={chartYear}
              options={years.map((y) => ({ value: y, label: y + "년" }))}
              onChange={setChartYear}
            />
            <MonthlyChart data={months} mode="payments" />
          </Panel>
        </div>
        <aside className="stack">
          <Panel
            title="위치는 어디까지 확인했나"
            description={merchant.region || "소재지 미기재"}
          >
            {merchant.region?.startsWith("서울 ") && (
              <PlaceMap region={merchant.region} compact />
            )}
            <p className="caption">
              지역 대표 위치입니다. 가게의 핀이나 거리로 표시하지 않습니다.
            </p>
            <External
              url={
                merchant.region
                  ? "https://map.naver.com/p/search/" +
                    encodeURIComponent(merchant.region)
                  : undefined
              }
            >
              네이버 지도에서 지역 보기
            </External>
          </Panel>
          <Panel title="같은 거래처로 연결한 근거">
            <KeyValues
              rows={[
                ["상호 연결 신뢰도", confidence(merchant.confidence)],
                [
                  "연결 근거",
                  merchant.confidence === "HIGH"
                    ? "사업자번호 기준"
                    : merchant.confidence === "MEDIUM"
                      ? "상호명과 지역 기준"
                      : "상호명 기준",
                ],
                ["상호 변형", merchant.aliases.join(" · ") || "추가 표기 없음"],
                ["사업자번호", merchant.businessNumber || "미수집"],
              ]}
            />
            <p className="caption">
              상호 연결 신뢰도와 위치 정확도는 별개입니다.
            </p>
          </Panel>
        </aside>
      </div>
      <Section
        title="출처 거래 내역"
        description="날짜와 건별 금액, 목적을 확인합니다. 금액은 각 거래 1건입니다."
      >
        <Transactions rows={data.transactions.rows} showSubject />
        <Pagination
          {...data.transactions}
          onChange={(page) => changeFilters({ page })}
        />
      </Section>
      <SourceNote>
        정치자금과 의회 경비는 별도 재원으로 집계합니다. 식사 기록의 분류·상호
        연결에는 오류가 있을 수 있어 인용 전 원자료를 확인해야 합니다.
      </SourceNote>
    </div>
  );
}
