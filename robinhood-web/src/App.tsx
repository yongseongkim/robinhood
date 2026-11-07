import { useEffect, useState } from "react";
import { FileText, Landmark, Map, MapPin, Menu, Users, X } from "lucide-react";
import { GeoContext, MetaContext, useResource } from "./api";
import { Link, useLocation } from "./router";
import { Notice, ResourceState } from "./components/ui";
import { Home } from "./pages/Home";
import { Members } from "./pages/Members";
import { Profile } from "./pages/Profile";
import { Councils } from "./pages/Councils";
import { Rankings } from "./pages/Rankings";
import { Places, PlaceDetail } from "./pages/Places";
import { Fiscal } from "./pages/Fiscal";
import { Sources } from "./pages/Sources";
import { Transaction } from "./pages/Transaction";
import type { Geo, Meta } from "./types";

const navigation = [
  { href: "/", label: "내 지역", icon: MapPin },
  { href: "/members", label: "의원·정당", icon: Users },
  { href: "/rankings", label: "비교·장소", icon: Map },
  { href: "/fiscal", label: "나라 살림", icon: Landmark },
  { href: "/sources", label: "출처·방법", icon: FileText },
];
function PageRouter({ path }: { path: string }) {
  const parts = path.split("/").filter(Boolean);
  if (!parts.length) return <Home />;
  let id = "";
  try {
    id = decodeURIComponent(parts[1] || "");
  } catch {
    return <NotFound />;
  }
  if (parts[0] === "members")
    return id ? <Profile key={id} id={id} /> : <Members />;
  if (parts[0] === "councils") return <Councils />;
  if (parts[0] === "rankings") return <Rankings />;
  if (parts[0] === "places")
    return id ? <PlaceDetail key={id} id={id} /> : <Places />;
  if (parts[0] === "fiscal") return <Fiscal />;
  if (parts[0] === "sources") return <Sources />;
  if (parts[0] === "transactions" && id)
    return <Transaction key={id} id={id} />;
  return <NotFound />;
}
function NotFound() {
  return (
    <div className="page empty">
      <h1>페이지를 찾지 못했습니다</h1>
      <p>주소를 확인하거나 내 지역에서 다시 시작해 주세요.</p>
      <Link className="button-link" href="/">
        내 지역으로
      </Link>
    </div>
  );
}

export default function App() {
  const { path, search } = useLocation();
  const meta = useResource<Meta>("meta");
  const geo = useResource<Geo>("geo");
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    setMenu(false);
  }, [path, search]);
  useEffect(() => {
    document.title = "나랏일보고서";
  }, [path]);
  const active = (to: string) =>
    to === "/"
      ? path === "/" || path.startsWith("/councils")
      : path.startsWith(to) ||
        (to === "/rankings" && path.startsWith("/places"));
  return (
    <>
      <a className="skip-link" href="#content">
        본문으로 이동
      </a>
      <header className="app-header">
        <div className="header-inner">
          <Link className="brand" href="/" aria-label="나랏일보고서 홈">
            <span>나랏일보고서</span>
            <small>공개 기록</small>
          </Link>
          <nav className="desktop-nav" aria-label="주 메뉴">
            {navigation.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active(n.href) ? "page" : undefined}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="data-mode">공개 수집 자료</span>
          <button
            className="menu-button"
            aria-label={menu ? "메뉴 닫기" : "메뉴 열기"}
            aria-expanded={menu}
            aria-controls="mobile-menu"
            onClick={() => setMenu((v) => !v)}
          >
            {menu ? <X size={19} /> : <Menu size={19} />}
            <span>메뉴</span>
          </button>
        </div>
        {menu && (
          <nav
            className="mobile-menu"
            id="mobile-menu"
            aria-label="모바일 주 메뉴"
          >
            {navigation.map((n) => (
              <Link key={n.href} href={n.href}>
                {n.label}
              </Link>
            ))}
            <Link href="/places">자주 결제한 장소</Link>
            <Link href="/councils">지방의회 경비</Link>
          </nav>
        )}
      </header>
      <main id="content" className="app-main">
        {meta.data ? (
          <MetaContext value={meta.data}>
            <GeoContext value={geo.data}>
              {geo.error && (
                <div className="page">
                  <Notice>
                    지도를 읽지 못했습니다. 다른 기록은 확인할 수 있습니다.{" "}
                    <button onClick={geo.retry}>지도 다시 읽기</button>
                  </Notice>
                </div>
              )}
              <PageRouter path={path} />
            </GeoContext>
          </MetaContext>
        ) : (
          <div className="page">
            <ResourceState {...meta} />
          </div>
        )}
      </main>
      <footer className="app-footer">
        <span>나랏일보고서</span>
        <span>기간·재원·출처를 함께 확인하세요.</span>
        <Link href="/sources">데이터와 확인 방법 →</Link>
      </footer>
      <nav className="bottom-nav" aria-label="빠른 이동">
        {[
          { href: "/", label: "내 지역", icon: MapPin },
          { href: "/members", label: "의원", icon: Users },
          { href: "/places", label: "장소", icon: Map },
          { href: "/fiscal", label: "나라 살림", icon: Landmark },
          { href: "/sources", label: "출처", icon: FileText },
        ].map((n) => (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active(n.href) ? "page" : undefined}
          >
            <n.icon size={19} />
            <span>{n.label}</span>
          </Link>
        ))}
      </nav>
    </>
  );
}
