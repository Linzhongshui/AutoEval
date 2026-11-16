import type { Config, Param, Target } from "./types";

export const RUN_MODES = ["GPQA", "MMMU-Pro", "AutomationBench"] as const;

export const DATASET_TYPES = [
  { label: "科学问答", items: ["GPQA", "GPQA_Diamond"] },
  { label: "多模态", items: ["MMMU-Pro"] },
  { label: "Agent 工作流", items: ["DeepSWE", "AutomationBench"] },
];

export const eligibleConfig = (row: Config) =>
  Object.keys(row.items).length === 1 && row.items.GPQA?.scope === "Lite" && row.profile_bindings?.GPQA;

export const eligibleTarget = (row: Target) =>
  row.remote_model === "deepseek-flash" && row.base_url.replace(/\/$/, "") === "https://api.deepseek.com";

export const runLink = (id: string) => `#run/${id}`;

export const withSelected = <T extends { id: string }>(rows: T[], selected: T | null) =>
  selected && !rows.some((row) => row.id === selected.id) ? [selected, ...rows] : rows;

export const baseParams = (i = 0): Param => ({
  output: 2048,
  concurrency: 60 - i * 20,
  temperature: 0.6,
  top_p: 0.95,
  scope: "全量",
});

export const isTerminal = (state: string) => ["completed", "failed", "cancelled"].includes(state);

export const resourceLabel = (kind?: string) =>
  kind === "aisbench_monitor" ? "远程 AISBench" : kind === "customer_ssh" ? "客户 SSH 服务器" : "本机 Docker";

export const formatTime = (value?: string) =>
  value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "暂无记录";

export const datasetProgress = (summary?: Record<string, unknown> | null) => {
  const progress = summary?.progress;
  if (!progress || typeof progress !== "object") return "未采集样本进度";
  const p = progress as Record<string, unknown>;
  return typeof p.finish_count === "number" && typeof p.total_count === "number"
    ? `已完成 ${p.finish_count}/${p.total_count}${p.stale ? "（已过期）" : ""}`
    : "执行状态已采集，等待样本计数";
};
