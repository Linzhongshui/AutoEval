import { useEffect, useState } from "react";
import { apiGet, apiGetPage } from "../../shared/api";

type Monitor = {
  datasets?: (Monitor & { dataset?: string })[];
  platform_state?: string;
  collection_status: string;
  stale: boolean;
  source?: string;
  task_name?: string;
  run_id?: string;
  attempt?: number;
  process_id?: number;
  tool_status?: string;
  finish_count?: number | null;
  total_count?: number | null;
  observed_at?: string;
  snapshot_kind?: string;
  progress_description?: string;
  progress_text?: string;
  time_cost?: string;
  tool_start_time?: number;
  diagnostics?: string[];
  log_available?: boolean;
  job_dir_available?: boolean;
  log?: { endpoint: string; sha256: string } | null;
};
type Snapshot = { id: string; kind: string; sha256: string; created_at: string; dataset?: string | null; summary?: string; summary_status?: string };
type ArchivedLog = { content: string; sha256: string; source: string };

const KIND_LABEL: Record<string, string> = {
  final: "终态已归档",
  last_observed: "仅最后观测（非终态）",
  live: "实时观测",
};
const SNAPSHOT_LABEL: Record<string, string> = {
  live: "过程快照",
  final: "终态快照",
  last_observed: "最后观测",
};
const STATUS_LABEL: Record<string, string> = {
  finish: "已完成",
  finished: "已完成",
  inferencing: "推理中",
  processing: "处理中",
  pending: "等待中",
  started: "执行中",
  succeeded: "执行成功",
  failed: "执行失败",
};
const PAGE = 20;
const stamp = (value?: number | string | null) => {
  if (value === null || value === undefined || value === "") return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("zh-CN");
};

function MonitorProgress({ value, error = false, stage, terminal = false }: { value: Monitor | null; error?: boolean; stage?: string; terminal?: boolean }) {
  const total = value?.total_count;
  const done = value?.finish_count;
  const known = typeof total === "number" && Number.isInteger(total) && total > 0
    && typeof done === "number" && Number.isInteger(done) && done >= 0 && done <= total;
  const percent = known ? Math.round(done / total * 100) : undefined;
  const stale = Boolean(value?.stale || error);
  const kind = value?.snapshot_kind || "live";
  const waiting = terminal ? "未记录样本进度" : value?.collection_status === "waiting_tool" ? "等待作业启动" : stale ? "等待恢复采集" : "等待样本计数";
  return <div className={`run-progress ${kind}${stale ? " stale" : ""}`} data-testid="run-progress">
    <div className="run-progress-head"><span>样本执行进度</span><b>{known ? `${done} / ${total} · ${percent}%` : waiting}</b></div>
    <div className={`run-progress-track${known ? "" : " unknown"}`} role="progressbar"
      aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="工具执行进度"
      aria-valuetext={known ? `已完成 ${done} / ${total} 个样本，${percent}%${stale ? "，数据已过期" : ""}` : waiting}>
      <i style={known ? { width: `${percent}%` } : undefined} />
    </div>
    <small>{stage && <>当前阶段：{stage} · </>}
      {stale ? "数据已过期，保留最后观测值" : known ? value?.source === "archived_case_executions" ? "进度来自已归档执行记录，不代表历史实时监控或评分通过" : "进度来自工具执行记录，执行完成不代表评分通过" : terminal ? "任务已结束，未记录有效样本计数" : "样本计数尚未返回，当前阶段与耗时持续更新"}
    </small>
  </div>;
}

type ProgressEvent = { type: string; created_at: string; dataset?: string | null; summary?: string; summary_status?: string };
const PHASES = ["提交与排队", "环境准备", "测评执行", "结果归档", "任务完成"];
const PHASE_INDEX: Record<string, number> = { accepted: 0, queued: 0, preparing: 1, running: 2, aggregating: 3, completed: 4 };
const duration = (milliseconds: number) => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  return `${hours ? `${hours}小时 ` : ""}${Math.floor(seconds % 3600 / 60)}分 ${String(seconds % 60).padStart(2, "0")}秒`;
};

function useRunMonitor(runId: string, terminal: boolean) {
  const [value, setValue] = useState<Monitor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      if (terminal || !document.hidden) {
        try {
          const row = await apiGet<Monitor>(`/runs/${runId}/monitor`, controller.signal);
          if (!controller.signal.aborted) { setValue(row); setError(""); }
        } catch {
          if (!controller.signal.aborted) setError("监控采集暂不可用，保留最后观测值");
        } finally {
          if (!controller.signal.aborted) setLoading(false);
        }
      }
      if (!controller.signal.aborted && !terminal) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [runId, terminal]);

  return { value, loading, error };
}

