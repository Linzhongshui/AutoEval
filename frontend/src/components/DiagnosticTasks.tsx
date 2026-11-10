import { useEffect, useRef, useState } from "react";
import { apiGet, apiGetPage, apiPost } from "../services/api";
import { OffsetPagination, REGISTRY_PAGE_SIZE } from "./OffsetPagination";

type Resource = { id: string; binding_key: string; version: number };
type Run = { id: string; state: string };
type Detail = Run & { result: unknown; execution_unresolved: boolean; ownership_held: boolean; cleanup_state: "not_requested" | "pending" | "completed"; events: { seq: number; type: string }[] };
const terminal = new Set(["completed", "failed", "cancelled"]);

export function DiagnosticTasks() {
  const [resources, setResources] = useState<Resource[]>([]);
  const [resource, setResource] = useState("");
  const [resourceOffset, setResourceOffset] = useState(0);
  const [resourceNext, setResourceNext] = useState<number | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ key: string; resource: string } | null>(null);
  const submitting = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    apiGetPage<Resource[]>(`/resources?offset=${resourceOffset}&limit=${REGISTRY_PAGE_SIZE}`, controller.signal).then((page) => {
      setResources(page.data); setResourceNext(page.next_offset); setResource(page.data[0]?.id || "");
    }).catch(() => { if (!controller.signal.aborted) setError("无法加载Docker资源，请检查后端连接。"); });
    return () => controller.abort();
  }, [resourceOffset]);
  useEffect(() => {
    let active = true;
    let refreshing = false;
    const controller = new AbortController();
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const rows = await apiGet<Run[]>("/diagnostics/runs", controller.signal);
        if (active) setRuns(rows);
        if (selected) {
          const value = await apiGet<Detail>(`/diagnostics/runs/${selected}`, controller.signal);
          if (active) setDetail(value);
        }
      } catch { if (active) setError("任务刷新失败，页面保留上次结果；请恢复连接后重试。"); }
      finally { refreshing = false; }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 2000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, [selected]);
  const submit = async () => {
    if (submitting.current || !resource) return;
    submitting.current = true; setBusy(true); setError("");
    if (!pending.current || pending.current.resource !== resource) pending.current = { key: crypto.randomUUID(), resource };
    try {
      const row = await apiPost<{ run_id: string }>("/diagnostics/runs", {
        resource_binding_id: resource, kind: "framework_smoke", duration_seconds: 15,
      }, pending.current.key);
      pending.current = null; setDetail(null); setSelected(row.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败；重试将沿用提交键。"); }
    finally { submitting.current = false; setBusy(false); }
  };
  const cancel = async () => {
    setBusy(true); setError("");
    try { await apiPost(`/diagnostics/runs/${selected}/cancel`); }
    catch { setError("取消请求未确认，请查看任务状态后重试。"); }
    finally { setBusy(false); }
  };
  return <details className="diagnostic-tasks" open>
    <summary>本机 Docker 诊断</summary>
    <p>验证提交、执行与取消链路，每次约15秒。不调用模型，不产生测评成绩，发布门禁不适用。</p>
    <label>诊断执行资源 <select aria-label="诊断执行资源" value={resource} onChange={(e) => setResource(e.target.value)}>
      <option value="">请选择已登记资源</option>
      {resources.map((row) => <option key={row.id} value={row.id}>{row.binding_key} v{row.version}</option>)}
    </select></label>
    <OffsetPagination label="资源" offset={resourceOffset} nextOffset={resourceNext} onChange={setResourceOffset} />
    <button type="button" disabled={busy || !resource} onClick={() => void submit()}>提交Docker诊断</button>
    {error && <p role="alert">{error}</p>}
    <label>已保存诊断任务 <select aria-label="已保存诊断任务" value={selected} onChange={(e) => { setDetail(null); setSelected(e.target.value); }}>
      <option value="">请选择任务</option>
      {selected && !runs.some((row) => row.id === selected) && <option value={selected}>{selected}</option>}
      {runs.map((row) => <option key={row.id} value={row.id}>{row.id} · {row.state}</option>)}
    </select></label>
    {detail && <div>
      <p role="status" data-testid="diagnostic-state">诊断状态：{detail.state}</p>
      <p role="status" data-testid="diagnostic-cleanup-state">清理状态：{detail.cleanup_state}</p>
      {detail.cleanup_state === "pending" && <p role="status">清理尚未确认，资源占用继续保留；对账确认后将自动释放。</p>}
      {detail.execution_unresolved && <p role="alert">执行结果待查证；资源占用已保留，系统对账后再确认终态。请勿重复提交替代任务。</p>}
      <button type="button" disabled={busy || terminal.has(detail.state)} onClick={() => void cancel()}>取消Docker诊断</button>
      <ol>{detail.events.map((event) => <li key={event.seq}>{event.seq}. {event.type}</li>)}</ol>
      {detail.result !== null && <pre>{JSON.stringify(detail.result, null, 2)}</pre>}
    </div>}
  </details>;
}
