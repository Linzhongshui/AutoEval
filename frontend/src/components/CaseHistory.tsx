import { useEffect, useState } from "react";
import { apiGet, apiGetPage } from "../services/api";

type Attempt = {
  id: string;
  dataset_key: string;
  sample_id: string;
  attempt_no: number;
  state: string;
  error_code: string | null;
  evidence_available: boolean;
  evidence_sha256: string | null;
  created_at: string;
  finished_at: string | null;
};

const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN") : "—";

export function CaseHistory({ initialRun = "" }: { initialRun?: string }) {
  const [run, setRun] = useState(initialRun);
  const [sample, setSample] = useState("");
  const [query, setQuery] = useState<{ run: string; sample: string; offset: number } | null>(null);
  const [rows, setRows] = useState<Attempt[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [selected, setSelected] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (initialRun) {
      setRun(initialRun);
      setQuery({ run: initialRun, sample: "", offset: 0 });
    }
  }, [initialRun]);
  useEffect(() => {
    if (!query) return;
    const controller = new AbortController();
    setRows([]); setNext(null); setSelected(""); setMessage("正在查询历史…");
    const suffix = `limit=20&offset=${query.offset}`;
    const path = `/runs/${encodeURIComponent(query.run)}/case-executions?${suffix}${query.sample ? `&sample_id=${encodeURIComponent(query.sample)}` : ""}`;
    apiGetPage<Attempt[]>(path, controller.signal)
      .then((page) => {
        setRows(page.data); setNext(page.next_offset);
        setMessage(page.data.length ? "历史已加载；评分结论请以报告为准。" : "该运行暂无匹配的 case 执行记录。");
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "历史查询失败");
      });
    return () => controller.abort();
  }, [query]);
  useEffect(() => {
    setEvidence(null);
    if (!selected) return;
    const controller = new AbortController();
    apiGet<unknown>(`/case-executions/${selected}/evidence`, controller.signal)
      .then(setEvidence)
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "证据读取失败");
      });
    return () => controller.abort();
  }, [selected]);

  return (
    <details className="diagnostic-tasks case-history" open={Boolean(initialRun)}>
      <summary>Case 执行历史</summary>
      <p>查询每次执行尝试及已校验的原始证据。重试成功仍保留此前失败；执行状态与评分正确性分开。</p>
      <div className="filters">
        <label>运行ID <input aria-label="回溯运行ID" value={run} onChange={(event) => setRun(event.target.value)} /></label>
        <label>样本ID（可选） <input aria-label="回溯样本ID" value={sample} onChange={(event) => setSample(event.target.value)} /></label>
        <button type="button" disabled={!run.trim()} onClick={() => setQuery({ run: run.trim(), sample: sample.trim(), offset: 0 })}>查询case历史</button>
      </div>
      <p role="status">{message}</p>
      {rows.length > 0 && (
        <div className="table-wrap" data-testid="case-attempts">
          <table>
            <thead><tr><th>数据集 / 样本</th><th>尝试</th><th>执行状态</th><th>错误类别</th><th>创建时间</th><th>完成时间</th><th>证据</th></tr></thead>
            <tbody>{rows.map((row) => (
              <tr key={row.id}>
                <td><b>{row.dataset_key}</b><small>{row.sample_id}</small></td>
                <td>第 {row.attempt_no} 次</td>
                <td><span className={`case-status ${row.state === "succeeded" ? "passed" : row.state === "failed" ? "error" : "running"}`}>{row.state}</span></td>
                <td>{row.error_code || "—"}</td>
                <td>{time(row.created_at)}</td>
                <td>{time(row.finished_at)}</td>
                <td>
                  <button className="link" type="button" disabled={!row.evidence_available} onClick={() => { setSelected(row.id); setEvidence(null); }}>查看第{row.attempt_no}次证据</button>
                  <small>SHA-256：{row.evidence_sha256 || "尚未归档"}</small>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {query && <div className="pagination"><button disabled={query.offset === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - 20) })}>历史上一页</button><button disabled={next === null} onClick={() => { if (next !== null) setQuery({ ...query, offset: next }); }}>历史下一页</button></div>}
      {evidence !== null && (
        <details open className="report-analysis-summary">
          <summary>证据已通过后端校验</summary>
          <pre className="snapshot" data-testid="case-evidence">{JSON.stringify(evidence, null, 2)}</pre>
        </details>
      )}
    </details>
  );
}