export function RunProgress({ runId, terminal, stage, state, createdAt, events = [], showSampleProgress = true }: {
  runId: string; terminal: boolean; stage: string; state: string; createdAt?: string; events?: ProgressEvent[]; showSampleProgress?: boolean;
}) {
  const { value, loading, error } = useRunMonitor(runId, terminal);
  const datasets = value?.datasets ?? [];
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const tick = () => { if (!document.hidden) setNow(Date.now()); };
    tick();
    if (terminal) return;
    const timer = setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", tick); };
  }, [runId, terminal]);
  const start = createdAt ? Date.parse(createdAt) : NaN;
  const recoveryIndex = events.map(event => event.type).lastIndexOf("results_recovered");
  const originalEnd = state === "completed" && recoveryIndex >= 0
    ? events.slice(0, recoveryIndex).filter(event => ["completed", "failed", "cancelled"].includes(event.type)).at(-1)
    : undefined;
  const endEvent = events.filter(event => event.type === state).at(-1) ?? originalEnd;
  const end = terminal ? endEvent ? Date.parse(endEvent.created_at) : NaN : now;
  const elapsed = Number.isFinite(start) && Number.isFinite(end) && end >= start ? duration(end - start) : "暂无时间记录";
  const stopped = state === "failed" || state === "cancelled" || state === "cancelling";
  const observedPhases = events.map(event => PHASE_INDEX[event.type]).filter(index => index !== undefined);
  const current = PHASE_INDEX[state] ?? (observedPhases.length ? Math.max(...observedPhases) : 0);
  return <section className={`task-progress-panel${stopped ? " interrupted" : ""}`} aria-label="任务进度与耗时">
    <div className="task-progress-summary"><div><span className="muted">当前阶段</span><strong>{stage}</strong></div>
      <div className="task-elapsed"><span className="muted">{terminal ? "总耗时" : "当前耗时"}</span><strong data-testid="run-elapsed">{elapsed}</strong></div>
    </div>
    <ol className="task-phase-steps" aria-label="任务阶段">
      {PHASES.map((label, index) => <li key={label} className={index < current || state === "completed" ? "done" : index === current ? stopped ? "interrupted" : "current" : "pending"} aria-current={index === current ? "step" : undefined}>
        <span className="task-phase-dot" aria-hidden="true">{index < current || state === "completed" ? "✓" : index === current && !terminal && !stopped ? <span className="phase-spinner" /> : stopped && index === current ? "!" : index + 1}</span><span>{label}</span>
      </li>)}
    </ol>
    {!terminal && <p className="task-wait-hint">{state === "accepted" || state === "queued" ? "提交已接收，正在等待执行资源" : state === "preparing" ? "正在校验环境并启动工具，阶段变化会自动更新" : state === "aggregating" ? "正在收集结果、校验证据并生成报告" : state === "cancelling" ? "正在确认远程作业停止，资源仍保留占用" : "工具正在执行；样本计数返回后自动显示完成比例"}</p>}
    {datasets.length > 0 && (!showSampleProgress || datasets.length > 1) ? datasets.map(item => <section className="card stack" key={item.dataset || item.task_name || item.attempt}>
      <h4>{item.dataset || item.task_name} · {STATUS_LABEL[item.tool_status || ""] || item.tool_status || "等待中"}</h4>
      <MonitorProgress value={item} error={Boolean(error)} terminal={item.snapshot_kind === "final"} />
      <p className="muted">{item.source === "executor_lifecycle" ? "远程作业状态采集；不是工具原生样本进度" : item.source} · {item.observed_at || "等待采集"}{item.stale ? " · 数据已过期" : ""}</p>
    </section>) : showSampleProgress
      ? <MonitorProgress value={value} error={Boolean(error)} terminal={terminal} />
      : <p className="muted">暂无分数据集样本进度。</p>}
    <small className="muted">{endEvent === originalEnd && originalEnd
      ? "总耗时截至原始运行结束，后续证据处理时间单独记录。"
      : "任务耗时包含排队、环境准备、测评与归档；样本进度和评分结论分别记录。"}</small>
    {(value?.stale || error) && <p className="notice" role="status">{error ? "读取监控接口失败，保留上次观测。" : "监控数据更新延迟，保留上次观测。"}</p>}
    <details className="tool-run-details">
      <summary>工具运行详情</summary>
      {value && (value.collection_status !== "not_collected" || value.log) ? <>
        <dl className="detail-properties monitor-properties">
          <div><dt>任务名</dt><dd>{value.task_name || "—"}</dd></div>
          <div><dt>运行 ID</dt><dd>{value.run_id || runId}</dd></div>
          <div><dt>执行尝试</dt><dd>{value.attempt ?? "—"}</dd></div>
          <div><dt>工具状态</dt><dd>{STATUS_LABEL[value.tool_status || ""] || value.tool_status || "—"}</dd></div>
          <div><dt>工具进程</dt><dd>{value.process_id ?? "—"}</dd></div>
          <div><dt>工具开始时间</dt><dd>{stamp(value.tool_start_time)}</dd></div>
          <div><dt>工具耗时</dt><dd>{value.time_cost || "—"}</dd></div>
          <div><dt>采集时间</dt><dd>{stamp(value.observed_at)}</dd></div>
          <div><dt>数据来源</dt><dd>{value.source || "—"}</dd></div>
          <div><dt>采集状态</dt><dd>{error ? "监控接口读取失败" : value.stale ? "等待下次观测" : "正常"}</dd></div>
          <div><dt>归档能力</dt><dd>{value.log_available ? "日志已归档" : "日志未归档"} · {value.job_dir_available ? "作业目录可用" : "作业目录不可用"}</dd></div>
        </dl>
        {(value.diagnostics?.length ?? 0) > 0 && (
          <p className="muted">诊断：{value.diagnostics?.join("、")}</p>
        )}
        <details>
          <summary>原始投影数据</summary>
          <pre className="snapshot" data-testid="monitor-raw">{JSON.stringify(value, null, 2)}</pre>
        </details>
      </> : <>
        <p className="muted" role="status">{loading ? "正在读取工具监控…" : error || "本次运行未采集工具监控。"}</p>
        <dl className="detail-properties"><div><dt>运行 ID</dt><dd>{runId}</dd></div></dl>
      </>}
    </details>
  </section>;
}

