import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../services/api";

type Config = { id: string; display_name: string; version_label: string; items: Record<string, { scope: string }>; profile_bindings: Record<string, string> };
type Target = { id: string; remote_model: string; base_url: string };
type Resource = { id: string; binding_key: string; native_tool_root?: string | null };
type Run = { id: string; state: string };
type Detail = Run & { execution_unresolved: boolean; cleanup: { state: string; attempt_count: number; last_error_code: string | null }; report: null | { id: string; validity: string; summary: Record<string, unknown> } };

export function EvaluationRuns() {
  const [configs, setConfigs] = useState<Config[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [sshResources, setSshResources] = useState<Resource[]>([]);
  const [resourceKind, setResourceKind] = useState("docker_local");
  const [config, setConfig] = useState("");
  const [target, setTarget] = useState("");
  const [resource, setResource] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const pending = useRef<{ hash: string; key: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([apiGet<Config[]>("/test-configs?limit=200", controller.signal), apiGet<Target[]>("/target-bindings", controller.signal), apiGet<Resource[]>("/resources", controller.signal), apiGet<Resource[]>("/ssh-resources?limit=200", controller.signal)])
      .then(([c, t, r, s]) => { setConfigs(c.filter((row) => Object.keys(row.items).length === 1 && row.items.GPQA?.scope === "Lite" && row.profile_bindings?.GPQA)); setTargets(t.filter((row) => row.remote_model === "deepseek-flash")); setResources(r); setSshResources(s.filter((row) => row.native_tool_root)); })
      .catch(() => { if (!controller.signal.aborted) setMessage("测评提交选项加载失败。"); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        const list = await apiGet<Run[]>("/runs?limit=100", controller.signal);
        setRuns(list);
        if (selected) setDetail(await apiGet<Detail>(`/runs/${selected}`, controller.signal));
      } catch { if (!controller.signal.aborted) setMessage("任务查询失败；恢复连接后继续刷新。"); }
      finally { refreshing = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [selected]);
  const submit = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setMessage("");
    const payload = { config_version_id: config, target_id: target, resource_id: resource, resource_kind: resourceKind, run_mode: "exploration", max_model_requests: 5 };
    const hash = JSON.stringify(payload);
    if (pending.current?.hash !== hash) pending.current = { hash, key: crypto.randomUUID() };
    try {
      const row = await apiPost<{ run_id: string }>("/runs", payload, pending.current.key);
      pending.current = null; setSelected(row.run_id); setDetail(null); setMessage("已提交；此任务会调用真实模型，按冻结的Lite清单执行。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "提交未确认；重试沿用同一提交键。"); }
    finally { submitting.current = false; setBusy(false); }
  };
  const cancel = async () => {
    setBusy(true);
    try { await apiPost(`/runs/${selected}/cancel`); setMessage("取消意图已保存；等待当前请求返回后停止后续样本，已产生的用量不会撤销。"); }
    catch { setMessage("取消请求未确认，请查询任务状态后重试。"); }
    finally { setBusy(false); }
  };
  const retryCleanup = async () => {
    setBusy(true);
    try { await apiPost(`/runs/${selected}/cleanup`); setMessage("清理意图已保存；后台核验归档后重试，不会重新测评。"); }
    catch { setMessage("清理请求未确认，请刷新状态后重试。"); }
    finally { setBusy(false); }
  };
  return <details className="diagnostic-tasks" open>
    <summary>GPQA Lite探索测评（真实模型调用）</summary>
    <p>使用固定原生AISBench路径，每次最多5个样本、每样本最多64输出tokens，无自动重测。配置须为GPQA单数据集、Lite、并发1、temperature=0、top_p=1；正式发布门禁不适用。</p>
    <label>探索配置 <select aria-label="探索配置" value={config} onChange={(event) => setConfig(event.target.value)}><option value="">请选择已绑定Profile的Lite配置</option>{configs.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}</select></label>
    <label>探索模型服务 <select aria-label="探索模型服务" value={target} onChange={(event) => setTarget(event.target.value)}><option value="">请选择官方DeepSeek目标</option>{targets.map((row) => <option key={row.id} value={row.id}>{row.remote_model} · {row.id.slice(0, 8)}</option>)}</select></label>
    <label>探索资源接入方式<select aria-label="探索资源接入方式" value={resourceKind} onChange={(event) => { setResourceKind(event.target.value); setResource(""); }}><option value="docker_local">本机Docker</option><option value="customer_ssh">客户SSH服务器</option></select></label>
    <label>探索执行资源 <select aria-label="探索执行资源" value={resource} onChange={(event) => setResource(event.target.value)}><option value="">请选择资源</option>{(resourceKind === "customer_ssh" ? sshResources : resources).map((row) => <option key={row.id} value={row.id}>{row.binding_key}</option>)}</select></label>
    <button disabled={busy || !config || !target || !resource} onClick={() => void submit()}>提交真实GPQA Lite测评</button>
    <p role="status">{message}</p>
    <label>已保存探索任务 <select aria-label="已保存探索任务" value={selected} onChange={(event) => { setSelected(event.target.value); setDetail(null); }}><option value="">请选择任务</option>{selected && !runs.some((row) => row.id === selected) && <option value={selected}>{selected}</option>}{runs.map((row) => <option key={row.id} value={row.id}>{row.id} · {row.state}</option>)}</select></label>
    {detail && <div><p data-testid="evaluation-state">测评状态：{detail.state}</p>
      {detail.execution_unresolved && <p role="alert">执行待查证，保留占用及已有attempt；请勿重新提交替代任务。</p>}
      <p>运行ID：{detail.id}（可在下方case历史回溯查询）</p>
      {detail.cleanup.state !== "not_required" && <div><p data-testid="cleanup-state">资源清理：{({ not_scheduled: "尚未安排清理", pending: "等待归档核验与清理", running: "清理中", failed: "清理待恢复（保留占用）", cleaned: "清理已确认" } as Record<string, string>)[detail.cleanup.state] ?? detail.cleanup.state} · 尝试{detail.cleanup.attempt_count}次</p>{["failed", "not_scheduled"].includes(detail.cleanup.state) && detail.report && <button disabled={busy} onClick={() => void retryCleanup()}>重试资源清理</button>}</div>}
      <button disabled={busy || ["completed", "failed", "cancelled"].includes(detail.state)} onClick={() => void cancel()}>取消探索测评</button>
      {detail.report && <div><p data-testid="evaluation-validity">报告完整性：{detail.report.validity}</p><a href={`#report/${detail.report.id}`}>查看完整报告</a><pre data-testid="evaluation-summary" style={{ overflow: "auto" }}>{JSON.stringify(detail.report.summary, null, 2)}</pre></div>}
    </div>}
    <p>配置列表最多200条，任务列表最多100条；完整分页可使用API。</p>
  </details>;
}
