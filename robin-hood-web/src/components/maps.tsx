import { useEffect, useRef, useState } from "react";
import { Layers, Minus, Plus, RotateCw } from "lucide-react";
import { useGeo, useMeta } from "../api";
import { Link } from "../router";
import { count } from "../format";
import type { Cluster, MapFeature } from "../types";

type LatLng = { lat(): number; lng(): number };
type MapHandle = {
  setCenter(position: LatLng): void;
  getCenter(): LatLng;
  destroy(): void;
};
type MarkerHandle = { setMap(map: MapHandle | null): void };
type MapSDK = {
  Map: new (
    element: HTMLElement,
    options: Record<string, unknown>,
  ) => MapHandle;
  LatLng: new (lat: number, lng: number) => LatLng;
  Marker: new (options: Record<string, unknown>) => MarkerHandle;
  Point: new (x: number, y: number) => unknown;
  Position: Record<string, unknown>;
};
declare global {
  interface Window {
    naver?: { maps: MapSDK };
    navermap_authFailure?: () => void;
  }
}
let sdkPromise: Promise<MapSDK> | null = null;
function loadSDK(clientId: string) {
  if (window.naver?.maps) return Promise.resolve(window.naver.maps);
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise<MapSDK>((resolve, reject) => {
    const script = document.createElement("script");
    const timeout = window.setTimeout(
      () => reject(new Error("네이버 지도 응답 지연")),
      12000,
    );
    window.navermap_authFailure = () =>
      window.dispatchEvent(new Event("naver-map-failed"));
    script.src =
      "https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=" +
      encodeURIComponent(clientId);
    script.async = true;
    script.onload = () => {
      clearTimeout(timeout);
      if (window.naver?.maps) resolve(window.naver.maps);
      else reject(new Error("지도 SDK를 읽지 못했습니다."));
    };
    script.onerror = () => {
      clearTimeout(timeout);
      reject(new Error("지도 연결 실패"));
    };
    document.head.appendChild(script);
  });
  return sdkPromise;
}

