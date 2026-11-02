import { createContext, useContext, useEffect, useState } from "react";
import type { Geo, Meta } from "./types";

export const MetaContext = createContext<Meta | null>(null);
export const GeoContext = createContext<Geo | undefined>(undefined);
export const useGeo = () => useContext(GeoContext);
export function useMeta() {
  const value = useContext(MetaContext);
  if (!value) throw new Error("서비스 정보를 불러오지 못했습니다.");
  return value;
}
export function query(
  values: Record<string, string | number | undefined | null>,
) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return params.toString();
}
export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setData(undefined);
    fetch("/api/v1/" + path, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok)
          throw new Error(
            typeof body.detail === "string"
              ? body.detail
              : "입력한 조건을 확인해 주세요.",
          );
        return body as T;
      })
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted)
          setError(
            e.message === "Failed to fetch"
              ? "데이터를 읽지 못했습니다. 연결 상태를 확인해 주세요."
              : e.message,
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, error, loading, retry: () => setRevision((v) => v + 1) };
}
