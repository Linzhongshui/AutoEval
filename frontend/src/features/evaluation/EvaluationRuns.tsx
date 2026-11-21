import { TableWrap } from "../../shared/ui/TableWrap";
import { formatScore, formatDuration } from "../../shared/format";
import { RunMonitor, RunProgress } from "./RunMonitor";
import { SearchableSelect } from "../../shared/ui/SearchableSelect";
import { CopyIdentifier } from "../../shared/ui/CopyIdentifier";
import { SubmissionReview } from "./SubmissionReview";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { ListPagination } from "../../shared/ui/ListPagination";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, CircleAlert, Layers, Play } from "lucide-react";
import { apiGet, apiGetPage, apiPost } from "../../shared/api";
import type { Config, DatasetResult, Resource, Run, RunDetail, Target } from "./types";
import { datasetProgress, eligibleConfig, eligibleTarget, formatTime, isTerminal, resourceLabel, runLink, withSelected } from "./logic";
import { useDefaultConfig, useOptions } from "./hooks";
import { useExplorationSubmission } from "./submitIntent";
import { usePolling } from "../../shared/hooks/usePolling";
import { cleanupStatus, datasetStatus, taskStatus, toneClass } from "../../shared/status";
import { CaseHistory } from "../reporting/CaseHistory";

const terminal = (state: string) => isTerminal(state);
const time = formatTime;

const environmentLabels: Record<string, string> = {
  waiting_capacity: "等待容量", creating: "正在创建", submitting: "已分配",
  cleanup_pending: "待清理", cleaned: "已回收", not_created: "未创建",
};

function DatasetEnvironment({ environment }: { environment: NonNullable<DatasetResult["execution_environment"]> }) {
  return <>
    <small>SSH 主机 {environment.host || environment.resource_id}</small>
    <small title={environment.revision}>{environment.tool} · {environment.revision.slice(0, 12)}</small>
    <small>{environment.container_id && `容器 ${environment.container_id} · `}{environmentLabels[environment.state] || environment.state}</small>
  </>;
}

