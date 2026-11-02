import { useEffect, useState } from "react";
import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { query } from "./api";

export function navigate(href: string, replace = false) {
  if (replace) history.replaceState(null, "", href);
  else history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
export function useLocation() {
  const [location, setLocation] = useState(() => ({
    path: window.location.pathname,
    search: window.location.search,
  }));
  useEffect(() => {
    const update = () =>
      setLocation({
        path: window.location.pathname,
        search: window.location.search,
      });
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return { ...location, params: new URLSearchParams(location.search) };
}
export function href(
  path: string,
  values: Record<string, string | number | undefined | null> = {},
) {
  const suffix = query(values);
  return path + (suffix ? "?" + suffix : "");
}
export function changeFilters(
  values: Record<string, string | number | undefined | null>,
) {
  const next = new URLSearchParams(location.search);
  if (!("page" in values)) next.delete("page");
  Object.entries(values).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") next.delete(k);
    else next.set(k, String(v));
  });
  navigate(location.pathname + (next.size ? "?" + next.toString() : ""));
}
export function Link({
  href: to = "/",
  onClick,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const click = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.altKey ||
      event.shiftKey ||
      props.target ||
      !to.startsWith("/")
    )
      return;
    const changedPage = to.split("?")[0] !== location.pathname;
    event.preventDefault();
    navigate(to);
    if (changedPage) window.scrollTo({ top: 0 });
  };
  return <a {...props} href={to} onClick={click} />;
}