export function MonitorSnapshots({ runId, terminal }: { runId: string; terminal: boolean }) {
  const { value, error } = useRunMonitor(runId, terminal);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [snapshotOffset, setSnapshotOffset] = useState(0);
  const [snapshotMessage, setSnapshotMessage] = useState("");
  const [selected, setSelected] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);

  const [evidenceError, setEvidenceError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setSnapshots([]); setNext(null); setSelected("");
    setSnapshotMessage("正在读取监控快照…");
    apiGetPage<Snapshot[]>(`/runs/${runId}/monitor/snapshots?limit=${PAGE}&offset=${snapshotOffset}&include_summary=true`, controller.signal)
      .then(page => {
        if (controller.signal.aborted) return;
        setSnapshots(page.data); setNext(page.next_offset);
        setSnapshotMessage(page.data.length ? "" : "本次运行暂无监控快照。");
      }).catch(() => { if (!controller.signal.aborted) setSnapshotMessage("监控快照目录暂不可用。"); });
    return () => controller.abort();
  }, [runId, snapshotOffset]);

  useEffect(() => {
    setEvidence(null); setEvidenceError("");
    if (!selected) return;
    const controller = new AbortController();
    apiGet(`/runs/${runId}/monitor/snapshots/${selected}`, controller.signal)
      .then(data => { if (!controller.signal.aborted) setEvidence(data); })
      .catch(() => { if (!controller.signal.aborted) setEvidenceError("证据尚未归档或校验未通过"); });
    return () => controller.abort();
  }, [runId, selected]);

  const collected = value && (value.collection_status !== "not_collected" || value.log);
  const datasets = value?.datasets ?? [];
  const multi = datasets.length > 1;
  const finalCount = datasets.filter(item => item.snapshot_kind === "final").length;
  const allFinal = multi && finalCount === datasets.length;
  const kind = multi ? allFinal ? "final" : "live" : value?.snapshot_kind || "live";
  const headerKind = multi ? allFinal ? "全部数据集终态已归档" : finalCount ? "部分数据集已结束" : "数据集执行中" : KIND_LABEL[kind] || kind;
  const kindTone = value?.stale || error ? "orange" : kind === "final" ? "green" : kind === "live" ? "blue" : "orange";
  const evidenceRow = typeof evidence === "object" && evidence !== null ? (evidence as Record<string, unknown>) : null;
  const selectedSnapshot = snapshots.find((row) => row.id === selected);
  const projection = evidenceRow && typeof evidenceRow.projection === "object" ? evidenceRow.projection : evidence;
  const detail = projection as Partial<Monitor> | null;
  const raw = evidenceRow?.raw;

  return <section className="stack" aria-label="监控快照">
    {collected && <div className="inline"><span>采集状态</span><span className={`badge ${kindTone}`}>{headerKind}</span></div>}
    {evidenceError && <p role="status">{evidenceError}</p>}
    {snapshotMessage && <p role="status" className="muted">{snapshotMessage}</p>}
    {snapshots.length > 0 && (
      <ol className="monitor-list" data-testid="monitor-snapshots">
        {snapshots.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              className={`link ${selected === row.id ? "active" : ""}`}
              aria-pressed={selected === row.id}
              onClick={() => setSelected(row.id)}
            >
              <span className={`badge ${row.kind === "final" ? "green" : row.kind === "live" ? "blue" : "orange"}`}>{SNAPSHOT_LABEL[row.kind] ?? row.kind}</span>
              <span>{stamp(row.created_at)}</span>
              <span className="monitor-snapshot-dataset">数据集 · {row.dataset || "未记录"}</span>
              <span className="monitor-snapshot-summary">
                {row.summary || (row.summary_status === "unavailable" ? "摘要暂不可用" : "未记录进展")}
              </span>
              <span className="mono">{row.sha256.slice(0, 12)}</span>
            </button>
          </li>
        ))}
      </ol>
    )}
    {snapshots.length > 0 && (
      <div className="pagination">
        <button disabled={snapshotOffset === 0} onClick={() => setSnapshotOffset(Math.max(0, snapshotOffset - PAGE))}>上一页</button>
        <span>第 {snapshotOffset / PAGE + 1} 页</span>
        <button disabled={next === null} onClick={() => next !== null && setSnapshotOffset(next)}>下一页</button>
      </div>
    )}
    {evidence !== null && (
      <div className="monitor-evidence">
        <h4>快照内容 · 已通过完整性校验</h4>
        <p>{detail?.progress_description?.trim() || detail?.progress_text?.trim() || "未记录进展"}</p>
        <dl className="detail-properties">
          <div><dt>数据集</dt><dd>{selectedSnapshot?.dataset || "未记录"}</dd></div>
          <div><dt>采集时间</dt><dd>{stamp(detail?.observed_at)}</dd></div>
          {selectedSnapshot && <div><dt>校验指纹</dt><dd className="mono">{selectedSnapshot.sha256.slice(0, 12)}</dd></div>}
          {detail?.log_available !== undefined && (
            <div><dt>日志</dt><dd>{detail.log_available ? "已归档" : "未归档"}</dd></div>
          )}
          {detail?.job_dir_available !== undefined && (
            <div><dt>作业目录</dt><dd>{detail.job_dir_available ? "可用" : "不可用"}</dd></div>
          )}
        </dl>
        {!!detail?.diagnostics?.length && <p>诊断：{detail.diagnostics.join("、")}</p>}
        <details>
          <summary>投影字段</summary>
          <pre className="snapshot" data-testid="monitor-evidence">{JSON.stringify(projection, null, 2)}</pre>
        </details>
        {raw !== undefined && (
          <details>
            <summary>原始字段（脱敏）</summary>
            <pre className="snapshot">{JSON.stringify(raw, null, 2)}</pre>
          </details>
        )}
      </div>
    )}
  </section>;
}

