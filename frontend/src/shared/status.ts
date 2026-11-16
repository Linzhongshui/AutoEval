/** Central status vocabulary: unknown values keep their raw text and a neutral tone. */

export type Tone = "neutral" | "info" | "success" | "error" | "warning";

export type StatusView = { label: string; tone: Tone };

const TONES: Record<string, Tone> = {
  passed: "success",
  running: "info",
  error: "error",
  warning: "warning",
  neutral: "neutral",
};

export function toneClass(tone: Tone | undefined): string {
  return TONES[tone || "neutral"] || "neutral";
}

function view(map: Record<string, string>, tone: Tone, value: string): StatusView {
  const label = map[value];
  return label ? { label, tone } : { label: value, tone: "neutral" };
}

/** Evaluation task lifecycle (执行状态). */
const TASK_STATES: Record<string, string> = {
  accepted: "已接收",
  queued: "排队中",
  preparing: "准备执行环境",
  running: "执行中",
  aggregating: "汇总结果",
  cancelling: "取消确认中",
  cancelled: "已取消",
  completed: "已完成",
  failed: "执行失败",
  execution_unresolved: "状态待查证",
};
export const taskStatus = (value: string): StatusView => {
  const state = view(TASK_STATES, "info", value);
  if (value === "completed") return { ...state, tone: "success" };
  if (value === "failed") return { ...state, tone: "error" };
  if (value === "cancelled" || value === "cancelling") return { ...state, tone: "warning" };
  return state;
};

/** Per-dataset execution state (数据集执行状态). */
const DATASET_STATES: Record<string, string> = {
  pending: "待执行",
  submitting: "准备执行",
  running: "执行中",
  succeeded: "执行完成",
  completed: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
  unresolved: "状态待查证",
};
export const datasetStatus = (value: string): StatusView => {
  const state = view(DATASET_STATES, "info", value);
  if (value === "succeeded" || value === "completed") return { ...state, tone: "success" };
  if (value === "failed") return { ...state, tone: "error" };
  if (value === "cancelled" || value === "unresolved") return { ...state, tone: "warning" };
  return state;
};

/** Scoring and evidence state are separate from execution state. */
const EVIDENCE_STATES: Record<string, string> = {
  verified: "证据已核验",
  not_checked: "未核验",
  missing: "证据缺失",
  unavailable: "证据不可用",
  invalid: "证据异常",
};
export const evidenceStatus = (value: string): StatusView => {
  if (value === "verified") return { label: EVIDENCE_STATES[value], tone: "success" };
  if (value === "not_checked") return { label: EVIDENCE_STATES[value], tone: "neutral" };
  if (value === "missing") return { label: EVIDENCE_STATES[value], tone: "error" };
  if (value === "invalid") return { label: EVIDENCE_STATES[value], tone: "error" };
  if (value === "unavailable") return { label: EVIDENCE_STATES[value], tone: "warning" };
  return { label: value, tone: "neutral" };
};

const REPORT_VALIDITY: Record<string, string> = {
  complete: "完整",
  partial: "部分完成",
  failed: "执行失败",
};
export const reportValidity = (value: string): StatusView => {
  if (value === "complete") return { label: REPORT_VALIDITY[value], tone: "success" };
  if (value === "partial") return { label: REPORT_VALIDITY[value], tone: "warning" };
  if (value === "failed") return { label: REPORT_VALIDITY[value], tone: "error" };
  return { label: value, tone: "neutral" };
};

const CLEANUP_STATES: Record<string, string> = {
  not_required: "无需清理",
  not_scheduled: "尚未安排",
  pending: "待清理",
  running: "清理中",
  failed: "待恢复，保留占用",
  cleaned: "已确认",
};
export const cleanupStatus = (value: string): StatusView => {
  const state = view(CLEANUP_STATES, "info", value);
  if (value === "cleaned" || value === "not_required") return { ...state, tone: "success" };
  if (value === "failed") return { ...state, tone: "error" };
  if (value === "pending" || value === "not_scheduled") return { ...state, tone: "warning" };
  return state;
};
