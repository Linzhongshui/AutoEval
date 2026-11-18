import { PlanningSelect } from "./PlanningSelect";
import { ServiceBindings } from "../resources/ServiceBindings";
import { ResourceMultiSelect } from "./ResourceMultiSelect";
import { ModelServices } from "../resources/ModelServices";
import { ProbeProgress } from "../evaluation/ProbeProgress";
import { useEffect, useRef, useState } from "react";
import { apiGet, apiGetPage, apiPost } from "../../shared/api";
import type { Resource, Target } from "../evaluation/types";
import { useOptions } from "../evaluation/hooks";
import { usePolling } from "../../shared/hooks/usePolling";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { StandardInputs } from "../catalog/StandardInputs";
import { ExecutionBindings } from "../catalog/ExecutionBindings";
import { DatasetManifests } from "../catalog/DatasetManifests";

type Report = {
  input_sha256: string; conditional: boolean; confidence: string; warnings: string[];
  representative_duration_sec: number;
  estimate: { total_duration_sec: number; range: { p10_sec: number; p90_sec: number } };
  plan: { dataset_order: string[]; dataset_concurrency: number; case_concurrency: Record<string, number> };
  planner_revision?: string; throughput_source?: { measured_at?: string; type?: string };
  tasks: { task_id: string; standalone_duration_sec: number; scheduled_duration_sec: number; scheduled_start_sec: number; scheduled_end_sec: number }[];
};
type Options = {
  compilations: { adaptor_revision?: string; runtime_config?: Record<string, unknown>; id: string; label?: string; sha256: string; target_id: string; dataset: string; input_ready: boolean; config: { subcommand: string; params: Record<string, unknown> } }[];
  manifests: { id: string; dataset: string; scope: string; sample_count: number; sha256?: string }[];
  curves: { id: string; target_id: string; resource_id: string; resource_kind: string; measured_at: string }[];
};
type DatasetCheck = { task_id: string; dataset: string; data_path: string | null; tool_revision: string | null; expected_tool_revision: string; blocking_reasons: string[] };
type Job = { id: string; state: string; created_at?: string; updated_at?: string; result?: { progress?: { stage: string; current_concurrency?: number | null; completed_levels: number; total_levels: number; observed_at?: string } | null; report?: Report; throughput_profile_id?: string; reason?: string; dispatch_blocked?: boolean; remote_check?: { state: string; checked_at: string }; execution_ready?: boolean; supported_datasets?: string[]; blocking_reasons?: string[]; dataset_checks?: DatasetCheck[]; tool_versions?: Record<string, { expected: string; actual: string | null }> } };
const datasets = ["GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"];
const duration = (seconds: number | null | undefined) => {
  if (seconds == null) return "未知";
  const total = Math.max(0, Math.round(seconds));
  return [total >= 3600 ? `${Math.floor(total / 3600)}小时` : "", total >= 60 ? `${Math.floor(total % 3600 / 60)}分` : "", `${total % 60}秒`].filter(Boolean).join(" ");
};

function EstimateElapsed() {
  const [start] = useState(Date.now);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  return <span className="estimate-elapsed" aria-label="估算已耗时">已耗时 {duration((now - start) / 1000)}</span>;
}

export function PlanEstimate({ report }: { report: Report }) {
  const confidence = ({ high: "高", medium: "中", low: "低" } as Record<string, string>)[report.confidence] || report.confidence;
  return <section className="estimate-detail" aria-label="耗时估算与参数建议">
    <div className="estimate-result"><small>预计总耗时</small><strong>{duration(report.estimate.total_duration_sec)}</strong><span>预测区间（P10–P90）<br />{duration(report.estimate.range.p10_sec)} – {duration(report.estimate.range.p90_sec)}</span><span>置信度：{confidence}</span></div>
    <p className="estimate-note">不含平台排队及报告分析耗时。{report.conditional && "当前为条件估算，需执行资源预检后重新估算。"}</p>
    <div className="estimate-datasets">{report.tasks.map(t => <article className="estimate-dataset" key={t.task_id}><header><strong>{t.task_id}</strong><span>样本并发 {report.plan.case_concurrency[t.task_id]}</span></header><dl><div><dt>单独执行</dt><dd>{duration(t.standalone_duration_sec)}</dd></div><div><dt>计划内耗时</dt><dd>{duration(t.scheduled_duration_sec)}</dd></div><div><dt>开始 → 结束</dt><dd>{duration(t.scheduled_start_sec)} → {duration(t.scheduled_end_sec)}</dd></div></dl></article>)}</div>
    <p className="estimate-note">执行顺序：{report.plan.dataset_order.join(" → ")} · 同时运行 {report.plan.dataset_concurrency} 个数据集。并行共享吞吐与资源，各项时长不能直接相加。</p>
    <details className="estimate-source"><summary>估算来源与限制</summary><dl><div><dt>组件版本</dt><dd>{report.planner_revision || "未记录"}</dd></div><div><dt>吞吐依据</dt><dd>{report.throughput_source?.type === "probe" ? "真实吞吐探测" : report.throughput_source?.type || "未记录"}</dd></div><div><dt>采集时间</dt><dd>{report.throughput_source?.measured_at ? new Date(report.throughput_source.measured_at).toLocaleString("zh-CN") : "未记录"}</dd></div></dl><p>代表性仿真终点：{duration(report.representative_duration_sec)}</p></details>
    {report.warnings?.map((w, i) => <small className="estimate-note" key={i}>{w}</small>)}
  </section>;
}

