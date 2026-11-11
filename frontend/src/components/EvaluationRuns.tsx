import { ListPagination } from "./ListPagination";
import { useEffect, useState } from "react";
import { CheckCircle2, CircleAlert, Layers, Play } from "lucide-react";
import { apiGet, apiGetPage, apiPost } from "../services/api";
import {
  type Config, type Resource, type Target, eligibleConfig, eligibleTarget, runLink,
  useDefaultConfig, useExplorationSubmission, useOptions, withSelected,
} from "../services/evaluation";
import { CaseHistory } from "./CaseHistory";
import { OffsetPagination } from "./OffsetPagination";

type Run = { id: string; state: string; remote_model?: string; resource_kind?: string; created_at: string };
type Snapshot = { sha256: string; config_version_id: string; config_sha256: string; target_id: string; remote_model: string; resource_kind: string; sample_count: number; parameters: Record<string, unknown>; manifest_id: string; manifest_sha256: string; execution_origin: string };
type Detail = Run & { run_mode: string; gate_status: string; snapshot: Snapshot | null; execution_unresolved: boolean; cleanup: { state: string; attempt_count: number; last_error_code: string | null }; report: null | { id: string; validity: string; summary: Record<string, unknown> } };
const terminal = (state: string) => ["completed", "failed", "cancelled"].includes(state);
const resourceLabel = (kind?: string) => kind === "customer_ssh" ? "客户 SSH 服务器" : "本机 Docker";
const time = (value: string) => new Date(value).toLocaleString("zh-CN");

