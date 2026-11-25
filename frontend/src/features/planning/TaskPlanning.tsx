import { duration, ElapsedTime, PlanEstimate, type Report } from "./PlanEstimate";
import { TableWrap } from "../../shared/ui/TableWrap";
import { PlanningSelect } from "./PlanningSelect";
import { serviceLabel } from "../resources/serviceKind";
import { ServiceBindings } from "../resources/ServiceBindings";
import { groupSshHosts } from "./sshHosts";
import { PreflightNodes, type PreflightEvidence, type PreflightProgress } from "./PreflightNodes";
import { ResourceMultiSelect } from "./ResourceMultiSelect";
import { ModelServices } from "../resources/ModelServices";
import { ProbeProgress } from "../evaluation/ProbeProgress";
import { Clock3, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiGetPage, apiPost } from "../../shared/api";
import type { Resource, Target } from "../evaluation/types";
import { useOptions } from "../evaluation/hooks";
import { usePolling } from "../../shared/hooks/usePolling";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { StandardInputs } from "../catalog/StandardInputs";
import { ExecutionBindings } from "../catalog/ExecutionBindings";
import { DatasetManifests } from "../catalog/DatasetManifests";

type Options = {
  compilations: { adaptor_revision?: string; runtime_config?: Record<string, unknown>; id: string; label?: string; sha256: string; target_id: string; dataset: string; input_ready: boolean; config: { subcommand: string; params: Record<string, unknown> } }[];
  manifests: { id: string; dataset: string; scope: string; sample_count: number; sha256?: string }[];
  curves: { id: string; target_id: string; resource_id: string; resource_kind: string; measured_at: string }[];
};
type DatasetCheck = { preflight_evidence?: PreflightEvidence; task_id: string; assigned_resource_id?: string; dataset: string; data_path: string | null; tool_revision: string | null; expected_tool_revision: string; blocking_reasons: string[]; warnings?: string[] };
const preflightReasons: Record<string, string> = {
  dataset_not_validated: "该资源尚未完成此数据集的小样本验收",
  dataset_path_unavailable: "执行容器无法访问数据目录",
  dataset_path_missing: "配置缺少数据目录",
  harbor_network_unavailable: "Harbor 网络容量不可用",
  harbor_private_daemon_unavailable: "Harbor 私有 Docker 无法启动",
  harbor_private_daemon_image_import_failed: "Harbor 私有 Docker 无法导入试运行镜像",
  ssh_execution_template_changed: "SSH 执行模板已变更，请重新检查环境",
  tool_identity_mismatch: "AISBench 版本或评分文件校验不匹配",
  tool_environment_preflight_failed: "测评工具无法加载所选清单",
  no_supported_datasets: "至少一个执行资源没有通过检查的数据集",
};
const describePreflight = (reasons: string[]) =>
  reasons.map(reason => preflightReasons[reason] ?? reason).join("；");
type Job = { id: string; state: string; created_at?: string; updated_at?: string; result?: { preflight_valid_until?: string; preflight_progress?: PreflightProgress; progress?: { stage: string; current_concurrency?: number | null; completed_levels: number; total_levels: number; observed_at?: string } | null; report?: Report; throughput_profile_id?: string; reason?: string; dispatch_blocked?: boolean; remote_check?: { state: string; checked_at: string }; execution_ready?: boolean; supported_datasets?: string[]; blocking_reasons?: string[]; dataset_checks?: DatasetCheck[]; tool_versions?: Record<string, { expected: string; actual: string | null }> } };
const datasets = ["GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"];
function StrategyChoice({ label, parallel, disabled = false, onChange }: { label: string; parallel: boolean; disabled?: boolean; onChange: (parallel: boolean) => void }) {
  return <div className="strategy-choices" role="group" aria-label={label}>
    <button type="button" aria-pressed={!parallel} onClick={() => onChange(false)}>串行执行</button>
    <button type="button" aria-pressed={parallel} disabled={disabled} onClick={() => onChange(true)}>并行执行</button>
  </div>;
}