function StrategyChoice({ label, parallel, disabled = false, onChange }: { label: string; parallel: boolean; disabled?: boolean; onChange: (parallel: boolean) => void }) {
  return <div className="strategy-choices" role="group" aria-label={label}>
    <button type="button" aria-pressed={!parallel} onClick={() => onChange(false)}>串行执行</button>
    <button type="button" aria-pressed={parallel} disabled={disabled} onClick={() => onChange(true)}>并行执行</button>
  </div>;
}

export function TaskPlanning() {
  const targets = useOptions<Target>("/target-bindings");
  const docker = useOptions<Resource>("/resources");
  const ssh = useOptions<Resource>("/ssh-resources");
  const [target, setTarget] = useState("");
  const [addingService, setAddingService] = useState(false);
  const [resourceKind, setResourceKind] = useState("customer_ssh");
  const [resource, setResource] = useState("");
  const [resourceIds, setResourceIds] = useState<string[]>([]);
  const [options, setOptions] = useState<Options>({ compilations: [], manifests: [], curves: [] });
  const [selection, setSelection] = useState<Record<string, { compilation: string; manifest: string }>>({});
  const [enabled, setEnabled] = useState<string[]>([]);
  const [curve, setCurve] = useState("");
  const [parallel, setParallel] = useState(1);
  const [job, setJob] = useState<Job | null>(null);
  const [adviceJob, setAdviceJob] = useState<Job | null>(null);
  const [probeLookup, setProbeLookup] = useState(false);
  const [probeLookupFailed, setProbeLookupFailed] = useState(false);
  const [probe, setProbe] = useState<Job | null>(null);
  const [preflight, setPreflight] = useState<Job | null>(null);
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
  const resources = resourceKind === "customer_ssh" ? ssh : docker;
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
  const payload = { target_id: target, resource_id: resource, resource_kind: resourceKind,
    resource_ids: resourceIds,
    throughput_profile_id: curve || null, dataset_concurrency: parallel, recommend: false,
    tasks: enabled.filter(d => datasets.includes(d) && selection[d]?.compilation && selection[d]?.manifest).map(d => ({
      task_id: d.replaceAll("-", "_"), dataset: d, concurrency: concurrency[d] ?? null, compilation_id: selection[d].compilation, manifest_id: selection[d].manifest,
    })) };
  const fingerprint = JSON.stringify(payload);
  useEffect(() => { setParallel(v => Math.min(v, Math.max(1, enabled.length))); }, [enabled.length]);
  const preflightFingerprint = JSON.stringify({ target_id: target, resource_id: resource, resource_kind: resourceKind, resource_ids: resourceIds, tasks: payload.tasks });
  useEffect(() => {
    generation.current++; if (job) setStaleEstimate(true); setJob(null); setAdviceJob(null);
  }, [fingerprint]);
  useEffect(() => { setPreflight(null); }, [preflightFingerprint]);
  useEffect(() => { setPreflight(null); setProbeReview(false); setCurve(""); }, [target, resource, resourceKind]);
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
          if (row.id === job?.id) setJob(row);
          if (row.id === adviceJob?.id) setAdviceJob(row);
          if (row.id === preflight?.id) setPreflight(row);
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
  const probeBlocked = !!probe && ["pending", "running", "unresolved"].includes(probe.state);
  const checking = !!preflight && ["pending", "running"].includes(preflight.state);
  const preflightLabel = !preflight ? "未检查" : ({ pending: "排队中", running: "检查中", completed: preflight.result?.execution_ready ? "检查通过" : "存在阻塞", failed: "检查失败", cancelled: "已取消" } as Record<string, string>)[preflight.state] || "状态待确认";
  const preflightTone = checking ? "checking" : preflight?.result?.execution_ready ? "passed" : "blocked";
  const autoFillDataset = (dataset: string, active: boolean) => {
    setEnabled(rows => active ? [...new Set([...rows, dataset])] : rows.filter(row => row !== dataset));
    if (!active) { setSelection(rows => ({ ...rows, [dataset]: { compilation: "", manifest: "" } })); return; }
    const candidates = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset && (!Array.isArray(c.runtime_config?.resource_ids) || (c.runtime_config.resource_ids as string[]).some(id => resources.rows.some(r => r.id === id))));
    const chosen = candidates.length === 1 ? candidates[0] : undefined;
    const full = options.manifests.filter(m => m.dataset === dataset && m.scope === "full");
    setSelection(rows => ({ ...rows, [dataset]: { compilation: chosen?.id || "", manifest: full.length === 1 ? full[0].id : "" } }));
    const bound = chosen?.runtime_config?.resource_ids;
    if (Array.isArray(bound)) {
      const matching = bound.filter((id): id is string => typeof id === "string" && resources.rows.some(r => r.id === id));
      if (matching.length) { setResourceIds(ids => [...new Set([...ids, ...matching])]); if (!resource) setResource(matching[0]); }
    }
  };
  useEffect(() => {
    if (!target || !enabled.length) return;
    let changed = false;
    const next = { ...selection };
    const boundIds = new Set(resourceIds);
    for (const dataset of enabled) {
      const candidates = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset && (!Array.isArray(c.runtime_config?.resource_ids) || (c.runtime_config.resource_ids as string[]).some(id => resources.rows.some(r => r.id === id))));
      const current = candidates.find(c => c.id === selection[dataset]?.compilation);
      const chosen = current || (candidates.length === 1 ? candidates[0] : undefined);
      if (!chosen) continue;
      const allowed = chosen.runtime_config?.manifest_ids;
      const manifests = options.manifests.filter(m => m.dataset === dataset && (!Array.isArray(allowed) || allowed.includes(m.id)));
      const full = manifests.filter(m => m.scope === "full");
      const manifest = manifests.some(m => m.id === selection[dataset]?.manifest) ? selection[dataset].manifest : full.length === 1 ? full[0].id : "";
      if (selection[dataset]?.compilation !== chosen.id || selection[dataset]?.manifest !== manifest) { next[dataset] = { compilation: chosen.id, manifest }; changed = true; }
      const ids = chosen.runtime_config?.resource_ids;
      if (Array.isArray(ids)) for (const id of ids) if (typeof id === "string" && resources.rows.some(r => r.id === id)) boundIds.add(id);
    }
    if (changed) setSelection(next);
    const ids = [...boundIds];
    if (ids.length !== resourceIds.length) setResourceIds(ids);
    if (!resource && ids.length) setResource(ids[0]);
  }, [target, enabled, options, resources.rows, selection, resourceIds, resource]);
  const blocker = !target ? "请选择模型服务" : !resource ? "请选择执行资源" : !enabled.length ? "请启用至少一个数据集" : incomplete ? "请补全已启用数据集的配置与样本范围" : checking ? "正在检查执行环境，请稍候…" : !preflight?.result?.execution_ready ? "请完成环境检查并处理阻塞项" : "配置已就绪，可以提交测评";
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
    if (!ready) return;
    let stopped = false;
    const timer = setTimeout(() => { void apiPost<Job>("/planning/resources/preflight", payload)
      .then(result => { if (!stopped) setPreflight(result); })
      .catch(() => { if (!stopped) setMessage("自动环境检查失败，请点击环境检查重试。"); }); }, 350);
    return () => { stopped = true; clearTimeout(timer); };
  // Resource checks follow execution selection, independently of optional estimation inputs.
  }, [preflightFingerprint, ready]);
  return <div className="planning-layout"><section className="card stack planning-card" aria-label="发起测评">
    <h2>1. 模型与执行资源</h2>
    <p className="planning-intro">支持 GPQA、MMMU-Pro、DeepSWE、AutomationBench 的全量或已绑定 Lite 清单。Agent 工作流通过 AISBench Harbor 执行，需绑定配置与清单并通过环境检查。</p>
    <div className="planning-fields">
      <div className="planning-service-field"><div className="planning-service-heading"><label htmlFor="planning-service">模型服务</label><ManagementDrawer title="管理服务" onDismiss={targets.retry}><ModelServices /></ManagementDrawer></div><PlanningSelect id="planning-service" label="规划模型服务" value={target} options={targets.rows.map(t => ({ id: t.id, label: t.service_name || t.remote_model, detail: `${t.remote_model} · ${t.base_url} · ${t.id.slice(0, 8)}` }))} onChange={id => { setTarget(id); setSelection({}); }} onAdd={() => setAddingService(true)} /><ManagementDrawer title="新增模型服务" hideTrigger open={addingService} onOpenChange={setAddingService} onDismiss={targets.retry}><ServiceBindings /></ManagementDrawer></div>
      <div className="planning-environment-field"><span>执行环境</span><PlanningSelect label="执行环境" value={resourceKind} options={[{ id: "docker_local", label: "Docker" }, { id: "customer_ssh", label: "客户 SSH" }]} onChange={id => { setResourceKind(id); setResource(""); setResourceIds([]); }} /></div>
      <ResourceMultiSelect options={resources.rows} value={resourceIds} onChange={ids => { setResourceIds(ids); setResource(ids[0] || ""); }} />
    </div>
    <p className="muted">展开下拉框勾选多个执行资源；平台按配置绑定自动分配，每个数据集分别预检。</p>
    {(targets.error || resources.error) && <p role="alert">{targets.error || resources.error}</p>}
    <div className="planning-actions">
      <button disabled={busy || !ready || checking} onClick={() => void action(async () => { const revision = generation.current; const result = await apiPost<Job>("/planning/resources/preflight", payload); if (revision === generation.current) setPreflight(result); })}>{checking ? "正在检查…" : preflight ? "重新检查" : "环境检查"}</button>
      <p className="muted">仅检查环境，不发起测评。</p>
      {preflight && <div className="preflight-feedback" role="status" aria-live="polite"><span className={`preflight-status ${preflightTone}`}><i aria-hidden="true" />{preflightLabel}</span><span className="preflight-hint">{checking ? "正在核对工具版本、数据路径与执行环境" : preflight.result?.execution_ready ? `可执行：${preflight.result.supported_datasets?.join("、") || "所选数据集"}` : preflight.state === "completed" ? "请查看下方检查明细，处理阻塞后重新检查" : "请检查连接及后台任务状态后重试"}</span></div>}
    </div>
    {preflight?.state === "completed" && preflight.result && <div className="notice">
      <p>Planner：{preflight.result.tool_versions?.planner.actual?.slice(0, 12) || "未安装或版本未知"}；Adaptor：{preflight.result.tool_versions?.adaptor.actual?.slice(0, 12) || "未安装或版本未知"}</p>
      {!!preflight.result.blocking_reasons?.length && <p>阻塞原因：{preflight.result.blocking_reasons.join("、")}</p>}
      {preflight.result.dataset_checks?.map(check => <p key={check.task_id}>{check.dataset} · 数据路径：{check.data_path || "未配置"} · 工具版本：{check.tool_revision?.slice(0, 12) || "校验未通过"}{check.blocking_reasons.length ? ` · ${check.blocking_reasons.join("、")}` : " · 就绪"}</p>)}
    </div>}
    <h2>2. 数据集与样本范围</h2>
    <p className="muted">勾选后自动填充唯一匹配的执行配置、全量清单及绑定资源；存在多个候选或缺少全量清单时，请手动确认。不会自动启动环境检查或测评。</p><div className="table-wrap"><table className="planning-table"><thead><tr><th>启用</th><th>数据集</th><th>执行配置</th><th>样本范围</th><th>状态</th></tr></thead><tbody>{datasets.map(d => {
      const active = enabled.includes(d);
      const chosenConfig = options.compilations.find(c => c.id === selection[d]?.compilation);
      const allowed = chosenConfig?.runtime_config?.resource_ids;
      const assignedId = resourceIds.find(id => !Array.isArray(allowed) || allowed.includes(id));
      const assignedName = resources.rows.find(r => r.id === assignedId)?.binding_key;
      const configs = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === d && (!Array.isArray(c.runtime_config?.resource_ids) || resources.rows.some(r => (c.runtime_config!.resource_ids as string[]).includes(r.id))));
      return <tr key={d}><td><input type="checkbox" aria-label={`启用 ${d}`} checked={active} onChange={e => { autoFillDataset(d, e.target.checked); }} /></td><td>{d}</td><td data-label="执行配置"><select disabled={!active || !target} aria-label={`${d} 执行配置`} value={selection[d]?.compilation || ""} onChange={e => setSelection(rows => ({ ...rows, [d]: { ...rows[d], compilation: e.target.value } }))}><option value="">{!target ? "先选择模型服务" : !configs.length ? "暂无可用配置" : "请选择执行配置"}</option>{configs.map(c => <option key={c.id} value={c.id}>{c.label?.split(" / ").pop() || c.sha256.slice(0, 12)}</option>)}</select>{active && chosenConfig && assignedName && <small className="muted">自动分配：{assignedName}</small>}</td><td data-label="样本范围"><select disabled={!active || !selection[d]?.compilation} aria-label={`${d} 样本范围`} value={selection[d]?.manifest || ""} onChange={e => setSelection(rows => ({ ...rows, [d]: { ...rows[d], manifest: e.target.value } }))}><option value="">请选择已绑定清单</option>{options.manifests.filter(m => m.dataset === d).map(m => <option key={m.id} value={m.id}>{m.scope === "full" ? "全量" : "Lite"} · {m.sample_count} 个样本 · {m.id.slice(0, 8)}</option>)}</select></td><td><span className="planning-row-state">{!active ? "未启用" : !configs.length ? "需配置" : selection[d]?.compilation && selection[d]?.manifest ? "已配置" : "待补全"}</span></td></tr>;
    })}</tbody></table></div>
    {enabled.map(dataset => {
      const bound = options.compilations.filter(c => c.target_id === target && c.input_ready && c.dataset === dataset);
      if (!bound.length || bound.some(c => !Array.isArray(c.runtime_config?.resource_ids) || resourceIds.some(id => (c.runtime_config!.resource_ids as string[]).includes(id)))) return null;
      const names = [...new Set(bound.flatMap(c => (c.runtime_config?.resource_ids as string[]).map(id => [...ssh.rows, ...docker.rows].find(r => r.id === id)?.binding_key || id)))];
      return <p className="notice" key={dataset}>{dataset} 配置需使用执行资源：{names.join("、")}。请切换资源后选择配置。</p>;
    })}
    <details className="planning-management"><summary>管理配置与清单 · 缺少配置时在此维护</summary>
    <div className="inline"><ManagementDrawer title="配置标准输入"><StandardInputs /></ManagementDrawer><ManagementDrawer title="管理样本清单"><DatasetManifests /></ManagementDrawer><ManagementDrawer title="登记执行规则"><ExecutionBindings /></ManagementDrawer><button onClick={() => void action(refresh)}>刷新配置与清单</button></div>
    </details>
    <p className="muted">执行配置来自标准输入编译；并发仅为默认值，请在下方执行策略中自定义调整。样本清单须绑定已登记的工具与评分规则。</p>
    {incomplete && <p role="alert">请为每个已选执行配置选择样本范围。</p>}
    <h2>3. 执行策略</h2>
    <div className="execution-strategy">
      <section className="strategy-card strategy-datasets" aria-label="数据集执行设置">
        <div className="strategy-card-heading"><h3>数据集之间</h3><span>{enabled.length} 个数据集</span></div>
        <div className="strategy-controls">
          <div><span className="strategy-field-label">执行方式</span><StrategyChoice label="数据集执行策略" parallel={parallel > 1} disabled={enabled.length < 2} onChange={value => setParallel(value ? Math.max(2, Math.min(enabled.length, 3)) : 1)} /></div>
          <label>同时运行的数据集数<input aria-label="数据集同时运行数" type="number" min={1} max={Math.max(1, enabled.length)} value={parallel} disabled={parallel <= 1} onChange={e => setParallel(Math.max(1, Math.min(enabled.length || 1, Number(e.target.value))))} /></label>
        </div>
        <p className="strategy-help">{enabled.length < 2 ? "当前仅一个数据集，无需数据集并行；样本仍可单独选择并行。" : parallel > 1 ? "多个数据集共享执行资源，同时运行数量仍需通过资源预检。" : "按下方顺序逐个执行，前一个结束后开始下一个。"}</p>
        <div className="strategy-order"><span className="strategy-field-label">执行顺序</span>{enabled.length ? <ol>{enabled.map((d, i) => <li key={d}><span><small>{i + 1}</small>{d}</span>{enabled.length > 1 && <button type="button" className="link" disabled={i === 0} aria-label={`${d} 前移`} onClick={() => setEnabled(v => { const next = [...v]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next; })}>前移</button>}</li>)}</ol> : <p className="muted">请先选择数据集</p>}</div>
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
      <div><dt>执行资源</dt><dd>{resources.rows.filter(r => resourceIds.includes(r.id)).map(r => r.binding_key).join("、") || "待选择"}</dd></div>
      <div><dt>测评范围</dt><dd>{enabled.length} 个数据集 · {sampleCount} 个样本</dd></div>
      <div><dt>环境检查</dt><dd><span className={`preflight-status ${preflight ? preflightTone : "idle"}`}>{preflightLabel}</span></dd></div>
    </dl>
    <div className="planning-duration" role="status"><span>预计总耗时</span><div className="estimate-status-line"><strong>{estimating || (job && ["pending", "running"].includes(job.state)) ? "正在估算…" : report ? duration(report.estimate.total_duration_sec) : "暂无可靠估算"}</strong>{(estimating || (job && ["pending", "running"].includes(job.state))) && <EstimateElapsed />}</div><small>{report ? "不含排队及报告分析耗时" : !curve ? "未提供吞吐曲线；可直接按当前配置发起测评" : "吞吐曲线就绪后自动估算当前参数；可手动获取优化建议"}</small></div>
    {job?.state === "failed" && <p role="alert">当前参数估算失败：{job.result?.reason || "请重试"}</p>}
    <div className="estimate-actions"><button disabled={busy || estimating || !ready || !curve || (job != null && ["pending", "running"].includes(job.state))} onClick={() => void action(async () => { const revision = generation.current; setEstimating(true); setJob(null); try { const next = await apiPost<Job>("/planning/plans", { ...payload, recommend: false }); if (revision === generation.current) { setStaleEstimate(false); setJob(next); } } finally { setEstimating(false); } })}>重新估算</button>
    <button disabled={busy || !ready || !curve || (adviceJob != null && ["pending", "running"].includes(adviceJob.state))} onClick={() => void action(async () => { const revision = generation.current; const next = await apiPost<Job>("/planning/plans", { ...payload, recommend: true }); if (revision === generation.current) setAdviceJob(next); })}>获取优化建议</button></div>
    {report && <details className="estimate-disclosure"><summary>查看当前参数耗时依据</summary><PlanEstimate report={report} /></details>}
    {adviceJob && <p role="status">优化建议：{adviceJob.state} {adviceJob.result?.reason}</p>}
    {advice && <section className="stack"><h3>优化建议（尚未采纳）</h3><details className="estimate-disclosure"><summary>查看优化建议与参数差异</summary><PlanEstimate report={advice} /><p>同时运行数据集 {parallel} → {advice.plan.dataset_concurrency}</p>{advice.tasks.map(t => <p key={t.task_id}>{t.task_id}：case 并发 {currentConcurrency(datasets.find(d => d.replaceAll("-", "_") === t.task_id) || t.task_id)} → {advice.plan.case_concurrency[t.task_id]}</p>)}</details><button disabled={busy || advice.conditional} onClick={() => {
      const proposed: Record<string, number> = {};
      for (const d of datasets) { const id = d.replaceAll("-", "_"); if (advice.plan.case_concurrency[id] != null) proposed[d] = advice.plan.case_concurrency[id]; }
      setConcurrency(proposed); setParallel(advice.plan.dataset_concurrency); setEnabled(advice.plan.dataset_order.map(id => datasets.find(d => d.replaceAll("-", "_") === id) || id));
    }}>采纳参数建议</button></section>}
    {staleEstimate && !report && <p role="status">输入已变化，旧估算及建议已失效，请重新估算。</p>}
    <p className="planning-blocker" role="status">{blocker}</p>
    <p className="notice">提交将按所选数据集及范围执行真实测评，可能产生模型调用费用。本次测评及其智能分析不受平台预算金额和范围限制；标准参数校验、资源预检和任务超时仍然生效。</p>
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