export function RunLog({ runId, datasets }: { runId: string; datasets: string[] }) {
  const multi = datasets.length > 1;
  const [logDataset, setLogDataset] = useState("");
  const [log, setLog] = useState<ArchivedLog | null>(null);
  const [logMessage, setLogMessage] = useState("");

  useEffect(() => {
    setLog(null);
    if (multi && !logDataset) { setLogMessage("请选择日志数据集"); return; }
    const controller = new AbortController();
    setLogMessage("正在读取归档日志…");
    apiGet<ArchivedLog>(`/runs/${runId}/monitor/log${logDataset ? `?dataset_key=${encodeURIComponent(logDataset)}` : ""}`, controller.signal)
      .then(row => { if (!controller.signal.aborted) { setLog(row); setLogMessage(""); } })
      .catch(() => { if (!controller.signal.aborted) setLogMessage("本次运行未归档执行日志，或日志校验未通过。"); });
    return () => controller.abort();
  }, [runId, logDataset, multi]);

  return <section className="stack" aria-label="执行日志">
    {multi && <label>日志数据集 <select aria-label="日志数据集" value={logDataset} onChange={e => setLogDataset(e.target.value)}><option value="">请选择数据集</option>{datasets.map(d => <option key={d} value={d}>{d}</option>)}</select></label>}
    {logMessage && <p role="status" className="muted">{logMessage}</p>}
    {log && (
      <>
        <p className="muted">来源：归档作业日志 · SHA-256 {log.sha256.slice(0, 12)} · 读取时已核验完整性。</p>
        <pre className="snapshot monitor-log" data-testid="monitor-log">{log.content}</pre>
      </>
    )}
  </section>;
}