export function RegionMap({
  features,
  selected,
  onSelect,
  viewBox = "0 0 1000 820.9",
  dark = false,
  autoFit = false,
}: {
  features: MapFeature[];
  selected?: string;
  onSelect?: (feature: MapFeature) => void;
  viewBox?: string;
  dark?: boolean;
  autoFit?: boolean;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [fit, setFit] = useState("");
  useEffect(() => {
    if (!autoFit || !svg.current || !features.length) return;
    const boxes = Array.from(svg.current.querySelectorAll("path")).map((p) =>
      p.getBBox(),
    );
    const x = Math.min(...boxes.map((b) => b.x)),
      y = Math.min(...boxes.map((b) => b.y));
    const right = Math.max(...boxes.map((b) => b.x + b.width)),
      bottom = Math.max(...boxes.map((b) => b.y + b.height));
    setFit(`${x - 15} ${y - 15} ${right - x + 30} ${bottom - y + 30}`);
  }, [autoFit, features]);
  return (
    <svg
      ref={svg}
      className={
        "region-map" + (dark ? " dark-map" : "") + (autoFit ? " fit-map" : "")
      }
      viewBox={autoFit && fit ? fit : viewBox}
      role={onSelect ? "group" : "img"}
      aria-label="행정구역 지도"
    >
      {features.map((f) => (
        <g
          key={f.code}
          role={onSelect ? "button" : undefined}
          tabIndex={onSelect ? 0 : undefined}
          aria-label={f.name}
          onClick={() => onSelect?.(f)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect?.(f);
            }
          }}
          className={
            selected === f.name || selected === f.short
              ? "map-region selected-region"
              : "map-region"
          }
        >
          <title>{f.name}</title>
          <path d={f.d} />
          <text x={f.cx} y={f.cy} textAnchor="middle">
            {f.sgg?.replace(/구$/, "") ||
              f.short ||
              f.name.replace(/서울\s*/, "")}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function PlaceMap({
  clusters = [],
  region,
  onRegion,
  onRefresh,
  compact = false,
}: {
  clusters?: Cluster[];
  region: string;
  onRegion?: (region: string) => void;
  onRefresh?: () => void;
  compact?: boolean;
}) {
  const geo = useGeo();
  const meta = useMeta();
  const surface = useRef<HTMLDivElement>(null);
  const map = useRef<MapHandle | null>(null);
  const [sdk, setSDK] = useState<MapSDK>();
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(1);
  const features = geo?.seoul || [];
  const canUseSDK = features.some(
    (f) => f.lat !== undefined && f.lng !== undefined,
  );
  const live = Boolean(sdk && !failed && canUseSDK);
  useEffect(() => {
    if (!meta.naverMapsClientId) return;
    let active = true;
    loadSDK(meta.naverMapsClientId)
      .then((s) => {
        if (active) setSDK(s);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    const error = () => setFailed(true);
    window.addEventListener("naver-map-failed", error);
    return () => {
      active = false;
      window.removeEventListener("naver-map-failed", error);
    };
  }, [meta.naverMapsClientId]);
  useEffect(() => {
    if (!sdk || !surface.current || !canUseSDK || failed) return;
    const f =
      features.find((f) => f.name === region) ||
      features.find((f) => f.name === "서울 영등포구") ||
      features[0];
    map.current = new sdk.Map(surface.current, {
      center: new sdk.LatLng(f.lat!, f.lng!),
      zoom: compact ? 11 : 10,
      zoomControl: true,
      mapTypeControl: !compact,
      scaleControl: true,
      mapDataControl: true,
      zoomControlOptions: { position: sdk.Position.TOP_RIGHT },
    });
    return () => {
      map.current?.destroy();
      map.current = null;
    };
  }, [sdk, canUseSDK, failed]);
  useEffect(() => {
    if (!sdk || !map.current || !live) return;
    const markers: MarkerHandle[] = [];
    const list = clusters.length
      ? clusters.filter((c) => c.region.startsWith("서울 "))
      : [{ region, venues: 0 }];
    for (const c of list) {
      const f = features.find((f) => f.name === c.region);
      if (!f || f.lat === undefined || f.lng === undefined) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "map-cluster" + (c.region === region ? " active" : "");
      button.textContent =
        c.region.replace("서울 ", "") +
        (clusters.length ? " " + count(c.venues) : "");
      button.setAttribute(
        "aria-label",
        c.region + (clusters.length ? " " + c.venues + "곳" : " 지역 위치"),
      );
      button.onclick = () => onRegion?.(c.region);
      markers.push(
        new sdk.Marker({
          map: map.current,
          position: new sdk.LatLng(f.lat, f.lng),
          icon: { content: button, anchor: new sdk.Point(30, 12) },
        }),
      );
    }
    const f = features.find((f) => f.name === region);
    if (f?.lat !== undefined && f?.lng !== undefined)
      map.current.setCenter(new sdk.LatLng(f.lat, f.lng));
    return () => markers.forEach((marker) => marker.setMap(null));
  }, [sdk, live, clusters, region, features, onRegion]);
  const search = () => {
    if (live && map.current) {
      const center = map.current.getCenter();
      const nearest = features
        .filter((f) => f.lat !== undefined && f.lng !== undefined)
        .sort(
          (a, b) =>
            (a.lat! - center.lat()) ** 2 +
            (a.lng! - center.lng()) ** 2 -
            ((b.lat! - center.lat()) ** 2 + (b.lng! - center.lng()) ** 2),
        )[0];
      if (nearest) onRegion?.(nearest.name);
    }
    onRefresh?.();
  };
  const shown = [...clusters]
    .filter((c) => c.region.startsWith("서울 "))
    .sort((a, b) => b.payments - a.payments)
    .slice(0, compact ? 0 : 6);
  const selected = clusters.find((c) => c.region === region);
  if (selected && !shown.some((c) => c.region === region)) shown.push(selected);
  return (
    <div className={"place-map-wrap" + (compact ? " compact-map" : "")}>
      <div className="map-canvas" ref={surface} hidden={!live} />
      {!live && (
        <div className="fallback-map">
          <div
            className="fallback-map-layer"
            style={{ transform: `scale(${zoom})` }}
          >
            <RegionMap
              features={features}
              selected={region}
              onSelect={onRegion ? (f) => onRegion(f.name) : undefined}
              viewBox={geo?.projection.seoul.viewBox}
            />
            {shown.map((c) => {
              const f = features.find((f) => f.name === c.region);
              return f ? (
                <button
                  className={
                    "map-cluster positioned" +
                    (c.region === region ? " active" : "")
                  }
                  key={c.region}
                  style={{
                    left: f.cx / 10 + "%",
                    top: (f.cy / 820.9) * 100 + "%",
                  }}
                  onClick={() => onRegion?.(c.region)}
                >
                  {c.region.replace("서울 ", "")} {count(c.venues)}
                </button>
              ) : null;
            })}
          </div>
        </div>
      )}
      <div className="map-current-region">
        {region || "서울 전체"}
        {onRegion && <span> ▾</span>}
      </div>
      {!compact && (
        <button
          type="button"
          className="map-search"
          onClick={search}
          title="지도 중심에서 가까운 구의 기록을 확인합니다"
        >
          <RotateCw size={14} />이 지역 다시 검색
        </button>
      )}
      {!live && !compact && (
        <div className="map-zoom">
          <button
            aria-label="지도 확대"
            onClick={() => setZoom((v) => Math.min(2.2, v + 0.3))}
          >
            <Plus size={18} />
          </button>
          <button
            aria-label="지도 축소"
            onClick={() => setZoom((v) => Math.max(1, v - 0.3))}
          >
            <Minus size={18} />
          </button>
        </div>
      )}
      {!live && (
        <Link className="fallback-attribution" href="/sources?tab=sources">
          행정경계 지도 · SGIS / admdongkor
        </Link>
      )}
      {!live && !compact && (
        <span className="map-provider-state">
          <Layers size={12} />
          {failed
            ? "지도 연결 지연 · 지역 경계 표시"
            : "지역 경계 · 가게 좌표 미확인"}
        </span>
      )}
    </div>
  );
}
