import { useEffect, useRef, useState } from "react";
import { apiGet, apiGetPage, apiPost } from "../services/api";
import { CaseHistory } from "./CaseHistory";
import { OffsetPagination, REGISTRY_PAGE_SIZE } from "./OffsetPagination";

type Config = { id: string; display_name: string; version_label: string; items: Record<string, { scope: string }>; profile_bindings: Record<string, string> };
type Target = { id: string; remote_model: string; base_url: string; model_key: string; model_version: string; default_config_version_id: string | null };
type Resource = { id: string; binding_key: string; native_tool_root?: string | null };
type Run = { id: string; state: string; remote_model?: string; resource_kind?: string; created_at: string };
type Snapshot = { sha256: string; config_version_id: string; config_sha256: string; target_id: string; remote_model: string; resource_kind: string; sample_count: number; parameters: Record<string, unknown>; manifest_id: string; manifest_sha256: string };
type Detail = Run & { snapshot: Snapshot | null; execution_unresolved: boolean; cleanup: { state: string; attempt_count: number; last_error_code: string | null }; report: null | { id: string; validity: string; summary: Record<string, unknown> } };
const terminal = (state: string) => ["completed", "failed", "cancelled"].includes(state);
const eligibleConfig = (row: Config) => Object.keys(row.items).length === 1 && row.items.GPQA?.scope === "Lite" && row.profile_bindings?.GPQA;
const eligibleTarget = (row: Target) => row.remote_model === "deepseek-flash" && row.base_url.replace(/\/$/, "") === "https://api.deepseek.com";
const runLink = (id: string) => `#run/${id}`;
type PendingSubmission = { hash: string; key: string };
const pendingStorageKey = "autoeval.pending-exploration.v1";
function readPending(): PendingSubmission | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingStorageKey) || "null");
    return value && typeof value.hash === "string" && value.hash.length < 4096 && typeof value.key === "string" && /^[0-9a-f-]{36}$/.test(value.key) ? value : null;
  } catch { return null; }
}
function storePending(value: PendingSubmission | null) {
  // Only UUIDs, mode and bounded request limits are in this hash; never credentials.
  try { if (value) sessionStorage.setItem(pendingStorageKey, JSON.stringify(value)); else sessionStorage.removeItem(pendingStorageKey); }
  catch { /* Restricted storage falls back to the in-memory intent. */ }
}

