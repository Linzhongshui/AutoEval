import type { components } from "../../shared/types/api";
import { TableWrap } from "../../shared/ui/TableWrap";
import { PageNumbers } from "../../shared/ui/PageNumbers";
import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, FileCheck2, Workflow } from "lucide-react";
import { apiGet, apiGetPage, apiPost } from "../../shared/api";
import { UnifiedOutputSummary } from "./UnifiedOutputSummary";

type ToolMetadata = {
  score?: number | null;
  tool_started_at: string | null;
  tool_finished_at: string | null;
  duration_sec: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  diagnostics: string[];
  status: string;
};
type Attempt = {
  metadata_provenance?: {kind: string; report_id: string; archive_sha256: string} | null;
  recovered_evidence?: unknown;
  provenance?: unknown;
  id: string;
  dataset_key: string;
  sample_id: string;
  attempt_no: number;
  state: string;
  error_code: string | null;
  trace_status?: string;
  trace_url?: string | null;
  trace_content_mode?: "structural" | "full" | null;
  evidence_available: boolean;
  evidence_sha256: string | null;
  created_at: string;
  finished_at: string | null;
  tool_metadata?: ToolMetadata | null;
};
type Query = { run: string; sample: string; state: string; offset: number; size: number };

const time = (value: string | null) => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "—";
const STATUS: Record<string, { label: string; tone: string }> = {
  succeeded: { label: "执行成功", tone: "passed" },
  failed: { label: "执行失败", tone: "error" },
  started: { label: "执行中 / 待查证", tone: "running" },
};
const caseScore = (metadata?: ToolMetadata | null) => typeof metadata?.score === "number" && Number.isFinite(metadata.score) ? String(metadata.score) : "未提供评分";

