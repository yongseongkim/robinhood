import { MapPin } from "lucide-react";
import { query, useGeo, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, shortWon } from "../format";
import { RegionMap } from "../components/maps";
import {
  ButtonLink,
  Empty,
  External,
  PageHeader,
  Panel,
  ResourceState,
  Section,
  Select,
  SourceNote,
} from "../components/ui";
import type { Overview } from "../types";

export function Home() {
  const { params } = useLocation();
  const geo = useGeo();
  const region = params.get("region") || "";
  const province = region.split(" ")[0];
  const cities = (geo?.sigungu || []).filter((f) => f.sido_short === province);
  const city = cities.find((f) => f.name === region);
  const neighborhoods = (geo?.neighborhoods || []).filter(
    (f) => f.municipality === city?.code,
  );
  const dong = neighborhoods.find((f) => f.code === params.get("dong"));
  const district = params.get("district") || "";
  const resource = useResource<Overview>("overview?" + query({ region }));
  const data = resource.data;
  if (!data) return <ResourceState {...resource} />;
  const candidates = data.roster.rows.filter(
    (m) => !dong || dong.districtCodes.includes(m.districtCode || ""),
  );
  const members = candidates.filter(
    (m) => !district || m.districtCode === district || m.district === district,
  );
  const local = data.council;
  const councilYear = local?.scope.start.slice(0, 4);
  const selectRegion = (region: string) =>
    changeFilters({ region, dong: "", district: "" });
  return (
    <div className="page stack">
      <PageHeader
        title="우리 지역 국회의원"
        context="홈 · 내 지역"
        description="시·도와 시·군·구를 선택해 현재 지역구 의원의 지출, 신고재산과 의정활동을 확인하세요."
      />
      <div className="filters">
        <MapPin size={16} />
        <Select
          label="시·도"
          value={province}
          options={[
            { value: "", label: "시·도 선택" },
            ...(geo?.sido || []).map((f) => ({
              value: f.short || f.name,
              label: f.name,
            })),
          ]}
          onChange={selectRegion}
        />
        {province && (
          <Select
            label="시·군·구"
            value={city?.name || ""}
            options={[
              { value: "", label: "시·군·구 전체" },
              ...cities.map((f) => ({ value: f.name, label: f.sgg || f.name })),
            ]}
            onChange={(v) => selectRegion(v || province)}
          />
        )}
        {city && (
          <Select
            label="읍·면·동"
            value={dong?.code || ""}
            options={[
              { value: "", label: "읍·면·동 전체" },
              ...neighborhoods.map((f) => ({ value: f.code, label: f.name })),
            ]}
            onChange={(dong) => changeFilters({ dong, district: "" })}
          />
        )}
        {province && (
          <Select
            label="국회 선거구"
            value={district}
            options={[
              { value: "", label: "선거구 전체" },
              ...candidates.map((m) => ({
                value: m.districtCode || m.district,
                label: m.district,
              })),
            ]}
            onChange={(district) => changeFilters({ district })}
          />
        )}
      </div>
      {dong && (
        <SourceNote>
          {dong.method === "statute"
            ? "공직선거법 별표 1의 읍·면·동 구역과 대조한 결과입니다."
            : "행정동 경계와 선거구 경계를 겹쳐 추정한 결과입니다."}{" "}
          {dong.districtCodes.length !== 1 &&
            "주소에 따라 선거구가 달라질 수 있습니다. "}
          <External url="https://law.go.kr/LSW/flDownload.do?flSeq=163897897">
            법정 선거구 구역표 확인
          </External>
        </SourceNote>
      )}
      <div className="two-columns">
        <Panel title="지역 선택">
          <RegionMap
            dark
            features={geo?.sido || []}
            viewBox={geo?.projection.national.viewBox}
            selected={province}
            onSelect={(f) => selectRegion(f.short || f.name)}
          />
        </Panel>
        <Panel
          title={region || "전국 현직 의원"}
          description={
            "열린국회정보 명부 확인 " +
            (data.roster.asOf?.slice(0, 10) || "날짜 미확인")
          }
        >
          {province && (
            <RegionMap
              dark
              autoFit
              features={
                city
                  ? (geo?.districts || []).filter((f) =>
                      candidates.some((m) => m.districtCode === f.code),
                    )
                  : cities
              }
              selected={
                city
                  ? candidates.find((m) => m.districtCode === district)
                      ?.district
                  : region
              }
              onSelect={(f) =>
                city
                  ? changeFilters({ district: f.code })
                  : selectRegion(f.name)
              }
            />
          )}
          <div className="person-amount">{count(members.length)}명</div>
          {data.roster.check?.state === "partial" && (
            <p>최근 명부 확인에 실패해 직전 수집본을 표시합니다.</p>
          )}
          <ButtonLink to={href("/members", { region })}>
            현직 의원 전체 보기
          </ButtonLink>
        </Panel>
      </div>
      {province && (
        <Section
          title="이 지역 국회의원"
          description="현재 명부 기준 · 정치자금은 프로필에서 보고 연도를 선택할 수 있습니다."
        >
          {members.length ? (
            <div className="person-grid">
              {members.map((m) => (
                <Panel
                  key={m.id}
                  title={m.name}
                  description={[m.district, m.party]
                    .filter(Boolean)
                    .join(" · ")}
                >
                  <ButtonLink to={"/members/" + m.id}>프로필 보기</ButtonLink>
                </Panel>
              ))}
            </div>
          ) : (
            <Empty>
              선택한 범위와 연결된 현직 의원이 없습니다. 선거구 구역표를 확인해
              주세요.
            </Empty>
          )}
        </Section>
      )}
      {local && (
        <Panel
          title={local.council.name + " 경비"}
          description={local.scope.label}
        >
          <div className="person-amount">{shortWon(local.summary.amount)}</div>
        </Panel>
      )}
      <div className="two-columns">
        <Panel
          title="직책·반기별 지출 합계 Top 3"
          description={
            councilYear ? councilYear + "년 · 직책과 재임 기간 기준" : undefined
          }
        >
          {local?.roles.slice(0, 3).map((r, i) => (
            <div className="compact-rank" key={r.id}>
              <span>
                {i + 1}. {r.subject.role}
                <small>
                  {r.subject.term} ·{" "}
                  {r.subject.holders.map((h) => h.name).join(" · ") ||
                    "보유자 미확인"}
                </small>
              </span>
              <Link
                className="numeric"
                href={href("/members/" + r.id, {
                  fundingType: "COUNCIL_OPERATION",
                  year: councilYear,
                })}
              >
                {shortWon(r.amount)}
              </Link>
            </div>
          ))}
          {!local && (
            <Empty>이 지역 지방의회 자료는 아직 연결되지 않았습니다.</Empty>
          )}
          <ButtonLink
            to={href("/councils", {
              council: local?.council.source_id,
            })}
          >
            지방의회 전체 보기
          </ButtonLink>
        </Panel>
        <Panel title="이 지역에서 더 보기">
          <div className="action-list">
            <ButtonLink to={href("/members", { region })}>
              지역 의원 목록
            </ButtonLink>
            <ButtonLink to={href("/places", { region })}>
              자주 결제한 장소
            </ButtonLink>
            <ButtonLink to="/rankings">정당·항목별 비교</ButtonLink>
          </div>
        </Panel>
      </div>
      <SourceNote>
        정치자금: KA-money OCR 정제본 · 의회 경비: 각 의회 공개자료. 지도: SGIS
        / admdongkor, 오마이뉴스 선거구 경계. 집계 기간과 재원은 각각
        구분합니다.
      </SourceNote>
    </div>
  );
}