export function EvaluationRuns({ runId = "", initialTarget = "", allowSubmit = false }: { runId?: string; initialTarget?: string; allowSubmit?: boolean }) {
  const configs = useOptions<Config>("/test-configs", allowSubmit);
  const targets = useOptions<Target>("/target-bindings", allowSubmit);
  const docker = useOptions<Resource>("/resources", allowSubmit);
  const ssh = useOptions<Resource>("/ssh-resources", allowSubmit);
  const monitored = useOptions<Resource>("/aisbench-monitored/resources", allowSubmit);
  const [resourceKind, setResourceKind] = useState("docker_local");
  const resources = resourceKind === "aisbench_monitor" ? monitored : resourceKind === "customer_ssh" ? ssh : docker;
  const [target, setTarget] = useState<Target | null>(null);
  const [resource, setResource] = useState<Resource | null>(null);
  const { config, setConfig, loadingDefault, defaultError, setDefaultError, reloadDefault } = useDefaultConfig(target);
  const { busy, setBusy, message, setMessage, submit } = useExplorationSubmission();
  const [statistics, setStatistics] = useState({ total: 0, active: 0, completed: 0, failed_cancelled: 0 });
  const [runs, setRuns] = useState<Run[]>([]);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(15);
  const [next, setNext] = useState<number | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [detailTab, setDetailTab] = useState("执行进度");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [reportEvidence, setReportEvidence] = useState<unknown>(null);
  const [lastRefresh, setLastRefresh] = useState(0);
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

  // A filter change invalidates in-flight list responses so slow answers never
  // replace results for the newly selected filters.
  const listGeneration = useRef(0);
  useEffect(() => {
    listGeneration.current += 1;
    setRuns([]);
    setNext(null);
    setListLoading(true);
  }, [offset, pageSize, statusFilter, resourceFilter, query]);
  usePolling(
    async () => {
      const generation = listGeneration.current;
      try {
        const page = await apiGetPage<Run[]>(`/evaluation-tasks?offset=${offset}&limit=${pageSize}&state=${encodeURIComponent(statusFilter === "全部状态" ? "" : statusFilter === "执行中" ? "active" : statusFilter)}&resource_kind=${encodeURIComponent(resourceFilter === "全部资源" ? "" : resourceFilter)}&query=${encodeURIComponent(query)}`);
        if (generation !== listGeneration.current) return;
        setRuns(page.data);
        setNext(page.next_offset);
        if (page.statistics) setStatistics(page.statistics);
        setListError("");
        setListLoading(false);
      } catch {
        if (generation !== listGeneration.current) return;
        setListError("任务列表查询失败，恢复连接后自动重试；不能据此判断没有任务。");
        setListLoading(false);
      }
    },
    { intervalMs: 5000 },
  );
  useEffect(() => { setOffset(0); }, [statusFilter, resourceFilter, query]);

  // Terminal runs can still be reclaiming their dataset containers.
  usePolling(
    async () => {
      try {
        const row = await apiGet<RunDetail>(`/evaluation-tasks/${encodeURIComponent(runId)}`);
        setDetail(row);
        setLastRefresh(Date.now());
        setDetailError("");
      } catch {
        setDetailError("任务不存在或查询失败；已显示的状态可能过期，请勿据此重新提交。");
      }
    },
    { enabled: Boolean(runId) && (!terminal(detail?.state || "") || Boolean(detail?.datasets?.some(d => d.execution_environment?.state === "cleanup_pending"))), intervalMs: 2000 },
  );
  useEffect(() => { setDetail(null); setDetailError(""); }, [runId]);

  const action = async (kind: "cancel" | "cleanup") => {
    setBusy(true);
    try { await apiPost(`/evaluation-tasks/${runId}/${kind}`); setMessage(kind === "cleanup" ? "清理意图已保存；后台核验归档后重试，不会重新测评。" : "取消意图已保存；等待当前请求返回后停止后续样本，已产生的用量不会撤销。"); }
    catch { setMessage("操作未确认，请查询任务状态后重试。"); }
    finally { setBusy(false); }
  };
  const configRows = withSelected(configs.rows.filter(eligibleConfig), config);
  const targetRows = withSelected(targets.rows.filter(eligibleTarget), target);
  const resourceRows = withSelected(resources.rows.filter((row) => resourceKind !== "customer_ssh" || row.native_tool_root), resource);
  const filteredRuns = runs;

  return (
    <div className="stack evaluation-runs">
      {allowSubmit && (
        <section className="card stack">
          <div><h2>新建探索测评</h2><p className="muted">GPQA Lite 使用固定原生 AISBench 路径，每次最多 5 个样本；远程 AISBench 最多 2048 输出 tokens，其他兼容路径最多 64，无自动重测。</p></div>
          <p><a href="#console">登记模型、服务与资源</a> · <a href="#config">维护配置、清单与 Profile</a></p>
          <label>探索模型服务 <SearchableSelect aria-label="探索模型服务" value={target?.id || ""} disabled={busy || targets.loading} onChange={(event) => setTarget(targetRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择官方DeepSeek目标</option>{targetRows.map((row) => <option key={row.id} value={row.id}>{row.model_key} / {row.model_version} · {row.remote_model} · {row.id.slice(0, 8)}</option>)}</SearchableSelect></label>
          <label>探索配置 <SearchableSelect aria-label="探索配置" value={config?.id || ""} disabled={busy || loadingDefault} onChange={(event) => { setConfig(configRows.find((row) => row.id === event.target.value) || null); setDefaultError(""); }}><option value="">请选择已绑定Profile的Lite配置</option>{configRows.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}</SearchableSelect></label>
          {loadingDefault && <p role="status">正在读取模型默认配置…</p>}{defaultError && <p role="status">{defaultError}</p>}
          <button disabled={busy || !target || loadingDefault} onClick={reloadDefault}>重新加载模型默认配置</button>
          <label>探索资源接入方式<select aria-label="探索资源接入方式" value={resourceKind} disabled={busy} onChange={(event) => { setResourceKind(event.target.value); setResource(null); }}><option value="docker_local">本机Docker</option><option value="customer_ssh">客户SSH服务器</option><option value="aisbench_monitor">远程 AISBench（运行监控）</option></select></label>
          <label>探索执行资源 <SearchableSelect aria-label="探索执行资源" value={resource?.id || ""} disabled={busy || resources.loading} onChange={(event) => setResource(resourceRows.find((row) => row.id === event.target.value) || null)}><option value="">请选择资源</option>{resourceRows.map((row) => <option key={row.id} value={row.id}>{row.binding_key}</option>)}</SearchableSelect></label>
          {[configs, targets, resources].some((source) => source.error) && <p role="alert">选项加载失败。<button onClick={() => { configs.retry(); targets.retry(); resources.retry(); }}>重试选项加载</button></p>}
          <p className="muted">配置须为 GPQA 单数据集、Lite、并发 1、temperature=0、top_p=1。每页 20 条，翻页保留已选项，提交时后台再次校验。</p>
          <SubmissionReview config={loadingDefault ? null : config} target={target} resource={resource} resourceKind={resourceKind} busy={busy} submit={() => void submit(config, target, resource, resourceKind)} />
        </section>
      )}
      {message && <p role="status">{message}</p>}{listError && <p role="alert">{listError}</p>}

      {!runId && !initialTarget && (
        <>
          <div className="stats task-stats" aria-label="筛选结果任务统计">
            <section className="card"><div className="stat-icon"><Layers /></div><div>筛选结果任务<strong>{statistics.total}</strong></div></section>
            <section className="card"><div className="stat-icon tone-1"><Play /></div><div>执行中<strong>{statistics.active}</strong></div></section>
            <section className="card"><div className="stat-icon tone-2"><CheckCircle2 /></div><div>已完成<strong>{statistics.completed}</strong></div></section>
            <section className="card"><div className="stat-icon tone-3"><CircleAlert /></div><div>失败 / 取消<strong>{statistics.failed_cancelled}</strong></div></section>
          </div>
          <section className="card stack">
            <div className="spread"><div><h2>测评任务</h2><p className="muted">统计与筛选覆盖全部匹配任务；列表按页展示。</p></div><a className="link" href="#console">发起测评</a></div>
            <div className="filters">
              <label className="select-field"><span>状态</span><select aria-label="任务状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>全部状态</option><option>执行中</option><option value="completed">已完成</option><option value="failed">执行失败</option><option value="cancelled">已取消</option></select></label>
              <label className="select-field"><span>资源</span><select aria-label="任务资源筛选" value={resourceFilter} onChange={(event) => setResourceFilter(event.target.value)}><option value="全部资源">全部资源</option><option value="docker_local">本机 Docker</option><option value="customer_ssh">客户 SSH 服务器</option><option value="aisbench_monitor">远程 AISBench</option></select></label>
              <label className="search"><input aria-label="搜索任务" placeholder="搜索任务 ID 或模型" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            </div>

            <TableWrap><table className="evaluation-run-table"><thead><tr><th>任务</th><th>模型</th><th>运行方式</th><th>资源</th><th>状态</th><th>报告</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{filteredRuns.map((row) => <tr key={row.id}><td><a className="link strong" href={runLink(row.id)} title={row.id}>任务 {row.id.slice(0, 8)}</a></td><td>{row.remote_model || "—"}</td><td>{row.datasets?.join("、") || "历史测评"}</td><td>{resourceLabel(row.resource_kind)}</td><td><span className={`run-state-badge ${toneClass(taskStatus(row.state).tone)}`}>{taskStatus(row.state).label}</span></td><td>{row.report_id ? <a className="run-report-action" aria-label={`查看任务 ${row.id.slice(0, 8)} 的报告`} href={`#report/${row.report_id}`}>查看报告</a> : <span className="run-report-empty">未生成</span>}</td><td>{time(row.created_at)}</td><td><a className="link" href={runLink(row.id)}>查看</a></td></tr>)}</tbody></table>{!filteredRuns.length && <div className="empty">{listLoading ? "任务加载中…" : listError ? "任务查询失败" : "当前页没有符合条件的任务"}</div>}</TableWrap>
            <ListPagination total={listLoading || listError ? undefined : statistics.total} label="任务" offset={offset} nextOffset={next} pageSize={pageSize} onOffsetChange={setOffset} onPageSizeChange={setPageSize} disabled={busy} />
          </section>
        </>
      )}

      {runId && <a className="link back" href="#tasks">返回任务列表</a>}
      {detailError && <p role="alert">{detailError}</p>}
      {detail && (
        <article className="card stack execution-detail restored-detail" data-testid="evaluation-detail">
          <div className="spread"><div className="detail-title"><h2 title={detail.id}>任务 {detail.id.slice(0, 8)}</h2><span className={`badge ${toneClass(taskStatus(detail.state).tone)}`} data-testid="evaluation-state">{taskStatus(detail.state).label}</span><span className="muted">探索测评</span></div>
            <div className="inline">{!terminal(detail.state) && <button disabled={busy} onClick={() => void action("cancel")}>取消测评</button>}{detail.report && <a className="primary button" href={`#report/${detail.report.id}`}>查看报告</a>}</div></div>
          <div className="execution-meta">
            <span>模型 <b>{detail.snapshot?.remote_model || "—"}</b></span>
            <span>运行方式 <b>串行 · 探索</b></span>
            <span>创建时间 <b>{time(detail.created_at)}</b></span><span>状态更新时间 <b>{time(detail.updated_at)}</b></span><span>最近查询 <b>{lastRefresh ? new Date(lastRefresh).toLocaleTimeString("zh-CN") : "尚未刷新"}</b></span>
            <span>资源 <b>{resourceLabel(detail.snapshot?.resource_kind)}</b></span>
            <span>发布门禁 <b>不适用</b></span>
          </div>
          <div className="tabs">{["执行进度", "监控", "配置快照"].map((name) => <button key={name} className={detailTab === name ? "active" : ""} onClick={() => setDetailTab(name)}>{name}</button>)}</div>
          {detail.execution_unresolved && <p className="notice" role="alert">执行状态待查证，资源占用和已有记录已保留，请勿重复提交。</p>}
          {detailTab === "配置快照" ? <section data-testid="run-snapshot"><h3>本次配置快照</h3><dl className="detail-properties"><div><dt>执行参数</dt><dd>{detail.snapshot?.parameters ? Object.entries(detail.snapshot.parameters).map(([key, value]) => `${({output:"回答长度", concurrency:"并发数", temperature:"随机性", top_p:"候选范围", scope:"范围"} as Record<string,string>)[key] || key}：${String(value)}`).join("；") : "暂无信息"}</dd></div><div><dt>样本清单</dt><dd>{detail.snapshot?.manifest_id || "暂无信息"}</dd></div><div><dt>工具版本</dt><dd>{String(detail.snapshot?.tool?.revision || "暂无信息")}</dd></div></dl><p className="muted">本次提交时冻结，后续配置修改不会影响历史任务。</p><dl className="detail-properties"><div><dt>模型</dt><dd>{detail.snapshot?.remote_model || "—"}</dd></div><div><dt>样本数</dt><dd>{detail.snapshot?.sample_count ?? "—"}</dd></div><div><dt>配置版本</dt><dd>{detail.snapshot?.config_version_id || "—"}</dd></div></dl><ManagementDrawer title="查看完整快照与校验值"><pre className="snapshot">{JSON.stringify(detail.snapshot, null, 2)}</pre></ManagementDrawer></section> : detailTab === "监控" ? (
            <RunMonitor runId={detail.id} terminal={terminal(detail.state)} />
          ) : <>
            <section className="detail-progress">
              <div className="spread"><b>测评执行状态</b><span>{taskStatus(detail.state).label} · {detail.datasets?.map(d => d.dataset).join("、") || "测评任务"}</span></div>
              {detailError && <p className="notice" role="alert">当前展示为上次查询结果，状态可能过期；恢复连接后自动刷新。</p>}
              {detail.state === "failed" && <p role="alert">执行失败。请查看下方 Case 的错误类别和证据，确认原因后再决定后续操作。<button className="link" onClick={() => document.getElementById("case-detail")?.scrollIntoView({ behavior: "smooth", block: "start" })}>定位失败记录</button></p>}
              <RunProgress showSampleProgress={(detail.datasets?.length || 0) <= 1} runId={detail.id} terminal={terminal(detail.state)} state={detail.state} createdAt={detail.created_at} events={detail.events} stage={({ accepted: "已接收，等待调度", queued: "排队中", preparing: "准备执行环境", running: "测评执行中", aggregating: "收集结果与生成报告", completed: "执行结束", cancelling: "取消确认中，仍可能保留资源占用", cancelled: "取消已确认", failed: "执行失败" } as Record<string, string>)[detail.state] || "状态待确认"} />
              {detail.cancel_requested_at && <p>取消请求：{time(detail.cancel_requested_at)}；以终止确认及清理状态为准。</p>}
              <p className="muted">{detail.report ? "报告已归档，当前仅展示历史执行统计；成绩与证据完整性请查看报告。" : "报告尚未归档；工具进度来自监控观测，不代表评分结论。"}</p>
              <p className="muted">执行成功与判分通过分别记录；Case 列表保留每次尝试，缺失值不补零。</p>
            </section>
            <div className="task-overview-stats">{[["计划样本", detail.snapshot?.sample_count], ["执行成功", detail.report?.summary.successful_samples], ["执行失败", detail.report?.summary.failed_samples], ["缺测样本", detail.report?.summary.missing_samples], ["判分准确率", typeof detail.report?.summary.accuracy === "number" ? `${formatScore(detail.report.summary.accuracy)}%` : "—"], ["报告有效性", detail.report?.validity || "—"]].map(([label, value]) => <div className="case-stat" key={String(label)}><span>{String(label)}</span><strong>{value === undefined || value === null ? "—" : String(value)}</strong></div>)}</div>
            {!!detail.datasets?.length && <section className="card stack" aria-label="数据集执行结果"><h3>数据集执行结果</h3><TableWrap><table><thead><tr><th>数据集</th><th>状态</th><th>已归档样本</th><th>准确率</th><th>耗时</th><th>失败原因</th></tr></thead><tbody>{detail.datasets.map(d => <tr key={d.id}><td>{d.dataset}{d.execution_environment && <DatasetEnvironment environment={d.execution_environment} />}</td><td>{datasetStatus(d.state).label}<small>{datasetProgress(d.summary)}</small></td><td>{String(d.summary?.observed_cases ?? "—")} / {String(d.summary?.expected_cases ?? d.selected_cases ?? "—")}</td><td>{typeof d.summary?.accuracy === "number" ? `${formatScore(d.summary.accuracy)}%` : "—"}</td><td>{formatDuration(d.actual_duration_sec)}</td><td>{String(d.summary?.diagnostic ?? d.summary?.reason ?? "—")}</td></tr>)}</tbody></table></TableWrap><p className="muted">各数据集历史执行摘要独立展示，不生成跨数据集综合分；成绩有效性以归档证据核验为准。</p>{detail.dataset_report && <ManagementDrawer title="数据集报告与证据"><p>读取归档对象时核验哈希；不能读取时不以历史摘要替代。</p><button onClick={() => void apiGet(`/evaluation-tasks/${detail.id}/report`).then(setReportEvidence).catch(() => setMessage("报告证据读取或完整性校验失败"))}>读取归档报告</button>{reportEvidence != null && <pre className="snapshot">{JSON.stringify(reportEvidence, null, 2)}</pre>}</ManagementDrawer>}</section>}
            {detail.datasets?.some(d => d.summary?.recovery_report_id) && <p className="notice">本任务已从同次执行的原始产物恢复评分与归档；原失败历史保留，未重新调用模型。正式成绩见关联报告。</p>}
            <section id="case-detail" data-testid="case-detail">
              <CaseHistory key={`${detail.id}:${terminal(detail.state)}`} initialRun={detail.id} datasets={detail.datasets?.map(d => d.dataset) ?? []} />
            </section>
            <div className="detail-bottom-meta"><span data-testid="cleanup-state">资源清理：{cleanupStatus(detail.cleanup.state).label}</span>{["failed", "not_scheduled"].includes(detail.cleanup.state) && detail.report && <button disabled={busy} onClick={() => void action("cleanup")}>重试资源清理</button>}<ManagementDrawer title="任务标识与归档记录"><h3>状态记录</h3><ol>{detail.events?.map((event) => <li key={event.seq}>{time(event.created_at)} · {({ results_recovered: "结果恢复完成（未重跑）", accepted: "已接收", queued: "排队", preparing: "准备环境", running: "开始执行", aggregating: "汇总结果", completed: "执行完成", failed: "执行失败", cancelled: "取消确认", cancelling: "取消中", execution_unresolved: "结果待查证", execution_cleaned: "清理确认", execution_cleanup_pending: "等待清理" } as Record<string, string>)[event.type] || "状态变更"}</li>)}</ol><p>运行 ID：{detail.id}</p><CopyIdentifier value={detail.id} /><p>清理尝试：{detail.cleanup.attempt_count} 次</p><p data-testid="evaluation-validity">历史报告状态：{detail.report?.validity || "未归档"}</p><p>历史摘要不代表当前证据完整，成绩以报告核验结果为准。</p><pre className="snapshot" data-testid="evaluation-summary">{JSON.stringify(detail.report?.summary || {}, null, 2)}</pre></ManagementDrawer></div>
          </>}
        </article>
      )}
    </div>
  );
}