export function CaseHistory({ initialRun = "", datasets = [], selectedDataset, showPending, onRetry }: {
  initialRun?: string;
  datasets?: string[];
  selectedDataset?: string;
  showPending?: boolean;
  onRetry?: (datasetKey: string, sampleId: string) => void;
}) {
  const [dataset, setDataset] = useState(selectedDataset ?? "");
  const [revision, setRevision] = useState("");
  const [revisions, setRevisions] = useState<{id: string; dataset_key: string; created_at: string}[]>([]);
  useEffect(() => {
    setRevision(""); setRevisions([]);
    if (!initialRun) return;
    const c = new AbortController();
    apiGet<{id: string; dataset_key: string; created_at: string}[]>(`/runs/${initialRun}/result-revisions`, c.signal).then(setRevisions).catch(() => {});
    return () => c.abort();
  }, [initialRun]);
  const [pending, setPending] = useState<components["schemas"]["FollowUpPreview"]["samples"]>([]);
  const [pendingError, setPendingError] = useState(false);
  useEffect(() => {
    if (!showPending) return;
    const controller = new AbortController();
    apiGet<components["schemas"]["FollowUpPreview"]>(`/evaluation-tasks/${encodeURIComponent(initialRun)}/resume-preview`, controller.signal)
      .then(preview => setPending(preview.samples.filter(row => !row.has_attempts && row.category === "remaining")))
      .catch(() => { if (!controller.signal.aborted) setPendingError(true); });
    return () => controller.abort();
  }, [initialRun, showPending]);
  const evidenceDialog = useRef<HTMLDialogElement>(null);
  const [run, setRun] = useState(initialRun);
  const [stateFilter, setStateFilter] = useState("");
  const [sample, setSample] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [query, setQuery] = useState<Query | null>(null);
  const [rows, setRows] = useState<Attempt[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [selected, setSelected] = useState<Attempt | null>(null);
  const [evidence, setEvidence] = useState<unknown>(null);
  const [message, setMessage] = useState("");

  useEffect(() => { if (evidence !== null) evidenceDialog.current?.showModal(); }, [evidence]);

  useEffect(() => {
    if (initialRun) {
      setRun(initialRun);
      setQuery({ run: initialRun, sample: "", state: "", offset: 0, size: pageSize });
    }
  }, [initialRun]);

  useEffect(() => {
    if (!query) return;
    const controller = new AbortController();
    setRows([]); setNext(null); setTotal(null); setSelected(null); setEvidence(null); setMessage("正在查询历史…");
    const parts = [`limit=${query.size}`, `offset=${query.offset}`];
    parts.push(`evidence_version=${revision === "original" ? "original" : "current"}`);
    if (selectedDataset !== undefined) parts.push("prioritize_retries=true");
    if (dataset) parts.push(`dataset_key=${encodeURIComponent(dataset)}`);
    if (query.sample) parts.push(`sample_id=${encodeURIComponent(query.sample)}`);
    if (query.state) parts.push(`state=${encodeURIComponent(query.state)}`);
    apiGetPage<Attempt[]>(`/runs/${encodeURIComponent(query.run)}/${revision && revision !== "original" ? `result-revisions/${revision}/cases` : "case-executions"}?${parts.join("&")}`, controller.signal)
      .then((page) => {
        setRows(page.data); setNext(page.next_offset); setTotal(page.total ?? null);
        setMessage(
          page.data.length
            ? `已加载 ${page.data.length} 条执行记录`
            : query.state || query.sample
              ? "没有符合筛选条件的执行记录。"
              : "该运行暂无 case 执行记录。"
        );
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "历史查询失败");
      });
    return () => controller.abort();
  }, [query, dataset, revision, selectedDataset]);

  const applyState = (value: string) => {
    setStateFilter(value);
    if (!initialRun) return;
    setQuery({ run: initialRun, sample: sample.trim(), state: value, offset: 0, size: pageSize });
  };
  const changeSize = (value: number) => {
    setPageSize(value);
    if (query) setQuery({ ...query, offset: 0, size: value });
  };

  const openEvidence = (row: Attempt) => {
    setSelected(row);
    setEvidence(null);
    if (row.recovered_evidence) { setEvidence({recovered_evidence: row.recovered_evidence, provenance: row.provenance}); return; }
    const controller = new AbortController();
    apiGet<unknown>(`/case-executions/${row.id}/evidence?evidence_version=${revision === "original" ? "original" : "current"}`, controller.signal)
      .then(setEvidence)
      .catch((error) => {
        if (!controller.signal.aborted) setEvidence({ message: error instanceof Error ? error.message : "证据读取失败" });
      });
  };
  const pendingRows = pending.filter(row => (!dataset || row.dataset_key === dataset)
    && (!query?.sample || row.sample_id === query.sample));
  const detail = evidence && typeof evidence === "object" ? (evidence as Record<string, unknown>) : null;
  const meta = selected?.tool_metadata ?? null;
  const page = query ? Math.floor(query.offset / query.size) + 1 : 1;
  const visiblePending = showPending && !query?.state && !revision ? pendingRows : [];
  const combinedTotal = total === null ? null : total + visiblePending.length;
  const pendingPage = query && total !== null
    ? visiblePending.slice(Math.max(0, query.offset - total), Math.max(0, query.offset + query.size - total))
    : [];
  const nextPage = query && combinedTotal !== null && query.offset + query.size < combinedTotal
    ? query.offset + query.size : next;
  const pages = combinedTotal !== null ? Math.max(1, Math.ceil(combinedTotal / (query?.size ?? pageSize))) : null;

  const body = (
    <>
      <div className="case-history-heading">
        <div><h3>样本执行记录</h3><p className="muted">每次尝试独立保留执行结果、原始证据和 Agent 轨迹。</p></div>
        {rows.some(row => row.trace_url) && <span className="case-trace-hint"><Workflow size={15} aria-hidden="true" />在新标签页查看 Agent 轨迹</span>}
      </div>
      {initialRun && <UnifiedOutputSummary runId={initialRun} compact />}
      {rows.some(row => row.trace_status === "failed") && <button type="button" onClick={async () => {
        try {
          await apiPost(`/runs/${query?.run}/traces/retry`, {});
          setMessage("Trace 导入已重新排队，请刷新查看状态");
          setQuery(current => current ? {...current} : current);
        } catch { setMessage("Trace 重试失败"); }
      }}>重试失败的 Trace 导入</button>}
      {rows.some(row => row.trace_status === "pending") && <small>Trace 正在等待导入，刷新可查看最新状态</small>}
      <div className="filters case-toolbar">
        {revisions.length > 0 && <label>证据版本 <select aria-label="Case证据版本" value={revision} onChange={e => { setRevision(e.target.value); setQuery(q => q ? {...q, offset: 0} : q); }}><option value="">当前有效证据（含已核验恢复）</option><option value="original">原始归档（历史记录）</option>{revisions.map(r => <option key={r.id} value={r.id}>{r.dataset_key} · 恢复归档 · {time(r.created_at)}</option>)}</select></label>}
        {datasets.length > 1 && <label>数据集 <select aria-label="Case数据集筛选" value={dataset} onChange={e => { setDataset(e.target.value); setQuery(q => q ? {...q, offset: 0} : q); }}><option value="">全部数据集</option>{datasets.map(d => <option key={d} value={d}>{d}</option>)}</select></label>}
        {!initialRun && <label>运行ID <input aria-label="回溯运行ID" value={run} onChange={(event) => setRun(event.target.value)} /></label>}
        <label>样本ID（可选） <input aria-label="回溯样本ID" value={sample} onChange={(event) => setSample(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && run.trim()) setQuery({ run: run.trim(), sample: sample.trim(), state: stateFilter, offset: 0, size: pageSize }); }} /></label>
        <label>执行状态 <select aria-label="Case执行状态筛选" value={stateFilter} onChange={(event) => applyState(event.target.value)}><option value="">全部尝试</option><option value="succeeded">执行成功</option><option value="failed">执行失败</option><option value="started">执行中 / 待查证</option></select></label>
        {!initialRun && <button type="button" disabled={!run.trim()} onClick={() => setQuery({ run: run.trim(), sample: sample.trim(), state: stateFilter, offset: 0, size: pageSize })}>查询case历史</button>}
        {initialRun && <button type="button" onClick={() => setQuery({ run: initialRun, sample: sample.trim(), state: stateFilter, offset: 0, size: pageSize })}>筛选</button>}
      </div>
      <p className="case-history-message muted" role="status">{pendingPage.length ? `已加载 ${rows.length} 条执行记录 · ${pendingPage.length} 个待执行样本` : message}<span>执行状态与评分分别记录，缺少评分不补零。</span></p>
      {(rows.length > 0 || pendingPage.length > 0) && (
        <TableWrap data-testid="case-attempts">
          <table className="case-attempt-table">
            <thead><tr><th>数据集 / 样本</th><th>尝试</th><th>执行状态</th><th>得分</th><th>创建时间</th><th>耗时</th><th>Token（入 / 出）</th><th>证据与轨迹</th>{onRetry && <th>重试</th>}</tr></thead>
            <tbody>{rows.map((row) => {
              const status = STATUS[row.state] ?? { label: "待确认", tone: "pending" };
              return (
                <tr key={row.id}>
                  <td><b>{row.dataset_key}</b><small>{row.sample_id}</small></td>
                  <td>第 {row.attempt_no} 次</td>
                  <td>
                    <span className={`case-status ${status.tone}`}>{status.label}</span>
                    {row.error_code && <small className="case-cell-note">{row.error_code}</small>}
                  </td>
                  <td>{caseScore(row.tool_metadata)}{row.metadata_provenance && <small className="muted">恢复评分已核验</small>}</td>
                  <td>{time(row.created_at)}</td>
                  <td>{row.tool_metadata?.duration_sec != null ? `${row.tool_metadata.duration_sec} 秒` : "未采集"}</td>
                  <td>{row.tool_metadata ? row.tool_metadata.input_tokens == null && row.tool_metadata.output_tokens == null ? "未采集" : `${row.tool_metadata.input_tokens ?? "未采集"} / ${row.tool_metadata.output_tokens ?? "未采集"}` : "未采集"}</td>
                  <td className="case-evidence-cell">
                    <div className="case-evidence-actions">
                      <button className="case-evidence-button" type="button" disabled={!row.evidence_available} aria-label={`查看第${row.attempt_no}次证据`} onClick={() => openEvidence(row)}><FileCheck2 size={14} aria-hidden="true" />查看证据</button>
                      {row.trace_url && <a className="case-trace-button" href={row.trace_url} target="_blank" rel="noopener noreferrer" title="在新标签页查看本次执行的 Agent 轨迹">查看 Trace<ArrowUpRight size={14} aria-hidden="true" /></a>}
                    </div>
                    <small className="case-evidence-note">{row.trace_url ? row.trace_content_mode === "full" ? "正文轨迹已导入" : "轨迹已导入" : {pending: "Trace 等待导入", failed: "Trace 导入失败", missing: "缺少轨迹", disabled: "Langfuse 未配置", unsupported: "暂不支持 Trace"}[row.trace_status ?? "unsupported"]}<span aria-hidden="true"> · </span>{row.evidence_available ? "证据已校验" : "证据尚未归档"}</small>
                  </td>
                  {onRetry && <td><button type="button" onClick={() => onRetry(row.dataset_key, row.sample_id)}>重试此 Case</button></td>}
                </tr>
              );
            })}
            {pendingPage.map(row => <tr key={JSON.stringify([row.dataset_key, row.sample_id])}>
              <td><b>{row.dataset_key}</b><small>{row.sample_id}</small></td>
              <td>—</td>
              <td><span className="case-status pending">待执行</span></td>
              <td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>
              {onRetry && <td><button type="button" onClick={() => onRetry(row.dataset_key, row.sample_id)}>重试此 Case</button></td>}
            </tr>)}</tbody>
          </table>
        </TableWrap>
      )}
      {pendingError && <p role="status">待执行样本读取失败。</p>}
      {query && (
        <div className="pagination" aria-label="Case 列表分页">
          <span>{combinedTotal !== null ? `共 ${combinedTotal} 条 · 第 ${page} / ${pages} 页` : `第 ${page} 页`}</span>
          <label className="pagination-page-size"><span>每页</span><select aria-label="每页条数" value={pageSize} onChange={(event) => changeSize(Number(event.target.value))}>{[20, 50, 100].map((size) => <option key={size} value={size}>{size} 条</option>)}</select></label>
          <button disabled={query.offset === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - query.size) })}>上一页</button>
          <PageNumbers current={page} total={pages ?? (nextPage !== null ? page + 1 : page)} onChange={(value) => setQuery({ ...query, offset: (value - 1) * query.size })} />
          <button disabled={nextPage === null} onClick={() => { if (nextPage !== null) setQuery({ ...query, offset: nextPage }); }}>下一页</button>
        </div>
      )}
      {evidence !== null && createPortal(
        <dialog ref={evidenceDialog} className="management-drawer" aria-label="Case 执行证据" onCancel={() => setEvidence(null)}>
          <header className="spread"><h2>第 {selected?.attempt_no ?? "—"} 次执行证据</h2><button onClick={() => setEvidence(null)}>关闭</button></header>
          <p className="muted">证据读取时已核验 SHA-256；执行成功与判分通过分别记录，缺失值不补零。</p>
          {selected && (
            <dl className="detail-properties">
              <div><dt>数据集 / 样本</dt><dd>{selected.dataset_key} / {selected.sample_id}</dd></div>
              <div><dt>执行状态</dt><dd>{(STATUS[selected.state] ?? { label: "待确认" }).label}</dd></div>
              <div><dt>得分</dt><dd>{caseScore(meta)}</dd></div>
              <div><dt>错误类别</dt><dd>{selected.error_code || "无执行错误"}</dd></div>
              <div><dt>工具状态</dt><dd>{meta?.status || "—"}</dd></div>
              <div><dt>工具时间</dt><dd>{time(meta?.tool_started_at ?? null)} → {time(meta?.tool_finished_at ?? null)}</dd></div>
              <div><dt>工具耗时</dt><dd>{meta?.duration_sec != null ? `${meta.duration_sec} 秒` : "—"}</dd></div>
              <div><dt>Token</dt><dd>输入 {meta?.input_tokens ?? "—"} / 输出 {meta?.output_tokens ?? "—"}</dd></div>
              <div><dt>证据 SHA-256</dt><dd className="mono" title={selected.evidence_sha256 ?? ""}>{selected.evidence_sha256 ?? "—"}</dd></div>
            </dl>
          )}
          {selected?.error_code && <p className="notice">该次尝试存在执行异常。请检查服务连通性、资源环境及本次证据；结果未知时勿重复提交。</p>}
          {(meta?.diagnostics?.length ?? 0) > 0 && <p className="muted">诊断：{meta?.diagnostics.join("、")}</p>}
          {detail && !("message" in detail) && (
            <>
              <h3>模型输入</h3>
              <pre className="snapshot" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{detail.prompt == null ? "原始输入未采集" : String(detail.prompt) || "（输入为空）"}</pre>
              <h3>模型响应</h3>
              <pre className="snapshot" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{detail.response == null ? "原始响应未采集" : String(detail.response) || "（响应为空）"}</pre>
              {detail.native_evidence != null && <p className="muted">输入与响应来自已校验的原生预测归档，原始执行证据及评分保持不变。</p>}
            </>
          )}
          <details>
            <summary>完整证据与标识</summary>
            <pre className="snapshot" data-testid="case-evidence">{JSON.stringify(evidence, null, 2)}</pre>
          </details>
        </dialog>, document.body)}
    </>
  );
  return initialRun ? (
    <section className="stack case-history">{body}</section>
  ) : (
    <details className="diagnostic-tasks case-history"><summary>Case 执行历史</summary>{body}</details>
  );
}
