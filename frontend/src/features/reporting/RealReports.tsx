import { ListPagination } from "../../shared/ui/ListPagination";
import { useEffect, useState } from "react";
import { ReportView, type Report } from "./ReportView";
import { apiGetPage, apiPost } from "../../shared/api";

const reviewLabels: Record<string, string> = {
  pending: "未录入",
  approved: "已录入有效历史",
  revoked: "已撤销",
};

const validityLabels: Record<string, string> = {
  complete: "所选清单完整",
  partial: "部分有效",
  failed_summary: "执行失败摘要",
  invalid: "评分无效",
};

export function RealReports({ reportId, open }: { reportId?: string; open: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [model, setModel] = useState("");
  const [taskType, setTaskType] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [rows, setRows] = useState<Report[]>([]);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(15);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [reviewing, setReviewing] = useState("");

  const [total, setTotal] = useState<number>();
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [filters, setFilters] = useState<{ models: string[]; analysis_statuses: string[] }>({models: [], analysis_statuses: []});

  useEffect(() => {
    if (reportId) return;
    const controller = new AbortController();
    setRows([]);
    setMessage("");
    setLoading(true);
    setTotal(undefined);
    setNextOffset(null);
    const params = new URLSearchParams({summary_only: "true", limit: String(pageSize), offset: String(offset)});
    if (taskType) params.set("task_type", taskType);
    if (model) params.set("model", model);
    if (analysis) params.set("analysis_status", analysis);
    if (query) params.set("query", query);
    apiGetPage<Report[]>(`/reports?${params}`, controller.signal)
      .then(page => {
        if (controller.signal.aborted) return;
        if (page.total != null && offset > 0 && offset >= page.total) {
          setOffset(Math.max(0, Math.ceil(page.total / pageSize) - 1) * pageSize);
          return;
        }
        setRows(page.data);
        setTotal(page.total ?? undefined);
        setNextOffset(page.next_offset);
        if (page.filters) setFilters(page.filters);
      })
      .catch(() => {
        if (!controller.signal.aborted) setMessage("报告目录加载失败。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [refresh, reportId, taskType, model, analysis, query, offset, pageSize]);


  if (reportId) {
    return (
      <ReportView
        key={reportId}
        id={reportId}
        go={(path) => {
          if (path === "reports") window.location.hash = "reports";
          else if (path.startsWith("report/")) open(path.slice(7));
        }}
      />
    );
  }

  const review = async (row: Report) => {
    const decision = row.review_status === "approved" ? "revoke" : "approve";
    setReviewing(row.id);
    setMessage("");
    try {
      await apiPost(`/reports/${row.id}/review`, { decision });
      setRefresh((value) => value + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "审核状态更新失败");
    } finally {
      setReviewing("");
    }
  };
  const analysisLabel = (value: string) => ({ completed: "分析成功", succeeded: "分析成功", failed: "分析失败", pending: "待分析", queued: "排队中", running: "分析中", not_enabled: "未启用", not_queued: "待排队", unresolved: "待查证", not_requested: "未分析" }[value] || "暂无分析");
  return (
    <div className="stack" data-testid="real-report-catalog">
      <section className="card report-filters filters" aria-label="报告筛选">
        <label className="select-field"><span>任务类型</span><select value={taskType} onChange={event => { setOffset(0); setTaskType(event.target.value); }}><option value="">全部</option><option value="accuracy">精度</option><option value="performance">性能</option><option value="other">其他</option></select></label>
        <label className="select-field"><span>模型</span><select value={model} onChange={(e) => { setOffset(0); setModel(e.target.value); }}><option value="">全部模型</option>{[...new Set([...filters.models, ...(model ? [model] : [])])].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="select-field"><span>分析状态</span><select value={analysis} onChange={(e) => { setOffset(0); setAnalysis(e.target.value); }}><option value="">全部分析状态</option>{[...new Set([...filters.analysis_statuses, ...(analysis ? [analysis] : [])])].map((value) => <option key={value} value={value}>{analysisLabel(value)}</option>)}</select></label>
        <input aria-label="搜索报告或任务" placeholder="搜索报告或任务" value={query} onChange={(e) => { setOffset(0); setQuery(e.target.value); }} />
        <button onClick={() => setRefresh((value) => value + 1)}>刷新</button>
      </section>
      <section className="card table-card">
        <div className="report-list-heading"><h2>全部报告 <span className="badge">{total ?? "…"}</span></h2><span className="muted">每次测评独立保留报告 · 统计与筛选覆盖全部报告</span></div>
        {(message || loading) && <p role="status">{message || "报告加载中…"}</p>}
        <div className="table-wrap">
          <table className="reports-table">
            <thead>
              <tr>
                <th>报告 / 任务</th>
                <th>模型</th>
                <th>报告状态</th>
                <th>有效历史</th>
                <th>结果覆盖</th>
                <th>准确率</th>
                <th>生成时间</th><th>分析状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <b>{row.id.slice(0, 8)}</b>
                    <small title={row.run_id}>任务：{row.run_id.slice(0, 8)}</small>
                  </td>
                  <td>{row.remote_model}</td>
                  <td>
                    <span className={`report-validity-badge ${row.validity === "complete" ? "complete" : row.validity === "partial" ? "partial" : "error"}`}>
                      {row.task_type === "performance" ? (row.validity === "complete" ? "性能结果完整" : "性能结果不完整") : validityLabels[row.validity] || "状态待确认"}
                    </span>
                    <small className="report-context">{row.task_type === "performance" ? "性能测评" : "探索 · 门禁不适用"}</small>
                    {row.evidence_status !== "verified" && <small>原始证据暂不可用，成绩不参与比较。</small>}
                  </td>
                  <td>
                    <span className={`badge ${row.review_status === "approved" ? "green" : row.review_status === "revoked" ? "orange" : "neutral"}`}>
                      {reviewLabels[row.review_status] || row.review_status}
                    </span>
                    {row.reviewed_at && <small>{new Date(row.reviewed_at).toLocaleString("zh-CN")}</small>}
                  </td>
                  <td>
                    {row.task_type === "performance" ? "性能测评" : <>{row.summary.successful_samples}/{row.summary.expected_samples}
                    <small>
                      执行 {row.summary.executed_attempts} 次 · 失败 {row.summary.failed_samples} · 缺测 {row.summary.missing_samples}
                    </small>
                    <small>
                      {row.dataset_key || "GPQA"} · {row.summary.subset_scope === "lite" ? "Lite" : row.summary.subset_scope}
                    </small></>}
                  </td>
                  <td>
                    {row.evidence_status !== "verified" || row.summary.accuracy === null ? "—" : `${row.summary.accuracy}%`}
                    {row.task_type === "accuracy" && row.validity === "partial" && <small>仅成功样本</small>}
                  </td>
                  <td>{new Date(row.created_at).toLocaleString("zh-CN")}</td><td><span className={`report-analysis-badge analysis-${row.analysis_status}`}>{analysisLabel(row.analysis_status)}</span></td>
                  <td>
                    <button className="run-report-action" onClick={() => open(row.id)}>
                      查看报告
                    </button>
                    <button
                      onClick={() => review(row)}
                      disabled={row.task_type === "performance" || reviewing === row.id || row.evidence_status !== "verified" || row.validity !== "complete"}
                    >
                      {row.review_status === "approved" ? "撤销有效历史" : "录入为有效历史"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !rows.length && !message && (
            <div className="empty">没有符合条件的报告。</div>
          )}
        </div>
      </section>

      <ListPagination total={loading || message ? undefined : total} label="报告" offset={offset} nextOffset={nextOffset} pageSize={pageSize} onOffsetChange={setOffset} onPageSizeChange={setPageSize} disabled={loading} />
    </div>
  );
}
