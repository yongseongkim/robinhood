import { ArrowRight, MapPin } from "lucide-react";
import { query, useGeo, useResource } from "../api";
import { changeFilters, href, Link, useLocation } from "../router";
import { count, shortWon, won } from "../format";
import { RegionMap } from "../components/maps";
import {
  ButtonLink,
  Empty,
  PageHeader,
  Panel,
  ResourceState,
  Section,
  Select,
  SourceNote,
  Stat,
} from "../components/ui";
import type { Overview } from "../types";

export function Home() {
  const { params } = useLocation();
  const geo = useGeo();
  const region = params.get("region") || "서울 마포구";
  const province = region.split(" ")[0];
  const district = params.get("district") || "";
  const resource = useResource<Overview>("overview?" + query({ region }));
  const data = resource.data;
  if (!data) return <ResourceState {...resource} />;
  const members = district
    ? data.members.rows.filter((m) => m.district === district)
    : data.members.rows;
  const local = data.council;
  const city = data.cityCouncil;
  const boundaries =
    province === "서울"
      ? geo?.seoulDistricts.filter((d) =>
          d.name.includes(region.replace(/\s/g, "").replace("서울", "")),
        ) || []
      : [];
  return (
    <div className="page stack">
      <PageHeader
        title="우리 지역의 기록을 한눈에"
        context="홈 · 내 지역"
        description="지역을 고르고 의원·의회 경비·장소 기록으로 이어집니다."
      />
      <div className="filters">
        <MapPin size={16} />
        <Select
          label="시·도"
          value={province}
          options={(geo?.sido || []).map((f) => ({
            value: f.short || f.name,
            label: f.name,
          }))}
          onChange={(region) => changeFilters({ region, district: "" })}
        />
        {province === "서울" && (
          <Select
            label="시·군·구"
            value={region}
            options={[
              { value: "서울", label: "서울 전체" },
              ...(geo?.seoul || []).map((f) => ({
                value: f.name,
                label: f.sgg || f.name,
              })),
            ]}
            onChange={(region) => changeFilters({ region, district: "" })}
          />
        )}
        <Select
          label="국회 선거구"
          value={district}
          options={[
            { value: "", label: "선거구 · 전체" },
            ...data.members.rows.map((m) => ({
              value: m.district || "",
              label: m.district || "",
            })),
          ]}
          onChange={(district) => changeFilters({ district })}
        />
      </div>
      <div className="scope-bar">
        <span>집계 기준</span>
        <span>
          국회의원: 2024년 제22대 보고분 합계 · 의회 경비: 2024.01–12 연간 합계
        </span>
      </div>
      <div className="map-steps">
        <Panel
          title="01  시·도 선택"
          description="전국에서 내 지역을 찾습니다."
        >
          <RegionMap
            dark
            features={geo?.sido || []}
            viewBox={geo?.projection.national.viewBox}
            selected={province}
            onSelect={(f) =>
              changeFilters({ region: f.short || f.name, district: "" })
            }
          />
          <span className="map-step-label">
            {province} <ArrowRight size={13} />
          </span>
        </Panel>
        <Panel
          title="02  시·군·구 선택"
          description={
            province === "서울"
              ? "서울 · 25개 자치구"
              : "서울 지방의회부터 공개 자료를 연결합니다."
          }
        >
          {province === "서울" ? (
            <RegionMap
              dark
              features={geo?.seoul || []}
              selected={region}
              onSelect={(f) => changeFilters({ region: f.name, district: "" })}
            />
          ) : (
            <div className="map-scope-note">
              <MapPin size={28} />
              <p>
                {province} 국회의원 보고자료 {count(data.members.total)}명
              </p>
              <ButtonLink to={href("/members", { region })}>
                의원 목록 보기
              </ButtonLink>
            </div>
          )}
          <span className="map-step-label">{region}</span>
        </Panel>
        <Panel
          title="03  국회 선거구"
          description={region + " · 제22대 지역구"}
        >
          {boundaries.length ? (
            <RegionMap
              dark
              autoFit
              features={boundaries}
              selected={district || members[0]?.district}
              onSelect={(f) => changeFilters({ district: f.name })}
            />
          ) : (
            <div className="map-scope-note">
              <p>지역구를 선택해 보고자료를 확인합니다.</p>
              <span>{count(data.members.total)}명 연결</span>
            </div>
          )}
          <span className="map-step-label">{district || "선거구 전체"}</span>
        </Panel>
      </div>
      <div className="metrics">
        <Stat
          accent
          label="지역구 보고자"
          value={count(members.length) + "명"}
          detail="2024년 제22대 정치자금 보고분"
        />
        <Stat
          label={local ? local.council.name + " 경비" : "지역 의회 경비"}
          value={shortWon(local?.summary.amount)}
          exact={local?.summary.amount}
          detail="2024.01–12 · 의회운영업무추진비"
        />
        <Stat
          label="서울시의회 경비"
          value={shortWon(city?.summary.amount)}
          exact={city?.summary.amount}
          detail="2024.01–12 · 연간 합계"
        />
        <Stat
          label="지자체 재정수지"
          value="자료 미수집"
          detail="의회 경비와 지자체 전체 재정은 별도"
        />
      </div>
      <Section
        title="이 지역 국회의원"
        description="2024년 제22대 보고분 합계 · 현재 소속과 다를 수 있습니다."
      >
        {members.length ? (
          <div className="person-grid">
            {members.slice(0, 6).map((m) => (
              <Panel
                key={m.id}
                title={m.name}
                description={m.district + " · " + (m.party || "정당 미기재")}
              >
                <div className="person-amount" title={won(m.amount)}>
                  {shortWon(m.amount)}
                </div>
                <p className="caption">
                  2024년 보고분 합계 · {count(m.count)}건
                </p>
                <ButtonLink
                  to={href("/members/" + m.id, { report: "ka:2024-22" })}
                >
                  프로필 보기
                </ButtonLink>
              </Panel>
            ))}
          </div>
        ) : (
          <Empty>
            선택 지역에 연결된 보고자료가 없습니다. 다른 선거구나 의원 목록에서
            확인해 주세요.
          </Empty>
        )}
      </Section>
      <div className="two-columns">
        <Panel
          title="직책·반기별 지출 합계 Top 3"
          description="2024년 · 역할과 재임 기간을 함께 확인합니다."
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
                  year: 2024,
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
              council: local?.council.source_id || "mapo",
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
