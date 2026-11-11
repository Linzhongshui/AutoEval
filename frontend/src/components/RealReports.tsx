import { ListPagination } from "./ListPagination";
import { useEffect, useState } from "react";
import { ReportView, type Report } from "../app/ReportView";
import { apiGetPage } from "../services/api";

const validityLabels: Record<string, string> = {
  complete: "所选清单完整",
  partial: "部分有效",
  failed_summary: "执行失败摘要",
  invalid: "评分无效",
};

export function RealReports({ reportId, open }: { reportId?: string; open: (id: string) => void }) {
  const [rows, setRows] = useState<Report[]>([]);
  const [offset, setOffset] = useState(0);
  const [pageSize,setPageSize] = useState(15);
  const [next, setNext] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (reportId) return;
    const controller = new AbortController();
    setRows([]);
    setNext(null);
    setMessage("");
    setLoading(true);
    apiGetPage<Report[]>(`/reports?limit=${pageSize}&offset=${offset}`, controller.signal)
      .then((page) => {
        setRows(page.data);
        setNext(page.next_offset);
      })
      .catch(() => {
        if (!controller.signal.aborted) setMessage("报告目录加载失败。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset, refresh, reportId, pageSize]);

  if (reportId) {
    return (
      <ReportView
        key={reportId}
        id={reportId}
        go={(path) => {
          if (path === "reports") window.location.hash = "reports";
        }}
      />
    );
  }

  return (
    <div className="stack" data-testid="real-report-catalog">
      <section className="card">
        <div className="spread">
          <div>
            <h2>全部报告 <span className="badge">{rows.length}</span></h2>
            <p className="muted">每次真实探索测评独立保留报告；模拟及来源未核验的产物不进入目录。</p>
          </div>
          <button onClick={() => setRefresh((value) => value + 1)}>刷新报告目录</button>
        </div>
        <p className="muted">当前页统计不代表全局数量；发布门禁不适用，运行 completed 不等于报告 complete。</p>
        <p role="status">{message || (loading ? "报告目录加载中…" : "")}</p>
      </section>

      <section className="card table-card">
        <div className="table-wrap">
          <table className="reports-table">
            <thead>
              <tr>
                <th>报告 / run_id</th>
                <th>remote_model</th>
                <th>validity / 来源</th>
                <th>结果覆盖</th>
                <th>accuracy</th>
                <th>created_at</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <b>{row.id.slice(0, 8)}</b>
                    <small>run_id：{row.run_id}</small>
                  </td>
                  <td>{row.remote_model}</td>
                  <td>
                    <span className={`coverage ${row.validity === "complete" ? "complete" : row.validity === "partial" ? "partial" : "error"}`}>
                      {row.validity} · {validityLabels[row.validity] || row.validity}
                    </span>
                    <small>execution_origin：{row.execution_origin}</small>
                    <small>gate_status：{row.gate_status}</small>
                    {row.evidence_status !== "verified" && <small>原始证据未验证：{row.evidence_status}；历史索引不作为有效成绩。</small>}
                  </td>
                  <td>
                    {row.summary.successful_samples}/{row.summary.expected_samples}
                    <small>
                      executed {row.summary.executed_attempts} · failed {row.summary.failed_samples} · missing {row.summary.missing_samples}
                    </small>
                    <small>
                      {row.summary.subset_scope} · dataset_samples {row.summary.dataset_samples}
                    </small>
                    <small>
                      {row.summary.metric_scope} · scoring_status {row.summary.scoring_status || "—"}
                    </small>
                  </td>
                  <td>
                    {row.evidence_status !== "verified" || row.summary.accuracy === null ? "—" : `${row.summary.accuracy}%`}
                    {row.validity === "partial" && <small>仅成功样本</small>}
                  </td>
                  <td>{row.created_at}</td>
                  <td>
                    <button className="link" onClick={() => open(row.id)}>
                      查看报告 {row.id.slice(0, 8)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !rows.length && !message && (
            <div className="empty">当前页暂无真实报告。</div>
          )}
        </div>
      </section>

      <ListPagination label="报告" offset={offset} nextOffset={next} pageSize={pageSize} onOffsetChange={setOffset} onPageSizeChange={setPageSize} disabled={loading} />
    </div>
  );
}