function useOptions<T>(path: string) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<T[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setRows([]); setNext(null);
    apiGetPage<T[]>(`${path}?offset=${offset}&limit=${REGISTRY_PAGE_SIZE}`, controller.signal)
      .then((page) => { if (!controller.signal.aborted) { setRows(page.data); setNext(page.next_offset); } })
      .catch(() => { if (!controller.signal.aborted) setError("选项加载失败，请重试。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, offset, refresh]);
  return { rows, offset, next, loading, error, setOffset, retry: () => setRefresh((value) => value + 1) };
}

export function EvaluationRuns({ runId = "", initialTarget = "" }: { runId?: string; initialTarget?: string }) {
  const configs = useOptions<Config>("/test-configs");
  const targets = useOptions<Target>("/target-bindings");
  const docker = useOptions<Resource>("/resources");
  const ssh = useOptions<Resource>("/ssh-resources");
  const [resourceKind, setResourceKind] = useState("docker_local");
  const resources = resourceKind === "customer_ssh" ? ssh : docker;
  const [config, setConfig] = useState<Config | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [resource, setResource] = useState<Resource | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [listError, setListError] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingDefault, setLoadingDefault] = useState(false);
  const [defaultError, setDefaultError] = useState("");
  const [defaultRefresh, setDefaultRefresh] = useState(0);
  const submitting = useRef(false);
  const [initialPending] = useState(readPending);
  const pending = useRef<PendingSubmission | null>(initialPending);

  useEffect(() => {
    if (!initialTarget) return;
    const controller = new AbortController();
    setTarget(null); setConfig(null); setMessage("正在加载已保存服务…");
    apiGet<Target[]>(`/target-bindings?target_id=${encodeURIComponent(initialTarget)}`, controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        if (!rows[0] || !eligibleTarget(rows[0])) { setMessage("服务不存在或不适用于当前GPQA探索路径。"); return; }
        setTarget(rows[0]); setMessage("已加载保存的服务，请确认配置和资源后提交。");
      }).catch(() => { if (!controller.signal.aborted) setMessage("服务读取失败，请返回服务配置重试。"); });
    return () => controller.abort();
  }, [initialTarget]);

  // Resolve the default by immutable version ID, even outside the current page.
  useEffect(() => {
    const controller = new AbortController();
    setConfig(null); setDefaultError(""); setLoadingDefault(false);
    if (!target) return () => controller.abort();
    setLoadingDefault(true);
    apiGet<Target[]>(`/target-bindings?target_id=${target.id}`, controller.signal)
      .then((rows) => {
        if (!rows[0]?.default_config_version_id) { throw new Error("该模型尚未绑定默认配置，可显式选择探索配置。"); }
        return apiGet<Config[]>(`/test-configs?config_id=${rows[0].default_config_version_id}`, controller.signal);
      })
      .then((rows) => {
        if (controller.signal.aborted) return;
        if (!rows[0] || !eligibleConfig(rows[0])) { setDefaultError("模型默认配置不适用于当前GPQA Lite探索，请显式选择其他配置。"); return; }
        setConfig(rows[0]);
      }).catch((error) => { if (!controller.signal.aborted) setDefaultError(error instanceof Error && error.message.startsWith("该模型") ? error.message : "默认配置读取失败，可重试或显式选择配置。"); })
      .finally(() => { if (!controller.signal.aborted) setLoadingDefault(false); });
    return () => controller.abort();
  }, [target, defaultRefresh]);

  useEffect(() => {
    const controller = new AbortController();
    let refreshing = false;
    setRuns([]); setNext(null);
    const refresh = async () => {
      if (refreshing || document.hidden) return;
      refreshing = true;
      try {
        const page = await apiGetPage<Run[]>(`/runs?offset=${offset}&limit=${REGISTRY_PAGE_SIZE}`, controller.signal);
        if (!controller.signal.aborted) { setRuns(page.data); setNext(page.next_offset); setListError(""); }
      } catch { if (!controller.signal.aborted) setListError("任务列表查询失败，恢复连接后自动重试。"); }
      finally { refreshing = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [offset, runId]);

  useEffect(() => {
    const controller = new AbortController();
    let refreshing = false;
    setDetail(null); setDetailError("");
    if (!runId) return () => controller.abort();
    const refresh = async () => {
      if (refreshing || document.hidden) return;
      refreshing = true;
      try {
        const row = await apiGet<Detail>(`/runs/${encodeURIComponent(runId)}`, controller.signal);
        if (!controller.signal.aborted) { setDetail(row); setDetailError(""); }
      } catch { if (!controller.signal.aborted) setDetailError("任务不存在或查询失败；已显示的状态可能过期，请勿据此重新提交。"); }
      finally { refreshing = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [runId]);

  const submit = async () => {
    if (submitting.current || !config || !target || !resource) return;
    submitting.current = true; setBusy(true); setMessage("");
    const payload = { config_version_id: config.id, target_id: target.id, resource_id: resource.id, resource_kind: resourceKind, run_mode: "exploration", max_model_requests: 5 };
    const hash = JSON.stringify(payload);
    if (pending.current?.hash !== hash) pending.current = { hash, key: crypto.randomUUID() };
    storePending(pending.current);
    try {
      const row = await apiPost<{ run_id: string }>("/runs", payload, pending.current.key);
      pending.current = null; storePending(null); location.hash = runLink(row.run_id); setMessage("已提交；按冻结的Lite清单执行。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "提交未确认；重试沿用同一提交键。"); }
    finally { submitting.current = false; setBusy(false); }
  };
  const action = async (kind: "cancel" | "cleanup") => {
    setBusy(true);
    try { await apiPost(`/runs/${runId}/${kind}`); setMessage(kind === "cleanup" ? "清理意图已保存；后台核验归档后重试，不会重新测评。" : "取消意图已保存；等待当前请求返回后停止后续样本，已产生的用量不会撤销。"); }
    catch { setMessage("操作未确认，请查询任务状态后重试。"); }
    finally { setBusy(false); }
  };
  const options = <T extends { id: string }>(rows: T[], selected: T | null) => selected && !rows.some((row) => row.id === selected.id) ? [selected, ...rows] : rows;
  const configRows = options(configs.rows.filter(eligibleConfig), config);
  const targetRows = options(targets.rows.filter(eligibleTarget), target);
  const resourceRows = options(resources.rows.filter((row) => resourceKind !== "customer_ssh" || row.native_tool_root), resource);

  return <section className="diagnostic-tasks">
    <h2>GPQA Lite探索测评（真实模型调用）</h2>
    <p>使用固定原生AISBench路径，每次最多5个样本、每样本最多64输出tokens，无自动重测。配置须为GPQA单数据集、Lite、并发1、temperature=0、top_p=1；正式发布门禁不适用。</p>
    <details open={!runId}><summary>新建探索测评</summary>
      <p><a href="#console">登记模型、服务与资源</a> · <a href="#config">维护配置、清单与Profile</a></p>
      <label>探索模型服务 <select aria-label="探索模型服务" value={target?.id || ""} disabled={busy || targets.loading} onChange={(event) => setTarget(targetRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择官方DeepSeek目标</option>{targetRows.map((row) => <option key={row.id} value={row.id}>{row.model_key} / {row.model_version} · {row.remote_model} · {row.id.slice(0, 8)}</option>)}</select></label>
      <OffsetPagination label="探索服务" offset={targets.offset} nextOffset={targets.next} onChange={targets.setOffset} disabled={targets.loading || busy} />
      <label>探索配置 <select aria-label="探索配置" value={config?.id || ""} disabled={busy || loadingDefault} onChange={(event) => { setConfig(configRows.find((row) => row.id === event.target.value) || null); setDefaultError(""); }}><option value="">请选择已绑定Profile的Lite配置</option>{configRows.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}</select></label>
      {loadingDefault && <p role="status">正在读取模型默认配置…</p>}{defaultError && <p role="status">{defaultError}</p>}
      <button disabled={busy || !target || loadingDefault} onClick={() => setDefaultRefresh((value) => value + 1)}>重新加载模型默认配置</button>
      <OffsetPagination label="探索配置" offset={configs.offset} nextOffset={configs.next} onChange={configs.setOffset} disabled={configs.loading || busy} />
      <label>探索资源接入方式<select aria-label="探索资源接入方式" value={resourceKind} disabled={busy} onChange={(event) => { setResourceKind(event.target.value); setResource(null); }}><option value="docker_local">本机Docker</option><option value="customer_ssh">客户SSH服务器</option></select></label>
      <label>探索执行资源 <select aria-label="探索执行资源" value={resource?.id || ""} disabled={busy || resources.loading} onChange={(event) => setResource(resourceRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择资源</option>{resourceRows.map((row) => <option key={row.id} value={row.id}>{row.binding_key}</option>)}</select></label>
      <OffsetPagination label="探索资源" offset={resources.offset} nextOffset={resources.next} onChange={resources.setOffset} disabled={resources.loading || busy} />
      {[configs, targets, resources].some((source) => source.error) && <p role="alert">选项加载失败。<button onClick={() => { configs.retry(); targets.retry(); resources.retry(); }}>重试选项加载</button></p>}
      <p>每页20条；当前页可能没有符合探索条件的选项，可继续翻页。翻页保留已选项，提交时后台再次校验。</p>
      <button disabled={busy || loadingDefault || !config || !target || !resource} onClick={() => void submit()}>提交真实GPQA Lite测评</button>
    </details>
    <p role="status">{message}</p>{listError && <p role="alert">{listError}</p>}
    <label>已保存探索任务 <select aria-label="已保存探索任务" value={runId} onChange={(event) => { location.hash = event.target.value ? runLink(event.target.value) : "#tasks"; }}><option value="">请选择任务</option>{runId && !runs.some((row) => row.id === runId) && <option value={runId}>{runId}</option>}{runs.map((row) => <option key={row.id} value={row.id}>{row.id} · {row.state}</option>)}</select></label>
    <div style={{ overflowX: "auto" }}><table><thead><tr><th>任务</th><th>模型</th><th>资源</th><th>状态</th><th>创建时间</th></tr></thead><tbody>{runs.map((row) => <tr key={row.id}><td><a href={runLink(row.id)}>{row.id}</a></td><td>{row.remote_model}</td><td>{row.resource_kind === "customer_ssh" ? "客户SSH服务器" : "本机Docker"}</td><td>{row.state}</td><td>{row.created_at}</td></tr>)}</tbody></table></div>
    <OffsetPagination label="探索任务" offset={offset} nextOffset={next} onChange={setOffset} disabled={busy} />
    {detailError && <p role="alert">{detailError}</p>}
    {detail && <article data-testid="evaluation-detail"><p data-testid="evaluation-state">测评状态：{detail.state}</p>
      {detail.execution_unresolved && <p role="alert">执行待查证，保留占用及已有attempt；请勿重新提交替代任务。</p>}
      <p>运行ID：{detail.id} · <a href={runLink(detail.id)}>任务永久链接</a></p>
      {detail.snapshot && <details data-testid="run-snapshot"><summary>本次冻结配置与证据标识</summary><p>模型：{detail.snapshot.remote_model}；样本：{detail.snapshot.sample_count}；配置版本：{detail.snapshot.config_version_id}</p><p>该快照不会随默认配置或配置新版本改变。</p><pre style={{ overflow: "auto" }}>{JSON.stringify(detail.snapshot, null, 2)}</pre></details>}
      {detail.cleanup.state !== "not_required" && <div><p data-testid="cleanup-state">资源清理：{({ not_scheduled: "尚未安排清理", pending: "等待归档核验与清理", running: "清理中", failed: "清理待恢复（保留占用）", cleaned: "清理已确认" } as Record<string, string>)[detail.cleanup.state] ?? detail.cleanup.state} · 尝试{detail.cleanup.attempt_count}次</p>{["failed", "not_scheduled"].includes(detail.cleanup.state) && detail.report && <button disabled={busy} onClick={() => void action("cleanup")}>重试资源清理</button>}</div>}
      <button disabled={busy || terminal(detail.state)} onClick={() => void action("cancel")}>取消探索测评</button>
      {detail.report && <div><p data-testid="evaluation-validity">报告完整性：{detail.report.validity}</p><a href={`#report/${detail.report.id}`}>查看完整报告</a><pre data-testid="evaluation-summary" style={{ overflow: "auto" }}>{JSON.stringify(detail.report.summary, null, 2)}</pre></div>}
      <CaseHistory key={detail.id} initialRun={detail.id} />
    </article>}
  </section>;
}