export function TaskPlanning({ poolRevision, onManagePool }: { poolRevision: number; onManagePool: (add?: boolean) => void }) {
  const targets = useOptions<Target>("/target-bindings");
  const ssh = useOptions<Resource>("/ssh-resources");
  const retryResources = useRef(ssh.retry);
  useEffect(() => { if (poolRevision) retryResources.current(); }, [poolRevision]);
  const [target, setTarget] = useState("");
  const [addingService, setAddingService] = useState(false);
  const resourceKind = "customer_ssh";
  const [resource, setResource] = useState("");
  const manualNodeSelection = useRef(false);
  const [resourceIds, setResourceIds] = useState<string[]>([]);
  const [options, setOptions] = useState<Options>({ compilations: [], manifests: [], curves: [] });
  const [selection, setSelection] = useState<Record<string, { compilation: string; manifest: string }>>({});
  const [enabled, setEnabled] = useState<string[]>([]);
  const [curve, setCurve] = useState("");
  const [requestedParallel, setParallel] = useState(1);
  const [job, setJob] = useState<Job | null>(null);
  const [adviceJob, setAdviceJob] = useState<Job | null>(null);
  const [probeLookup, setProbeLookup] = useState(false);
  const [probeLookupFailed, setProbeLookupFailed] = useState(false);
  const [probe, setProbe] = useState<Job | null>(null);
  const checkDetails = useRef<HTMLDetailsElement>(null);
  const firstBlocker = useRef<HTMLDetailsElement>(null);
  const [preflight, setPreflight] = useState<Job | null>(null);
  const [checkRequest, setCheckRequest] = useState(0);
  const [checkExpired, setCheckExpired] = useState(false);
  const [concurrency, setConcurrency] = useState<Record<string, number>>({});
  const [staleEstimate, setStaleEstimate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [probeReview, setProbeReview] = useState(false);
  const [closeReason, setCloseReason] = useState("");
  const [closeAcknowledged, setCloseAcknowledged] = useState(false);
  const probeDialog = useRef<HTMLDialogElement>(null);
  const [curveText, setCurveText] = useState("");
  const [levels, setLevels] = useState("1,2,4,8");
  const [promptTokens, setPromptTokens] = useState(512);
  const [maxTokens, setMaxTokens] = useState(512);
  const generation = useRef(0);
  const [estimating, setEstimating] = useState(false);
  const probeIntent = useRef<{ body: string; key: string } | null>(null);
  const pending = useRef<{ body: string; key: string } | null>(null);
  const resources = ssh;
  const hosts = groupSshHosts(resources.rows);
  const selectedHostCount = hosts.filter(host => host.resources.some(row => resourceIds.includes(row.id))).length;
  const refresh = async () => {
    const collected: Options = { compilations: [], manifests: [], curves: [] };
    let offset: number | null = 0;
    while (offset != null) {
      const page: { data: Options; next_offset: number | null } = await apiGetPage<Options>(`/planning/options?offset=${offset}&limit=100`);
      collected.compilations.push(...page.data.compilations);
      collected.manifests.push(...page.data.manifests);
      collected.curves.push(...page.data.curves);
      if (page.next_offset != null && page.next_offset <= offset) throw new Error("测评选项分页异常");
      offset = page.next_offset;
    }
    const stable = (value: unknown): string => {
      if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
      if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${stable(v)}`).join(",")}}`;
      return JSON.stringify(value);
    };
    const seen = new Set<string>();
    collected.compilations = collected.compilations.filter(c => {
      const params = Object.fromEntries(Object.entries(c.config.params).filter(([key]) => !["work_dir", "container_name"].includes(key)));
      const key = stable({ target: c.target_id, dataset: c.dataset, subcommand: c.config.subcommand, adaptor: c.adaptor_revision, runtime: c.runtime_config, params });
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
    const manifests = new Set<string>();
    collected.manifests = collected.manifests.filter(m => {
      const key = stable({ dataset: m.dataset, scope: m.scope, hash: m.sha256 || m.id });
      if (manifests.has(key)) return false;
      manifests.add(key); return true;
    });
    setOptions(collected);
  };
  useEffect(() => { void refresh().catch(() => setMessage("测评选项加载失败，请重试。")); }, []);
  const maxParallel = Math.max(1, Math.min(enabled.length, 4));
  const parallel = Math.min(requestedParallel, maxParallel);
  const allParallel = parallel > 1 && parallel === enabled.length;
  const payload = { target_id: target, resource_id: resource, resource_kind: resourceKind,
    resource_ids: resourceIds,
    throughput_profile_id: curve || null, dataset_concurrency: parallel, recommend: false,
    tasks: enabled.filter(d => datasets.includes(d) && selection[d]?.compilation && selection[d]?.manifest).map(d => ({
      task_id: d.replaceAll("-", "_"), dataset: d, concurrency: concurrency[d] ?? null, compilation_id: selection[d].compilation, manifest_id: selection[d].manifest,
    })) };
  const fingerprint = JSON.stringify(payload);
  useEffect(() => { setParallel(v => Math.min(v, maxParallel)); }, [maxParallel]);
  const requestedCheck = useRef("");
  const preflightFingerprint = JSON.stringify({
    target_id: target, resource_id: resource, resource_kind: resourceKind, resource_ids: resourceIds,
    tasks: payload.tasks.map(({ task_id, dataset, compilation_id, manifest_id }) => ({
      task_id, dataset, compilation_id, manifest_id,
    })).sort((a, b) => a.task_id.localeCompare(b.task_id)),
  });
  useEffect(() => {
    generation.current++; if (job) setStaleEstimate(true); setJob(null); setAdviceJob(null);
  }, [fingerprint]);
  useEffect(() => { setProbeReview(false); setCurve(""); }, [target, resource, resourceKind]);
  const validUntil = preflight?.result?.preflight_valid_until;
  useEffect(() => {
    if (!validUntil) return;
    const timer = setTimeout(() => {
      setCheckExpired(true);
      setPreflight(null);
    }, Math.max(0, Date.parse(validUntil) - Date.now()));
    return () => clearTimeout(timer);
  }, [validUntil]);
  useEffect(() => {
    setSelection(current => {
      const next = { ...current }; let changed = false;
      for (const [dataset, selected] of Object.entries(current)) {
        const config = options.compilations.find(c => c.id === selected.compilation);
        const ids = config?.runtime_config?.resource_ids;
        if (Array.isArray(ids) && !resourceIds.some(id => ids.includes(id))) { next[dataset] = { compilation: "", manifest: "" }; changed = true; }
      }
      return changed ? next : current;
    });
  }, [resource, resourceIds, options.compilations]);
  // Poll active planning jobs sequentially; stops naturally when nothing is active.
  usePolling(
    async () => {
      const jobs = [job, adviceJob, probe, preflight].filter((j): j is Job => !!j && (["pending", "running"].includes(j.state) || (j.id === probe?.id && j.state === "unresolved")));
      if (!jobs.length) return;
      try {
        const rows = await Promise.all(jobs.map(j => apiGet<Job>(`/planning/probes/${j.id}`)));
        for (const row of rows) {
          if (row.id === job?.id) setJob(current => current?.id === row.id ? row : current);
          if (row.id === adviceJob?.id) setAdviceJob(current => current?.id === row.id ? row : current);
          if (row.id === preflight?.id) setPreflight(current => current?.id === row.id ? row : current);
          if (row.id === probe?.id) { setProbe(row); if (row.result?.throughput_profile_id) { void refresh(); setCurve(row.result.throughput_profile_id); } }
        }
      } catch { setMessage("后台状态暂不可读，请刷新查证，勿重复启动探测。"); }
    },
    { intervalMs: 2000 },
  );
  useEffect(() => {
    if (!target || !resource) return;
    let stopped = false;
    setProbe(null); setProbeLookup(true); setProbeLookupFailed(false);
    void apiGet<Job | null>(`/planning/active-probe?target_id=${encodeURIComponent(target)}&resource_id=${encodeURIComponent(resource)}&resource_kind=${resourceKind}`).then(row => { if (!stopped) setProbe(row); })
      .catch(() => { if (!stopped) { setProbeLookupFailed(true); setMessage("原探测状态查询失败，暂不能启动新探测，请刷新查证。"); } })
      .finally(() => { if (!stopped) setProbeLookup(false); });
    return () => { stopped = true; };
  }, [target, resource, resourceKind]);
  useEffect(() => { const dialog = probeDialog.current; if (probeReview && dialog && !dialog.open) dialog.showModal(); if (!probeReview && dialog?.open) dialog.close(); }, [probeReview]);
  const action = async (operation: () => Promise<void>) => {
    setBusy(true); setMessage("");
    try { await operation(); } catch (error) { setMessage(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const probeLevels = levels.split(",").map(Number);
  const validLevels = probeLevels.length > 0 && probeLevels.every((n, i) => Number.isInteger(n) && n >= 1 && n <= 64 && (i === 0 || n > probeLevels[i - 1]));
  const requestBudget = 2 * probeLevels.reduce((sum, n) => sum + Math.max(2, n), 0);
  const incomplete = enabled.some(d => !selection[d]?.compilation || !selection[d]?.manifest);
  const ready = !!target && !!resource && payload.tasks.length > 0 && !incomplete;
  const report = job?.state === "completed" ? job.result?.report : undefined;
  const advice = adviceJob?.state === "completed" ? adviceJob.result?.report : undefined;
  const adviceQueued = adviceJob?.state === "pending";
  const adviceRunning = adviceJob?.state === "running";
  const adviceActive = adviceQueued || adviceRunning;
  const adviceNotice = adviceJob && !adviceActive && !advice
    ? ({
        failed: "优化建议生成失败",
        cancelled: "优化建议已取消",
        completed: "未返回可用的优化建议",
      } as Record<string, string>)[adviceJob.state] ?? "优化建议状态待确认"
    : null;
  const probeBlocked = !!probe && ["pending", "running", "unresolved"].includes(probe.state);
  const checking = !!preflight && ["pending", "running"].includes(preflight.state);
  const preflightLabel = !preflight ? (checkExpired ? "已过期" : "未检查") : ({ pending: "排队中", running: "检查中", completed: preflight.result?.execution_ready ? "检查通过" : "存在阻塞", failed: "检查失败", cancelled: "已取消" } as Record<string, string>)[preflight.state] || "状态待确认";
  const preflightTone = checking ? "checking" : preflight?.result?.execution_ready ? "passed" : "blocked";
  const autoFillDataset = (dataset: string, active: boolean) => {
    setEnabled(rows => active ? [...new Set([...rows, dataset])] : rows.filter(row => row !== dataset));
    if (!active) { setSelection(rows => ({ ...rows, [dataset]: { compilation: "", manifest: "" } })); return; }
    const candidates = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset && (!Array.isArray(c.runtime_config?.resource_ids) || (c.runtime_config.resource_ids as string[]).some(id => resources.rows.some(r => r.id === id))));
    const chosen = candidates[0];
    const full = options.manifests.filter(m => m.dataset === dataset && m.scope === "full");
    setSelection(rows => ({ ...rows, [dataset]: { compilation: chosen?.id || "", manifest: full.length === 1 ? full[0].id : "" } }));
    const bound = chosen?.runtime_config?.resource_ids;
    if (!manualNodeSelection.current && Array.isArray(bound)) {
      const matching = bound.filter((id): id is string => typeof id === "string" && resources.rows.some(r => r.id === id));
      if (matching.length) { setResourceIds(ids => [...new Set([...ids, ...matching])]); setResource(current => current || matching[0]); }
    }
  };
  const allDatasetsEnabled = datasets.every(dataset => enabled.includes(dataset));
  const toggleAllDatasets = () => {
    for (const dataset of datasets) {
      if (enabled.includes(dataset) === allDatasetsEnabled) {
        autoFillDataset(dataset, !allDatasetsEnabled);
      }
    }
  };
  const selectAllButton = <button type="button" className="link dataset-select-all" onClick={toggleAllDatasets}>
    {allDatasetsEnabled ? "取消全选" : "全选"}
  </button>;
  useEffect(() => {
    if (!target || !enabled.length) return;
    let changed = false;
    const next = { ...selection };
    const boundIds = new Set(resourceIds);
    for (const dataset of enabled) {
      const candidates = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset && (!Array.isArray(c.runtime_config?.resource_ids) || (c.runtime_config.resource_ids as string[]).some(id => resources.rows.some(r => r.id === id))));
      const current = candidates.find(c => c.id === selection[dataset]?.compilation);
      const chosen = current || candidates[0];
      if (!chosen) continue;
      const allowed = chosen.runtime_config?.manifest_ids;
      const manifests = options.manifests.filter(m => m.dataset === dataset && (!Array.isArray(allowed) || allowed.includes(m.id)));
      const full = manifests.filter(m => m.scope === "full");
      const manifest = manifests.some(m => m.id === selection[dataset]?.manifest) ? selection[dataset].manifest : full.length === 1 ? full[0].id : "";
      if (selection[dataset]?.compilation !== chosen.id || selection[dataset]?.manifest !== manifest) { next[dataset] = { compilation: chosen.id, manifest }; changed = true; }
      const ids = chosen.runtime_config?.resource_ids;
      if (!manualNodeSelection.current && Array.isArray(ids)) for (const id of ids) if (typeof id === "string" && resources.rows.some(r => r.id === id)) boundIds.add(id);
    }
    if (changed) setSelection(next);
    const ids = [...boundIds];
    if (ids.length !== resourceIds.length) setResourceIds(ids);
    if (!manualNodeSelection.current && !ids.length && resources.rows.length === 1) {
      setResourceIds([resources.rows[0].id]);
      setResource(resources.rows[0].id);
    } else if (!resource && ids.length) {
      setResource(ids[0]);
    }
  }, [target, enabled, options, resources.rows, selection, resourceIds, resource]);
  const result = preflight?.result;
  const checks = result?.dataset_checks ?? [];
  const failedCheck = checks.find(check => check.blocking_reasons.length);
  const passedCount = checks.filter(check => !check.blocking_reasons.length).length;
  const terminal = !!preflight && !checking;
  const blocked = terminal && !result?.execution_ready;
  const overallReasons = (result?.blocking_reasons ?? []).filter(reason =>
    !checks.some(check => check.blocking_reasons.includes(reason)));
  const failureReason = failedCheck ? `${failedCheck.dataset} · ${describePreflight(failedCheck.blocking_reasons)}`
    : describePreflight(overallReasons) || result?.reason || (preflight?.state === "cancelled"
      ? "环境检查已取消，请重新检查。" : "请检查节点连接和后台任务状态后重新检查。");
  const missingInput = !target ? "请选择模型服务" : !enabled.length ? "请启用至少一个数据集"
    : incomplete ? `请补全 ${enabled.filter(d => !selection[d]?.compilation || !selection[d]?.manifest).join("、")} 的配置或样本范围`
    : !resource ? "请选择 SSH 节点" : "";
  const blocker = missingInput || (checkExpired ? "环境检查已过期，请重新检查。" : blocked ? failureReason : "");
  function revealBlocker() {
    const details = checkDetails.current;
    if (!details) return;
    details.open = true;
    const target = firstBlocker.current ?? details;
    target.open = true;
    target.querySelector("summary")?.focus();
    target.scrollIntoView({ block: "center" });
  }
  useEffect(() => {
    if (!curve || !ready || !preflight?.result?.execution_ready) return;
    let stopped = false;
    const timer = setTimeout(() => {
      const revision = generation.current;
      setEstimating(true);
      void apiPost<Job>("/planning/plans", { ...payload, recommend: false }).then(next => {
        if (!stopped && revision === generation.current) { setStaleEstimate(false); setJob(next); }
      }).catch(error => { if (!stopped) setMessage(`自动估算失败：${error instanceof Error ? error.message : "请重试"}`); })
        .finally(() => { if (!stopped) setEstimating(false); });
    }, 500);
    return () => { stopped = true; clearTimeout(timer); setEstimating(false); };
  }, [fingerprint, ready, preflight?.result?.execution_ready]);
  const currentConcurrency = (d: string) => {
    const params = options.compilations.find(c => c.id === selection[d]?.compilation)?.config.params;
    return concurrency[d] ?? Number(params?.batch_size ?? params?.n_concurrent_trials ?? 1);
  };
  const sampleCount = payload.tasks.reduce((sum, t) => sum + (options.manifests.find(m => m.id === t.manifest_id)?.sample_count || 0), 0);
  useEffect(() => {
    setPreflight(null);
    setCheckExpired(false);
    setMessage("");
    if (!ready || !requestedCheck.current || requestedCheck.current !== preflightFingerprint) return;
    let stopped = false;
    const timer = setTimeout(() => { requestedCheck.current = ""; void apiPost<Job>("/planning/resources/preflight", JSON.parse(preflightFingerprint))
      .then(result => { if (!stopped) setPreflight(result); })
      .catch(() => { if (!stopped) setMessage("环境检查失败，请重试。"); }); }, 350);
    return () => { stopped = true; clearTimeout(timer); };
  // Resource checks follow execution selection, independently of optional estimation inputs.
  }, [preflightFingerprint, ready, checkRequest]);
  return <div className="planning-layout"><section className="card stack planning-card" aria-label="发起测评">
    <h2>1. 模型服务</h2>
    <p className="planning-intro">支持 GPQA、MMMU-Pro、DeepSWE、AutomationBench 的全量或已绑定 Lite 清单。Agent 工作流通过 AISBench Harbor 执行，需绑定配置与清单并通过环境检查。</p>
    <div className="planning-fields">
      <div className="planning-service-field"><div className="planning-service-heading"><label htmlFor="planning-service">模型服务</label><ManagementDrawer title="管理服务" onDismiss={targets.retry}><ModelServices /></ManagementDrawer></div><PlanningSelect id="planning-service" label="规划模型服务" value={target} options={targets.rows.map(t => ({ id: t.id, label: t.service_name || t.remote_model, detail: `${serviceLabel(t.service_kind)} · ${t.remote_model} · ${t.base_url} · ${t.id.slice(0, 8)}` }))} onChange={id => { setTarget(id); setSelection({}); }} onAdd={() => setAddingService(true)} /><ManagementDrawer title="新增模型服务" hideTrigger open={addingService} onOpenChange={setAddingService} onDismiss={targets.retry}><ServiceBindings /></ManagementDrawer></div>
    </div>
    {targets.error && <p role="alert">{targets.error}</p>}
    <h2>2. 数据集与样本范围</h2>
    <p className="muted">勾选后默认选择第一个可用配置。只有一个 SSH 节点时会自动选中。配置齐备后自动检查环境。</p>
    <div className="dataset-select-all-mobile">{selectAllButton}</div>
    <TableWrap><table className="planning-table"><thead><tr><th scope="col">{selectAllButton}</th><th>数据集</th><th>执行配置</th><th>样本范围</th><th>状态</th></tr></thead><tbody>{datasets.map(d => {
      const active = enabled.includes(d);
      const chosenConfig = options.compilations.find(c => c.id === selection[d]?.compilation);
      const allowedManifests = chosenConfig?.runtime_config?.manifest_ids;
      const availableManifests = options.manifests.filter(manifest =>
        manifest.dataset === d && (!Array.isArray(allowedManifests) || allowedManifests.includes(manifest.id)));
      const check = preflight?.result?.dataset_checks?.find(row => row.dataset === d);
      const assigned = resources.rows.find(r => r.id === check?.assigned_resource_id);
      const configs = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === d && (!Array.isArray(c.runtime_config?.resource_ids) || resources.rows.some(r => (c.runtime_config!.resource_ids as string[]).includes(r.id))));
      return <tr key={d}><td><input type="checkbox" aria-label={`启用 ${d}`} checked={active} onChange={e => { autoFillDataset(d, e.target.checked); }} /></td><td>{d}</td><td data-label="执行配置"><select disabled={!active || !target} aria-label={`${d} 执行配置`} value={selection[d]?.compilation || ""} onChange={e => setSelection(rows => ({ ...rows, [d]: { ...rows[d], compilation: e.target.value } }))}><option value="">{!target ? "先选择模型服务" : !configs.length ? "暂无可用配置" : "请选择执行配置"}</option>{configs.map((c, index) => <option key={c.id} value={c.id}>{d} · {c.config.subcommand === "llm_accuracy" ? "精度测评" : "Agent 测评"}{configs.length > 1 ? ` · 方案 ${index + 1}` : ""}</option>)}</select>{active && chosenConfig && assigned && <small className="muted">{check?.tool_revision && `${chosenConfig.config.subcommand === "harbor_agent" ? "Harbor" : "AISBench"} ${check.tool_revision.slice(0, 12)}`}</small>}</td><td data-label="样本范围"><select disabled={!active || !selection[d]?.compilation} aria-label={`${d} 样本范围`} value={selection[d]?.manifest || ""} onChange={e => setSelection(rows => ({ ...rows, [d]: { ...rows[d], manifest: e.target.value } }))}><option value="">请选择已绑定清单</option>{availableManifests.map(m => <option key={m.id} value={m.id}>{m.scope === "full" ? "全量" : "Lite"} · {m.sample_count} 个样本 · {m.id.slice(0, 8)}</option>)}</select></td><td><span className="planning-row-state">{!active ? "未启用" : !configs.length ? "需配置" : selection[d]?.compilation && selection[d]?.manifest ? "已配置" : "待补全"}</span></td></tr>;
    })}</tbody></table></TableWrap>
    {enabled.map(dataset => {
      const bound = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset);
      if (!bound.length || bound.some(c => !Array.isArray(c.runtime_config?.resource_ids) || resourceIds.some(id => (c.runtime_config!.resource_ids as string[]).includes(id)))) return null;
      const names = [...new Set(bound.flatMap(c => (c.runtime_config?.resource_ids as string[]).map(id => ssh.rows.find(r => r.id === id)?.binding_key || id)))];
      return <p className="notice" key={dataset}>{dataset} 配置需使用执行资源：{names.join("、")}。请切换资源后选择配置。</p>;
    })}
    <details className="planning-management"><summary>管理配置与清单 · 缺少配置时在此维护</summary>
    <div className="inline"><ManagementDrawer title="配置标准输入"><StandardInputs /></ManagementDrawer><ManagementDrawer title="管理样本清单"><DatasetManifests /></ManagementDrawer><ManagementDrawer title="登记执行规则"><ExecutionBindings /></ManagementDrawer><button onClick={() => void action(refresh)}>刷新配置与清单</button></div>
    </details>
    <p className="muted">执行配置来自标准输入编译；并发仅为默认值，请在下方执行策略中自定义调整。样本清单须绑定已登记的工具与评分规则。</p>
    {incomplete && <p role="alert">请为已启用的数据集补全执行配置和样本范围。</p>}
    <div className="spread"><h2>3. SSH 执行资源</h2><button type="button" onClick={() => onManagePool()}>管理 SSH 资源池</button></div>
    {resources.loading ? <p role="status">正在加载 SSH 节点…</p> : resources.error ? <div className="inline"><p role="alert">{resources.error}</p><button onClick={resources.retry}>重新加载</button></div> : !resources.rows.length ? <div className="notice"><p>资源池暂无可用的 SSH 节点。</p><button type="button" onClick={() => onManagePool(true)}>添加 SSH 节点</button></div> : <ResourceMultiSelect hosts={hosts} showChips={!preflight || (checking && !result?.preflight_progress && !checks.length)} value={resourceIds} onChange={ids => { manualNodeSelection.current = true; setResourceIds(ids); setResource(ids[0] || ""); }} />}
    <div className="planning-actions">
      <button disabled={busy || !ready || checking} onClick={() => { requestedCheck.current = preflightFingerprint; setCheckRequest(n => n + 1); }}>{checking ? "正在检查…" : preflight || checkExpired ? "重新检查" : "环境检查"}</button>
      <p className="muted">仅检查环境，不发起测评。</p>
    </div>
    {preflight && <PreflightNodes hosts={hosts} selectedIds={resourceIds} datasets={enabled} job={preflight} />}
    {terminal && <details key={preflight.id} ref={checkDetails} className="planning-management preflight-details" open={blocked}>
      <summary>查看环境检查详情</summary>
      {overallReasons.length > 0 && <p>{describePreflight(overallReasons)}</p>}
      {blocked && !failedCheck && !overallReasons.length && <p>{failureReason}</p>}
      {checks.map(check => <details key={check.task_id} ref={check === failedCheck ? firstBlocker : undefined} open={!!check.blocking_reasons.length}>
        <summary>{check.dataset}{check.blocking_reasons.length > 0 && " · 存在阻塞"}</summary>
        {!!check.blocking_reasons.length && <p>{describePreflight(check.blocking_reasons)}</p>}
        <dl>
          <dt>资源配置</dt><dd>{resources.rows.find(row => row.id === check.assigned_resource_id)?.binding_key || "待匹配"}</dd>
          {check.preflight_evidence && <><dt>预检容器 ID</dt><dd><code>{check.preflight_evidence.container_id}</code></dd><dt>原始预检时间</dt><dd>{new Date(check.preflight_evidence.checked_at).toLocaleString("zh-CN")}</dd><dt>来源预检任务</dt><dd>{check.preflight_evidence.source_job_id}</dd></>}
          <dt>数据路径</dt><dd>{check.data_path || "未配置"}</dd>
          <dt>工具版本</dt><dd>{check.tool_revision?.slice(0, 12) || `校验未通过（要求 ${check.expected_tool_revision?.slice(0, 12) || "未知"}）`}</dd>
        </dl>
      </details>)}
      {result?.tool_versions && <p className="muted">Planner {result.tool_versions.planner?.actual?.slice(0, 12) || "版本未知"} · Adaptor {result.tool_versions.adaptor?.actual?.slice(0, 12) || "版本未知"}</p>}
    </details>}
    {terminal && checks.filter(check => check.warnings?.includes("dataset_not_validated")).map(check =>
      <small className="muted" key={check.task_id}>{check.dataset} 尚无小样本验收记录，首次试跑由你决定。</small>
    )}
    <h2>4. 执行策略</h2>
    <div className="execution-strategy">
      <section className="strategy-card strategy-datasets" aria-label="数据集执行设置">
        <div className="strategy-card-heading"><h3>数据集之间</h3><span>已选 {enabled.length} 个数据集</span></div>
        <div className="strategy-controls">
          <div><span className="strategy-field-label">执行方式</span><StrategyChoice label="数据集执行策略" parallel={parallel > 1} disabled={enabled.length < 2} onChange={value => setParallel(value ? maxParallel : 1)} /></div>
          <label>同时运行的数据集上限
            <select aria-label="数据集同时运行数" value={parallel} disabled={parallel === 1} onChange={e => setParallel(Number(e.target.value))}>
              {parallel === 1 ? <option value={1}>1 个</option> : Array.from({ length: maxParallel - 1 }, (_, index) => index + 2).map(count =>
                <option key={count} value={count}>{count} 个</option>
              )}
            </select>
          </label>
        </div>
        <p className="strategy-help">{enabled.length === 0 ? "请先选择数据集。" : enabled.length === 1 ? "当前选择了一个数据集，可单独设置样本并行。" : parallel > 1 ? "实际同时运行数量取决于可用资源。" : "按下方顺序逐个执行。"}</p>
        {enabled.length > 1 && <div className="strategy-order">
          <span className="strategy-field-label">{allParallel ? "并行运行计划" : parallel > 1 ? "启动优先级" : "执行顺序"}</span>
          {allParallel ? <ul aria-label="并行数据集">{enabled.map(dataset => <li key={dataset}>{dataset}</li>)}</ul> :
            <ol>{enabled.map((dataset, index) => <li key={dataset}>
              <span><small>{index + 1}</small>{dataset}</span>
              <button type="button" className="link" disabled={index === 0} aria-label={`${dataset} 前移`} onClick={() => setEnabled(order => {
                const next = [...order];
                [next[index - 1], next[index]] = [next[index], next[index - 1]];
                return next;
              })}>前移</button>
            </li>)}</ol>}
        </div>}
      </section>
      {payload.tasks.map(t => <section className={`strategy-card${payload.tasks.length === 1 ? " strategy-sample-single" : ""}`} key={t.dataset} aria-label={`${t.dataset} 样本执行设置`}>
        <div className="strategy-card-heading"><h3>{t.dataset} 样本</h3><span>数据集内部</span></div>
        <div className="strategy-controls">
          <div><span className="strategy-field-label">执行方式</span><StrategyChoice label={`${t.dataset} 样本执行策略`} parallel={currentConcurrency(t.dataset) > 1} onChange={value => setConcurrency(v => ({ ...v, [t.dataset]: value ? 2 : 1 }))} /></div>
          <label>同时执行的样本数<input aria-label={`${t.dataset} case 并发`} type="number" min={1} max={256} disabled={currentConcurrency(t.dataset) <= 1} value={currentConcurrency(t.dataset)} onChange={e => setConcurrency(v => ({ ...v, [t.dataset]: Number(e.target.value) }))} /></label>
        </div><p className="strategy-help">{currentConcurrency(t.dataset) > 1 ? "并行处理多个样本；以此处设置覆盖配置默认并发，仍受资源能力限制。" : "每次处理一个样本，完成后再执行下一个。"}</p>
      </section>)}
    </div>
    <details className="planning-throughput"><summary>吞吐曲线与主动探测<span>高级设置 · 可使用已有曲线或发起真实探测</span></summary><div className="probe-content"><h3>主动探测</h3><div className="probe-fields">
      <label>并发档位<input value={levels} onChange={e => { setLevels(e.target.value); setProbeReview(false); }} /></label>
      <label>输入 token<input type="number" min={1} max={4096} value={promptTokens} onChange={e => { setPromptTokens(Number(e.target.value)); setProbeReview(false); }} /></label>
      <label>最大输出 token<input type="number" min={1} max={4096} value={maxTokens} onChange={e => { setMaxTokens(Number(e.target.value)); setProbeReview(false); }} /></label>
      </div><p className="probe-budget">包含非流式回退在内最多 {validLevels ? requestBudget : "—"} 次请求，最多 {validLevels ? requestBudget * maxTokens : "—"} 个输出 token；可能产生模型调用费用。</p>
      <div className="probe-actions"><button disabled={busy || !target || !resource || !validLevels || probeBlocked || probeLookup || probeLookupFailed} onClick={() => setProbeReview(true)}>启动吞吐探测</button></div>
      {probe && <ProbeProgress job={probe} />}
      {probeBlocked && <div className="inline"><button disabled={busy} onClick={() => void action(async () => { setCloseAcknowledged(false); setProbe(await apiPost<Job>(`/planning/probes/${probe!.id}/reconcile`, {})); })}>查询探测状态</button><button disabled={busy} onClick={() => void action(async () => { await apiPost(`/planning/probes/${probe!.id}/cancel`, {}); setProbe(await apiGet<Job>(`/planning/probes/${probe!.id}`)); })}>取消探测</button></div>}
      {probe?.state === "unresolved" && probe.result?.remote_check?.state === "unknown" && <details className="probe-import"><summary>历史异常记录处理</summary><p>仅结束平台记录，不停止远程进程，不认定原探测成功或未产生费用；原始异常与查证记录会保留。新探测需另行确认预算。</p><label>处理原因<textarea aria-label="历史探测处理原因" value={closeReason} onChange={e => setCloseReason(e.target.value)} /></label><label><input type="checkbox" checked={closeAcknowledged} onChange={e => setCloseAcknowledged(e.target.checked)} />确认原执行结果及用量仍未知，保留历史后结束此记录</label><button disabled={busy || !closeAcknowledged || closeReason.trim().length < 5} onClick={() => void action(async () => { setProbe(await apiPost<Job>(`/planning/probes/${probe.id}/close`, { reason: closeReason.trim(), acknowledge_unknown: true })); setCloseAcknowledged(false); setCloseReason(""); const next = await apiGet<Job | null>(`/planning/active-probe?target_id=${encodeURIComponent(target)}&resource_id=${encodeURIComponent(resource)}&resource_kind=${resourceKind}`); setProbe(next); })}>结束历史记录</button></details>}
      <dialog ref={probeDialog} className="probe-budget-dialog" aria-labelledby="probe-budget-heading" onCancel={() => setProbeReview(false)}>
        <h3 id="probe-budget-heading">确认吞吐探测</h3><p>这会额外调用模型，不会启动测评任务。</p><dl><dt>并发档位</dt><dd>{levels}</dd><dt>最多模型请求</dt><dd>{requestBudget} 次（含非流式回退）</dd><dt>每次最大输出</dt><dd>{maxTokens} tokens</dd><dt>最多总输出</dt><dd>{requestBudget * maxTokens} tokens</dd></dl><p className="notice">可能产生模型调用费用。原任务状态未查清时不能重复启动。</p>
        <div className="inline"><button disabled={busy} onClick={() => setProbeReview(false)}>返回修改</button><button className="primary" disabled={busy || probeBlocked || probeLookup || probeLookupFailed} onClick={() => void action(async () => {
          const body = { target_id: target, resource_id: resource, resource_kind: resourceKind, concurrency: probeLevels, prompt_tokens: promptTokens, max_tokens: maxTokens }; const serialized = JSON.stringify(body);
          if (probeIntent.current?.body !== serialized || (probe && ["completed", "failed", "cancelled"].includes(probe.state))) probeIntent.current = { body: serialized, key: crypto.randomUUID() };
          try { setProbe(await apiPost<Job>("/planning/probes", body, probeIntent.current.key)); setProbeReview(false); }
          catch (error) {
            try { const active = await apiGet<Job | null>(`/planning/active-probe?target_id=${encodeURIComponent(target)}&resource_id=${encodeURIComponent(resource)}&resource_kind=${resourceKind}`); if (active) { setProbe(active); setProbeReview(false); } }
            catch { setProbeLookupFailed(true); }
            throw error;
          }
        })}>启动探测</button></div>
      </dialog>
      <details className="probe-import"><summary>导入已有吞吐曲线</summary><div className="probe-import-content"><label>曲线 JSON<textarea aria-label="曲线 JSON" rows={5} placeholder="在此粘贴吞吐曲线 JSON" spellCheck={false} value={curveText} onChange={e => setCurveText(e.target.value)} /></label>
      <button disabled={busy || !target || !resource || !curveText} onClick={() => void action(async () => { const saved = await apiPost<{ id: string }>("/planning/throughput-profiles", { target_id: target, resource_id: resource, resource_kind: resourceKind, curve: JSON.parse(curveText) }); await refresh(); setCurve(saved.id); })}>导入吞吐曲线</button></div></details>
    </div></details>
    <label>吞吐来源<select aria-label="吞吐来源" value={curve} onChange={e => setCurve(e.target.value)}><option value="">请选择或探测</option>{options.curves.filter(c => c.target_id === target && c.resource_id === resource && c.resource_kind === resourceKind).map(c => <option key={c.id} value={c.id}>{new Date(c.measured_at).toLocaleString()} / {c.id.slice(0, 8)}</option>)}</select></label>
    </section><aside className="card stack planning-summary" aria-label="任务摘要">
    <h2>任务摘要</h2>
    <dl className="planning-checklist">
      <div><dt>模型服务</dt><dd>{targets.rows.find(t => t.id === target)?.remote_model || "待选择"}</dd></div>
      <div><dt>测评范围</dt><dd>{enabled.length} 个数据集 · {sampleCount.toLocaleString("zh-CN")} 个样本</dd></div>
      <div><dt>候选主机</dt><dd>{selectedHostCount ? `已选 ${selectedHostCount} 台` : "待选择"}</dd></div>
      {result?.execution_ready && <div><dt>执行容器</dt><dd>计划启动 {enabled.length} 个独立容器</dd></div>}
      <div><dt>数据集并行</dt><dd>{enabled.length ? `最多 ${parallel} 个` : "待选择"}</dd></div>
      {payload.tasks.length > 0 && <div><dt>样本并行</dt><dd>{payload.tasks.map(({ dataset }) => `${dataset} ${currentConcurrency(dataset)}`).join(" · ")}</dd></div>}
      <div><dt>环境检查</dt><dd className="preflight-summary">
        <span role="status" className={`preflight-status ${preflight ? preflightTone : "idle"}`}>
          {preflight?.state === "completed" && result?.execution_ready && checks.length ? `${passedCount}/${enabled.length} 通过` : preflightLabel}
        </span>
        {checking && preflight && <ElapsedTime key={preflight.id} label="环境检查已耗时" startedAt={preflight.created_at} />}
        {terminal && preflight.created_at && preflight.updated_at && <small>· 耗时 {duration((Date.parse(preflight.updated_at) - Date.parse(preflight.created_at)) / 1000)}</small>}
      </dd></div>
    </dl>
    <div className="planning-duration" role="status"><span>预计总耗时</span><div className="estimate-status-line"><strong>{job?.state === "pending" ? "估算排队中" : estimating || job?.state === "running" ? "正在估算…" : report ? duration(report.estimate.total_duration_sec) : "暂无可靠估算"}</strong>{(estimating || (job && ["pending", "running"].includes(job.state))) && <ElapsedTime label="估算已耗时" />}</div><small>{report ? "不含排队及报告分析耗时" : !curve ? "未提供吞吐曲线；可直接按当前配置发起测评" : "按当前参数估算"}</small></div>
    {job?.state === "failed" && <p role="alert">当前参数估算失败：{job.result?.reason || "请重试"}</p>}
    <div className="estimate-actions"><button disabled={busy || estimating || !ready || !curve || (job != null && ["pending", "running"].includes(job.state))} onClick={() => void action(async () => { const revision = generation.current; setEstimating(true); setJob(null); try { const next = await apiPost<Job>("/planning/plans", { ...payload, recommend: false }); if (revision === generation.current) { setStaleEstimate(false); setJob(next); } } finally { setEstimating(false); } })}>重新估算</button>
    <button className={adviceActive ? "advice-in-progress" : undefined} disabled={busy || !ready || !curve || adviceActive} onClick={() => void action(async () => { const revision = generation.current; const next = await apiPost<Job>("/planning/plans", { ...payload, recommend: true }); if (revision === generation.current) setAdviceJob(next); })}>
      {adviceQueued && <Clock3 size={16} aria-hidden="true" />}
      {adviceRunning && <LoaderCircle size={16} aria-hidden="true" />}
      <span aria-live="polite">{adviceQueued ? "优化建议排队中" : adviceRunning ? "正在生成建议" : "获取优化建议"}</span>
    </button></div>
    {report && <details className="estimate-disclosure"><summary>查看当前参数耗时依据</summary><PlanEstimate report={report} /></details>}
    {adviceNotice && <p role="status">{adviceNotice}{adviceJob?.result?.reason && ` · ${adviceJob.result.reason}`}</p>}
    {advice && <section className="stack"><h3>优化建议（尚未采纳）</h3><details className="estimate-disclosure"><summary>查看优化建议与参数差异</summary><PlanEstimate report={advice} /><p>同时运行数据集 {parallel} → {advice.plan.dataset_concurrency}</p>{advice.tasks.map(t => <p key={t.task_id}>{t.task_id}：case 并发 {currentConcurrency(datasets.find(d => d.replaceAll("-", "_") === t.task_id) || t.task_id)} → {advice.plan.case_concurrency[t.task_id]}</p>)}</details><button disabled={busy || advice.conditional} onClick={() => {
      const proposed: Record<string, number> = {};
      for (const d of datasets) { const id = d.replaceAll("-", "_"); if (advice.plan.case_concurrency[id] != null) proposed[d] = advice.plan.case_concurrency[id]; }
      setConcurrency(proposed); setParallel(advice.plan.dataset_concurrency); setEnabled(advice.plan.dataset_order.map(id => datasets.find(d => d.replaceAll("-", "_") === id) || id));
    }}>采纳参数建议</button></section>}
    {staleEstimate && !report && <p role="status">输入已变化，旧估算及建议已失效，请重新估算。</p>}
    {blocker && <div className="planning-blocker">
      <span role="status">{blocker}</span>
      {blocked && !missingInput && <button className="link" type="button" onClick={revealBlocker}>查看阻塞项</button>}
    </div>}
    <div className="planning-execution-note">
      <p>提交将调用模型，可能产生费用；平台不设预算上限。</p>
      <details><summary>执行说明</summary>
        <p>测评按所选数据集和样本范围执行。本次测评及其智能分析不受平台预算金额和范围限制，标准参数校验、资源预检和任务超时仍然生效。</p>
      </details>
    </div>
    <button className="primary" disabled={busy || !ready || !preflight?.result?.execution_ready} onClick={() => void action(async () => {
      const submission = { target_id: target, resource_id: resource, resource_kind: resourceKind, resource_ids: resourceIds, tasks: payload.tasks, dataset_concurrency: parallel, ignore_budget: true };
      const body = JSON.stringify(submission);
      if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() };
      const saved = await apiPost<{ run_id: string }>("/evaluation-tasks", submission, pending.current.key);
      pending.current = null; location.hash = `#run/${saved.run_id}`;
    })}>提交测评</button>
    {message && <p role="alert">{message}</p>}
  </aside></div>;
}
