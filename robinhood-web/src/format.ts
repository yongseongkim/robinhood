const number = new Intl.NumberFormat("ko-KR");
export const count = (value?: number | null) =>
  value === undefined || value === null
    ? "—"
    : number.format(Math.round(value));
export const won = (value?: number | null) =>
  value === undefined || value === null
    ? "미수집"
    : number.format(Math.round(value)) + "원";
export function shortWon(value?: number | null) {
  if (value === undefined || value === null) return "미수집";
  const abs = Math.abs(value),
    sign = value < 0 ? "−" : "";
  if (abs >= 1e12)
    return sign + (abs / 1e12).toFixed(1).replace(/\.0$/, "") + "조";
  if (abs >= 1e8)
    return sign + (abs / 1e8).toFixed(2).replace(/\.00$/, "") + "억";
  if (abs >= 1e4) return sign + number.format(Math.round(abs / 1e4)) + "만";
  return sign + number.format(abs) + "원";
}
export const percent = (value?: number | null) =>
  value === undefined || value === null ? "—" : (value * 100).toFixed(1) + "%";
export const confidence = (value?: string) =>
  ({ HIGH: "높음", MEDIUM: "보통", LOW: "낮음" })[value || ""] || "미확인";
export function externalUrl(url?: string) {
  return url && /^https?:\/\//i.test(url) ? url : undefined;
}
