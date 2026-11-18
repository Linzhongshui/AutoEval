/** Presentation only: preserve original values for sorting, scoring and evidence. */
export function formatScore(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "—";
}
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.round(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor(total % 86400 / 3600);
  const minutes = Math.floor(total % 3600 / 60);
  const rest = total % 60;
  return [days ? `${days}天` : "", hours || days ? `${hours}小时` : "", minutes || hours || days ? `${minutes}分` : "", `${rest}秒`].filter(Boolean).join(" ");
}
