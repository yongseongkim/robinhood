import { useState } from "react";
import { query, useMeta, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, won } from "../format";
import {
  Empty,
  External,
  KeyValues,
  Notice,
  PageHeader,
  Panel,
  Pagination,
  ResourceState,
  SearchForm,
  Section,
  Select,
  SourceNote,
  Stat,
  Tabs,
} from "../components/ui";
import type { Finding, Sources as SourcesData } from "../types";

const referenceNames: Record<string, string> = {
  REGULATORY: "법령 기준 대조",
  STATISTICAL: "통계 비교",
  EXACT_MATCH: "반복·중복 패턴",
  KEYWORD: "상호·내용 단어",
  DISCLOSURE: "공개·자료 품질",
};
const observedLabels: Record<string, string> = {
  transactionCount: "거래 건수",
  totalAmount: "거래 합계",
  maxAmount: "최대 금액",
  maxPerPerson: "최대 1인당 금액",
  maxRatio: "기준 대비 최대 배수",
  occurrences: "발생 횟수",
  ratioToMedian: "중앙값 대비 배수",
  evidenceCount: "근거 거래 수",
};
const moneyKeys = new Set(["totalAmount", "maxAmount", "maxPerPerson"]);

export function Sources() {
  const resource = useResource<SourcesData>("sources");
  const data = resource.data;
  const meta = useMeta();
  const { params } = useLocation();
  const tab = params.get("tab") || "data";
  const [q, setQ] = useState("");
  const funding = params.get("fundingType") || "COUNCIL_OPERATION";
  const page = Number(params.get("page")) || 1;
  const findings = useResource<{
    rows: Finding[];
    total: number;
    page: number;
    pageSize: number;
  }>(
    tab === "findings"
      ? "findings?" + query({ fundingType: funding, q, page })
      : null,
  );
  if (!data) return <ResourceState {...resource} />;
  const total = Object.values(data.counts).reduce((s, v) => s + v, 0);
  return (
    <div className="page stack">
      <PageHeader
        title="데이터와 확인 방법"
        context="기록과 출처"
        description="공개 항목·자료 범위·분석 기준을 확인하고 원자료로 이동합니다."
      />
      <Tabs
        value={tab}
        items={[
          { value: "data", label: "수집 데이터" },
          { value: "sources", label: "출처와 범위" },
          { value: "methods", label: "분석 기준" },
          { value: "findings", label: "다시 볼 표시" },
        ]}
        onChange={(tab) => changeFilters({ tab })}
      />
      {tab === "data" && (
        <>
          <div className="metrics">
            <Stat
              accent
              label="수집된 거래"
              value={count(total) + "건"}
              detail="재수록 중복 제외 · 여러 재원의 건수"
            />
            <Stat
              label="정치자금 거래"
              value={count(data.counts.POLITICAL_FUND) + "건"}
              detail="2023–2024 수집 자료"
            />
            <Stat
              label="출처 문서"
              value={count(meta.documents) + "개"}
              detail="각 기록에서 원문으로 연결"
            />
            <Stat
              label="연결된 거래처"
              value={count(meta.merchants) + "개"}
              detail="상호·사업자번호 등으로 연결"
            />
          </div>
          <div className="two-columns">
            {[
              [
                "정치자금",
                "날짜·금액·목적·재원 계정·결제수단·영수증 번호·거래처·원문 연번",
                "보고분 합계, 월별·항목별 지출, 반환 반영 순지출",
                "시각·인원수·영수증 이미지",
              ],
              [
                "지방의회 경비",
                "날짜·시각·금액·목적·기재 인원·결제수단·예산 항목·직책·임기",
                "직책·기간별 집행, 기재 인원당 금액, 집계 개월",
                "실제 결제자·참석자 명단·개인 전체 지출",
              ],
              [
                "신고재산",
                "전년·당년 가액·관계·소재지·면적·임차권·변동 사유",
                "신고액 증감, 종류별 비교, 부동산 항목별 비교",
                "실거래 시세·개인 소득·매매 차익",
              ],
              [
                "법안·표결",
                "법안명·번호·발의일·위원회·처리 결과·표결일·안건·선택",
                "발의 건수, 찬반·기권·불참 집계, 참여율",
                "표결·불참 사유·활동의 질 점수",
              ],
              [
                "장소·거래처",
                "상호 변형·시군구·연결 근거·출처·관련 거래",
                "기간 순지출, 결제 건수, 보고 명의 수",
                "정확한 가게 좌표·거리·현재 영업·실제 방문자",
              ],
              [
                "국가재정",
                "연도·통계 기준·수입·지출·분야·부처·재정수지·채무",
                "결산과 예산을 나눈 추이, 구성과 재정수지 비교",
                "지방자치단체 전체 수입·결산",
              ],
            ].map(([title, raw, calculated, missing]) => (
              <Panel key={title} title={title}>
                <p>수집 항목 · {raw}</p>
                <p className="caption blue-text">계산 가능 · {calculated}</p>
                <p className="caption">현재 없는 항목 · {missing}</p>
              </Panel>
            ))}
          </div>
          <Section
            title="비어 있는 항목은 0으로 채우지 않습니다"
            description="중복을 제외한 전체 수집본에서 해당 필드가 존재하는 비율입니다."
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>재원</th>
                    <th>거래 건수</th>
                    <th>시각</th>
                    <th>인원수</th>
                    <th>결제수단</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.fields).map(([fund, f]) => (
                    <tr key={fund}>
                      <td>{meta.fundingTypes[fund]?.label}</td>
                      <td>{count(f.count)}</td>
                      {[f.time, f.attendees, f.payment].map((v, i) => (
                        <td key={i}>{((v / f.count) * 100).toFixed(1)}%</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
      {tab === "sources" && (
        <>
          <Notice>
            조회자료 구성 시각{" "}
            {new Date(data.indexedAt).toLocaleString("ko-KR")}. 원자료의
            수집·공개 시각과는 구분합니다.
          </Notice>
          <Section title="수집 출처와 거래 수록 기간">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>출처</th>
                    <th>거래 수록 기간</th>
                    <th>중복 제외 거래</th>
                    <th>문서</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.source}>
                      <td>{s.name}</td>
                      <td>
                        {s.firstDate}–{s.lastDate}
                      </td>
                      <td>{count(s.count)}건</td>
                      <td>{count(s.documents)}개</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
          <div className="two-columns">
            <Panel title="정치자금 자료">
              <p>
                KA-money는 선관위 스캔 보고서를 언론사가 OCR로 정제한 2차 XLSX
                자료입니다. 글자·금액 오인식 가능성이 있습니다.
              </p>
              <External url="https://github.com/OhmyNews/KA-money">
                정제자료 저장소
              </External>
            </Panel>
            <Panel
              title="재산공개 자료"
              description={data.assetSource?.basis + " 기준"}
            >
              <External url={data.assetSource?.url}>
                {data.assetSource?.title}
              </External>
              <p className="caption">
                신고가액은 시세와 다를 수 있습니다. 지번·건물명·동호수는
                공개하지 않습니다.
              </p>
            </Panel>
          </div>
          <Section title="지도 경계와 라이선스">
            {data.geoSources.map((s, i) => (
              <Panel key={i}>
                <External url={s.url}>경계 데이터 원문 {i + 1}</External>
                <p className="caption">{s.attribution}</p>
              </Panel>
            ))}
          </Section>
        </>
      )}
      {tab === "methods" && (
        <>
          <div className="three-columns">
            <Panel title="재원·기간을 맞춥니다">
              <p>
                연간 합계·월평균·선택 기간 합계·단건 여부와 날짜를 함께
                표시합니다. 정치자금 보고분과 직책·반기를 구분합니다.
              </p>
            </Panel>
            <Panel title="중복·반환을 반영합니다">
              <p>
                다른 문서에 다시 실린 거래를 합계에서 제외합니다. 순지출은
                반환을 포함하고, 결제 빈도는 취소 짝을 제외한 양수 거래로
                셉니다. 문서 대상 기간 밖의 날짜로 표시된 행도 합계에서
                제외합니다.
              </p>
            </Panel>
            <Panel title="표시는 확인할 이유입니다">
              <p>
                규칙·관측값·근거 거래·자료 품질·정상적인 설명을 함께 봅니다.
                표시 건수로 사람의 점수나 위반 순위를 만들지 않습니다.
              </p>
            </Panel>
          </div>
          <Section
            title={"수집된 분석 규칙 " + data.rules.length + "개"}
            description="적용 시점과 기준을 확인해야 합니다. 자동 표시는 위반 확정이 아닙니다."
          >
            <SearchForm
              value={q}
              placeholder="규칙명 또는 내용 검색"
              onSearch={setQ}
            />
            <div className="rules-list">
              {data.rules
                .filter((r) => (r.name + r.purpose).includes(q))
                .map((r) => (
                  <details key={r.id}>
                    <summary>
                      <span>
                        {r.code} · {r.name}
                      </span>
                      <span className="tag">
                        {referenceNames[r.reference_type]}
                      </span>
                    </summary>
                    <p>{r.purpose}</p>
                    <KeyValues
                      rows={[
                        ["사용 항목", r.fields.join(" · ")],
                        ["계산 방법", r.method],
                        ["기준", r.thresholds],
                        ["자료가 없을 때", r.missing_data],
                      ]}
                    />
                    <h3>정상적인 설명일 수 있는 경우</h3>
                    <ul>
                      {r.normal_cases.map((v, i) => (
                        <li key={i}>{v}</li>
                      ))}
                    </ul>
                    <h3>추가 확인할 자료</h3>
                    <ul>
                      {r.verification.map((v, i) => (
                        <li key={i}>{v}</li>
                      ))}
                    </ul>
                  </details>
                ))}
            </div>
          </Section>
        </>
      )}
      {tab === "findings" && (
        <>
          <Notice>
            표시 {count(data.findingCount)}건은 자동 규칙의 결과입니다. 검토되지
            않은 기록을 위반이나 개인 평가로 해석하지 않습니다.
          </Notice>
          <div className="filters">
            <Select
              label="표시 재원"
              value={funding}
              options={Object.entries(meta.fundingTypes).map(([value, f]) => ({
                value,
                label: f.label,
              }))}
              onChange={(fundingType) => changeFilters({ fundingType })}
            />
            <SearchForm
              value={q}
              placeholder="규칙 코드 또는 내용 검색"
              onSearch={(value) => {
                setQ(value);
                changeFilters({ page: "" });
              }}
            />
          </div>
          {!findings.data ? (
            <ResourceState {...findings} />
          ) : findings.data.rows.length ? (
            findings.data.rows.map((f) => (
              <Panel
                key={f.id}
                title={
                  data.rules.find((r) => r.id === f.ruleId)?.name ||
                  "추가 확인 표시"
                }
                description="자동 표시 · 맥락 확인 필요"
              >
                <p>{f.explanation}</p>
                <KeyValues
                  rows={Object.entries(f.observed)
                    .filter(
                      ([k, v]) => observedLabels[k] && typeof v === "number",
                    )
                    .map(([k, v]) => [
                      observedLabels[k],
                      moneyKeys.has(k) ? won(v as number) : String(v),
                    ])}
                />
                <p className="caption">{f.reference.description}</p>
                <div className="evidence-links">
                  {f.evidenceIds.slice(0, 5).map((tid) => (
                    <Link
                      key={tid}
                      href={"/transactions/" + encodeURIComponent(tid)}
                    >
                      근거 거래 →
                    </Link>
                  ))}
                </div>
                <p className="caption">
                  {f.reviewHistory?.length
                    ? "검토 기록이 있습니다."
                    : "아직 사람이 검토한 기록이 없습니다."}
                </p>
              </Panel>
            ))
          ) : (
            <Empty>조건에 맞는 표시가 없습니다.</Empty>
          )}
          {findings.data && (
            <Pagination
              {...findings.data}
              onChange={(page) => changeFilters({ page })}
            />
          )}
        </>
      )}
      <SourceNote>
        빠진 값은 미기재·미수집으로 표시합니다. 원자료, 추정 분류, 계산 지표와
        검토 상태를 구분합니다.
      </SourceNote>
    </div>
  );
}
