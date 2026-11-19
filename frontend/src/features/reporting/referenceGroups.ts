import { datasetIdentity } from "../catalog/datasetIdentities";
import type { CuratedRecord } from "./DataWorkbench";

export type ComparisonGroup = {
  id: string;
  comparison: Record<string, unknown>;
  entries: CuratedRecord[];
};

export const datasetPriority = (name: string) => {
 const value = name.toLowerCase().replace(/[^a-z0-9]/g, "");
 return value.includes("gpqadiamond") ? 0 : value.includes("deepswe") ? 1 : value.includes("terminalbench") ? 2 : value.includes("automationbench") ? 3 : value.includes("mmmupro") ? 4 : value.includes("gpqa") ? 5 : 6;
};
// 仅归一化平台服务别名，保留官方来源披露的模型标识。
const MODEL_ALIASES: Record<string, string> = { "deepseek-flash": "deepseek-ai/DeepSeek-V4.1-Flash-1017" };
export const displayModelName = (name: string) => MODEL_ALIASES[name.trim().toLowerCase()] ?? name;
const PUBLISHER_PERCENT_DATASETS = new Set(["AutomationBench", "GPQA-Diamond"]);
const HIDDEN_REFERENCE_SOURCE = "official-ms-56a6dd9854fd8da9184dd928cbfa3af6";

export function mergeReferenceGroups(groups: ComparisonGroup[]) {
  // Only align publisher scores with a unique platform metric in the same unit and direction.
  const comparisonKey = (dataset: string, comparison: Record<string, unknown>) =>
    JSON.stringify([dataset, comparison.unit, comparison.direction]);
  const canonical = new Map<string, Set<string>>();
  for (const original of groups) {
    const metric = String(original.comparison.metric);
    if (metric === "publisher_reported_score" || !original.entries.some((row) => row.entry.source_type === "report")) continue;
    const key = comparisonKey(datasetIdentity(String(original.comparison.dataset)), original.comparison);
    const metrics = canonical.get(key) ?? new Set<string>();
    metrics.add(metric);
    canonical.set(key, metrics);
  }
  const merged = new Map<string, { id: string; comparison: Record<string, unknown>; entries: CuratedRecord[] }>();
  for (const original of groups) {
    const dataset = datasetIdentity(String(original.comparison.dataset));
    const rawMetric = String(original.comparison.metric);
    // These publisher references use a 0–100 scale in the official imports.
    const deepSwe = dataset === "DeepSWE";
    const percentageReference = (deepSwe || PUBLISHER_PERCENT_DATASETS.has(dataset))
      && rawMetric === "publisher_reported_score"
      && original.comparison.unit === "points"
      && original.entries.every((row) => row.entry.source_type === "official" && row.entry.value >= 0 && row.entry.value <= 100);
    const referenceUnit = percentageReference ? "%" : original.comparison.unit;
    const candidates = canonical.get(comparisonKey(dataset, { ...original.comparison, unit: referenceUnit }));
    // DeepSWE uses a shared Pass@1 reference view even without platform results.
    const compatibleMetric = percentageReference
      ? (deepSwe && original.comparison.direction === "higher_is_better"
        ? "pass@1"
        : candidates?.has("accuracy") ? "accuracy" : undefined)
      : (candidates?.size === 1 ? [...candidates][0] : undefined);
    const metric = rawMetric === "publisher_reported_score" && compatibleMetric ? compatibleMetric : rawMetric;
    const unit = metric !== rawMetric ? referenceUnit : original.comparison.unit;
    const comparison = { ...original.comparison, dataset, metric, unit } as Record<string, unknown>;
    const group = { ...original, comparison, entries: original.entries.filter((row) => row.entry.source_type !== "manual" && row.entry.source_key !== HIDDEN_REFERENCE_SOURCE) };
    if (!group.entries.length) continue;
    const entries = group.entries.map((row) => ({ ...row, entry: { ...row.entry, model_name: row.entry.source_type === "report" ? displayModelName(row.entry.model_name) : row.entry.model_name } }));
    const key = JSON.stringify([comparison.dataset, comparison.metric, comparison.unit, comparison.direction]);
    const existing = merged.get(key);
    if (existing) existing.entries.push(...entries);
    else merged.set(key, { id: key, comparison: { ...comparison, source_name: "平台实测与官方公开成绩", source_type: "mixed", scope: "各记录范围见模型说明" }, entries });
  }
  return merged;
}