export function EvaluationRuns({ runId = "", initialTarget = "", allowSubmit = true }: { runId?: string; initialTarget?: string; allowSubmit?: boolean }) {
  const configs = useOptions<Config>("/test-configs");
  const targets = useOptions<Target>("/target-bindings");
  const docker = useOptions<Resource>("/resources");
  const ssh = useOptions<Resource>("/ssh-resources");
  const [resourceKind, setResourceKind] = useState("docker_local");
  const resources = resourceKind === "customer_ssh" ? ssh : docker;
  const [target, setTarget] = useState<Target | null>(null);
  const [resource, setResource] = useState<Resource | null>(null);
  const { config, setConfig, loadingDefault, defaultError, setDefaultError, reloadDefault } = useDefaultConfig(target);
  const { busy, setBusy, message, setMessage, submit } = useExplorationSubmission();
  const [runs, setRuns] = useState<Run[]>([]);
  const [offset, setOffset] = useState(0);
  const [pageSize,setPageSize] = useState(15);
  const [next, setNext] = useState<number | null>(null);
  const [listError, setListError] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [statusFilter, setStatusFilter] = useState("全部状态");
  const [resourceFilter, setResourceFilter] = useState("全部资源");
  const [query, setQuery] = useState("");

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

  useEffect(() => {
    const controller = new AbortController();
    let refreshing = false;
    setRuns([]); setNext(null);
    const refresh = async () => {
      if (refreshing || document.hidden) return;
      refreshing = true;
      try {
        const page = await apiGetPage<Run[]>(`/runs?offset=${offset}&limit=${pageSize}`, controller.signal);
        if (!controller.signal.aborted) { setRuns(page.data); setNext(page.next_offset); setListError(""); }
      } catch { if (!controller.signal.aborted) setListError("任务列表查询失败，恢复连接后自动重试。"); }
      finally { refreshing = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [offset, runId, pageSize]);

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

  const action = async (kind: "cancel" | "cleanup") => {
    setBusy(true);
    try { await apiPost(`/runs/${runId}/${kind}`); setMessage(kind === "cleanup" ? "清理意图已保存；后台核验归档后重试，不会重新测评。" : "取消意图已保存；等待当前请求返回后停止后续样本，已产生的用量不会撤销。"); }
    catch { setMessage("操作未确认，请查询任务状态后重试。"); }
    finally { setBusy(false); }
  };
  const configRows = withSelected(configs.rows.filter(eligibleConfig), config);
  const targetRows = withSelected(targets.rows.filter(eligibleTarget), target);
  const resourceRows = withSelected(resources.rows.filter((row) => resourceKind !== "customer_ssh" || row.native_tool_root), resource);
  const filteredRuns = runs.filter((row) => {
    const statusMatches = statusFilter === "全部状态" || (statusFilter === "执行中" ? !terminal(row.state) : row.state === statusFilter);
    const resourceMatches = resourceFilter === "全部资源" || row.resource_kind === resourceFilter;
    const queryMatches = `${row.id} ${row.remote_model || ""}`.toLowerCase().includes(query.toLowerCase());
    return statusMatches && resourceMatches && queryMatches;
  });

  return (
    <div className="stack evaluation-runs">
      {allowSubmit && (
        <section className="card stack">
          <div><h2>新建探索测评</h2><p className="muted">GPQA Lite 使用固定原生 AISBench 路径，每次最多 5 个样本、每样本最多 64 输出 tokens，无自动重测。</p></div>
          <p><a href="#console">登记模型、服务与资源</a> · <a href="#config">维护配置、清单与 Profile</a></p>
          <label>探索模型服务 <select aria-label="探索模型服务" value={target?.id || ""} disabled={busy || targets.loading} onChange={(event) => setTarget(targetRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择官方DeepSeek目标</option>{targetRows.map((row) => <option key={row.id} value={row.id}>{row.model_key} / {row.model_version} · {row.remote_model} · {row.id.slice(0, 8)}</option>)}</select></label>
          <OffsetPagination label="探索服务" offset={targets.offset} nextOffset={targets.next} onChange={targets.setOffset} disabled={targets.loading || busy} />
          <label>探索配置 <select aria-label="探索配置" value={config?.id || ""} disabled={busy || loadingDefault} onChange={(event) => { setConfig(configRows.find((row) => row.id === event.target.value) || null); setDefaultError(""); }}><option value="">请选择已绑定Profile的Lite配置</option>{configRows.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}</select></label>
          {loadingDefault && <p role="status">正在读取模型默认配置…</p>}{defaultError && <p role="status">{defaultError}</p>}
          <button disabled={busy || !target || loadingDefault} onClick={reloadDefault}>重新加载模型默认配置</button>
          <OffsetPagination label="探索配置" offset={configs.offset} nextOffset={configs.next} onChange={configs.setOffset} disabled={configs.loading || busy} />
          <label>探索资源接入方式<select aria-label="探索资源接入方式" value={resourceKind} disabled={busy} onChange={(event) => { setResourceKind(event.target.value); setResource(null); }}><option value="docker_local">本机Docker</option><option value="customer_ssh">客户SSH服务器</option></select></label>
          <label>探索执行资源 <select aria-label="探索执行资源" value={resource?.id || ""} disabled={busy || resources.loading} onChange={(event) => setResource(resourceRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择资源</option>{resourceRows.map((row) => <option key={row.id} value={row.id}>{row.binding_key}</option>)}</select></label>
          <OffsetPagination label="探索资源" offset={resources.offset} nextOffset={resources.next} onChange={resources.setOffset} disabled={resources.loading || busy} />
          {[configs, targets, resources].some((source) => source.error) && <p role="alert">选项加载失败。<button onClick={() => { configs.retry(); targets.retry(); resources.retry(); }}>重试选项加载</button></p>}
          <p className="muted">配置须为 GPQA 单数据集、Lite、并发 1、temperature=0、top_p=1。每页 20 条，翻页保留已选项，提交时后台再次校验。</p>
          <button className="primary" disabled={busy || loadingDefault || !config || !target || !resource} onClick={() => void submit(config, target, resource, resourceKind)}>提交真实GPQA Lite测评</button>
        </section>
      )}
      <p role="status">{message}</p>{listError && <p role="alert">{listError}</p>}

      {!runId && !initialTarget && (
        <>
          <div className="stats task-stats" aria-label="当前页任务统计">
            <section className="card"><div className="stat-icon"><Layers /></div><div>当前页任务<strong>{runs.length}</strong></div></section>
            <section className="card"><div className="stat-icon tone-1"><Play /></div><div>当前页执行中<strong>{runs.filter((row) => !terminal(row.state)).length}</strong></div></section>
            <section className="card"><div className="stat-icon tone-2"><CheckCircle2 /></div><div>当前页已完成<strong>{runs.filter((row) => row.state === "completed").length}</strong></div></section>
            <section className="card"><div className="stat-icon tone-3"><CircleAlert /></div><div>当前页失败 / 取消<strong>{runs.filter((row) => ["failed", "cancelled"].includes(row.state)).length}</strong></div></section>
          </div>
          <section className="card stack">
            <div className="spread"><div><h2>测评任务</h2><p className="muted">仅统计和筛选当前页；接口未提供全局总数。</p></div><a className="link" href="#console">发起探索测评</a></div>
            <div className="filters">
              <label className="select-field"><span>状态</span><select aria-label="任务状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>全部状态</option><option>执行中</option><option>completed</option><option>failed</option><option>cancelled</option></select></label>
              <label className="select-field"><span>资源</span><select aria-label="任务资源筛选" value={resourceFilter} onChange={(event) => setResourceFilter(event.target.value)}><option value="全部资源">全部资源</option><option value="docker_local">本机 Docker</option><option value="customer_ssh">客户 SSH 服务器</option></select></label>
              <label className="search"><input aria-label="搜索任务" placeholder="搜索任务 ID 或模型" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            </div>
            <label>已保存探索任务 <select aria-label="已保存探索任务" value={runId} onChange={(event) => { location.hash = event.target.value ? runLink(event.target.value) : "#tasks"; }}><option value="">请选择任务</option>{runs.map((row) => <option key={row.id} value={row.id}>{row.id} · {row.state}</option>)}</select></label>
            <div className="table-wrap"><table><thead><tr><th>任务</th><th>模型</th><th>运行方式</th><th>资源</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{filteredRuns.map((row) => <tr key={row.id}><td><a className="link strong" href={runLink(row.id)}>{row.id}</a></td><td>{row.remote_model || "—"}</td><td>GPQA Lite · exploration</td><td>{resourceLabel(row.resource_kind)}</td><td><span className={`case-status ${row.state === "completed" ? "passed" : ["failed", "cancelled"].includes(row.state) ? "error" : "running"}`}>{row.state}</span></td><td>{time(row.created_at)}</td><td><a className="link" href={runLink(row.id)}>查看</a></td></tr>)}</tbody></table>{!filteredRuns.length && <div className="empty">当前页没有符合条件的任务</div>}</div>
            <ListPagination label="任务" offset={offset} nextOffset={next} pageSize={pageSize} onOffsetChange={setOffset} onPageSizeChange={setPageSize} disabled={busy} />
          </section>
        </>
      )}

      {runId && <a className="link back" href="#tasks">返回任务列表</a>}
      {detailError && <p role="alert">{detailError}</p>}
      {detail && (
        <article className="card stack execution-detail" data-testid="evaluation-detail">
          <div className="execution-heading"><h2>测评任务详情</h2><span className={`case-status ${detail.state === "completed" ? "passed" : ["failed", "cancelled"].includes(detail.state) ? "error" : "running"}`}>{detail.state}</span></div>
          <p data-testid="evaluation-state">测评状态：{detail.state}</p>
          <div className="execution-meta">
            <span>运行 ID <b>{detail.id}</b></span>
            <span>创建时间 <b>{time(detail.created_at)}</b></span>
            <span>模型 <b>{detail.snapshot?.remote_model || detail.remote_model || "—"}</b></span>
            <span>运行方式 <b>{detail.run_mode} · 串行</b></span>
            <span>资源 <b>{resourceLabel(detail.snapshot?.resource_kind || detail.resource_kind)}</b></span>
            <span>配置版本 <b>{detail.snapshot?.config_version_id || "—"}</b></span>
            <span>样本数 <b>{detail.snapshot?.sample_count ?? "—"}</b></span>
            <span>执行来源 <b>{detail.snapshot?.execution_origin || "—"}</b></span>
            <span>发布门禁 <b>{detail.gate_status}</b></span>
          </div>
          <p>任务永久链接：<a href={runLink(detail.id)}>{runLink(detail.id)}</a></p>
          {detail.execution_unresolved && <p role="alert">执行待查证，保留占用及已有 attempt；请勿重新提交替代任务。</p>}
          {detail.snapshot && <details data-testid="run-snapshot"><summary>本次冻结配置与证据标识</summary><p>模型：{detail.snapshot.remote_model}；样本：{detail.snapshot.sample_count}；配置版本：{detail.snapshot.config_version_id}</p><p>清单：{detail.snapshot.manifest_id}；配置与清单 SHA-256 均保留在下方快照中。该快照不会随默认配置或配置新版本改变。</p><pre className="snapshot">{JSON.stringify(detail.snapshot, null, 2)}</pre></details>}
          {detail.cleanup.state !== "not_required" && <div><p data-testid="cleanup-state">资源清理：{({ not_scheduled: "尚未安排清理", pending: "等待归档核验与清理", running: "清理中", failed: "清理待恢复（保留占用）", cleaned: "清理已确认" } as Record<string, string>)[detail.cleanup.state] ?? detail.cleanup.state} · 尝试{detail.cleanup.attempt_count}次</p>{["failed", "not_scheduled"].includes(detail.cleanup.state) && detail.report && <button disabled={busy} onClick={() => void action("cleanup")}>重试资源清理</button>}</div>}
          <div><button disabled={busy || terminal(detail.state)} onClick={() => void action("cancel")}>取消探索测评</button></div>
          {detail.report ? <div><p data-testid="evaluation-validity">历史报告完整性：{detail.report.validity}</p><a className="link" href={`#report/${detail.report.id}`}>查看完整报告</a><details><summary>历史索引摘要（未在此页核验证据）</summary><p>当前对象可能缺失或不可用，请以报告页证据校验状态为准，不能仅凭缓存摘要确认成绩。</p><pre className="snapshot" data-testid="evaluation-summary">{JSON.stringify(detail.report.summary, null, 2)}</pre></details></div> : <p role="status">报告尚未生成；运行 completed 不代表报告已归档或完整。</p>}
          <CaseHistory key={detail.id} initialRun={detail.id} />
        </article>
      )}
    </div>
  );
}
