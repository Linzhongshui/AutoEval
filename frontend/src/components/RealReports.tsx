import { useEffect, useState } from "react";
import { apiGet, apiGetPage } from "../services/api";
import { AnalysisPanel } from "./AnalysisPanel";

type Summary = { expected_samples: number; executed_attempts: number; successful_samples: number; failed_samples: number; missing_samples: number; accuracy: number | null; subset_scope: string; dataset_samples: number; metric_scope: string; scoring_status?: string };
type Report = { id: string; run_id: string; remote_model: string; validity: string; created_at: string; summary: Summary; sha256: string; snapshot_sha256: string; execution_origin: string; baseline_comparison: BaselineComparison; analysis_status: string; analysis_id: string | null };
type BaselineComparison = { status: "matched" | "missing" | "incomparable"; baseline_key: string | null; baseline_version: string | null; baseline_value: number | null; baseline_unit: string | null; baseline_direction: string | null; measured_value: number | null; difference: number | null };
const validity: Record<string, string> = { complete: "所选清单完整", partial: "部分有效", failed_summary: "执行失败摘要", invalid: "评分无效" };

export function RealReports({ reportId, open }: { reportId?: string; open: (id: string) => void }) {
  const [rows, setRows] = useState<Report[]>([]);
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [evidence, setEvidence] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [evidenceRequested, setEvidenceRequested] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setRows([]); setNext(null);
    apiGetPage<Report[]>(`/reports?limit=20&offset=${offset}`, controller.signal).then((page) => {
      setRows(page.data); setNext(page.next_offset);
    }).catch(() => { if (!controller.signal.aborted) setMessage("报告目录加载失败。"); });
    return () => controller.abort();
  }, [offset, refresh]);
  useEffect(() => {
    setReport(null); setEvidence(null); setEvidenceRequested(false); setMessage("");
    if (!reportId) return;
    const controller = new AbortController();
    apiGet<Report>(`/reports/${reportId}`, controller.signal).then(setReport)
      .catch(() => { if (!controller.signal.aborted) setMessage("报告不存在或无法读取。"); });
    return () => controller.abort();
  }, [reportId]);
  useEffect(() => {
    if (!reportId || !evidenceRequested) return;
    const controller = new AbortController();
    apiGet(`/reports/${reportId}/evidence`, controller.signal).then(setEvidence)
      .catch(() => { if (!controller.signal.aborted) setMessage("报告证据不可用或完整性校验失败；不能据此确认报告有效。"); });
    return () => controller.abort();
  }, [reportId, evidenceRequested]);
  return <section className="diagnostic-tasks">
    <h2>测评报告</h2>
    <p>此目录读取已归档的真实运行报告；模拟及来源未核验的测试产物不进入此列表。当前报告均为探索任务，发布门禁不适用。</p>
    <button onClick={() => { setMessage(""); setRefresh((value) => value + 1); }}>刷新报告目录</button>
    <p role="status">{message}</p>
    <div style={{ overflowX: "auto" }}><table><thead><tr><th>模型</th><th>范围</th><th>完整性</th><th>成功/预期</th><th>原生成绩</th><th>操作</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id}><td>{row.remote_model}</td><td>Lite</td><td>{validity[row.validity] || row.validity}</td><td>{row.summary.successful_samples}/{row.summary.expected_samples}</td><td>{row.summary.accuracy === null ? "—" : `${row.summary.accuracy}%`}{row.validity === "partial" ? "（仅成功样本）" : ""}</td><td><button onClick={() => open(row.id)}>查看报告 {row.id.slice(0, 8)}</button></td></tr>)}</tbody></table></div>
    {!rows.length && <p>当前页暂无真实报告。</p>}
    <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>报告上一页</button>
    <button disabled={next === null} onClick={() => { if (next !== null) setOffset(next); }}>报告下一页</button>
    {report && <article data-testid="real-report-detail">
      <h3>{report.remote_model} · GPQA Lite</h3>
      <p>完整性：{validity[report.validity] || report.validity}；门禁：不适用</p>
      <p>当前清单 {report.summary.expected_samples} 个样本 / 数据集 {report.summary.dataset_samples} 个样本；本报告不代表全量成绩。</p>
      <p>执行成功 {report.summary.successful_samples}，失败 {report.summary.failed_samples}，缺测 {report.summary.missing_samples}。</p>
      <p>原生 accuracy：{report.summary.accuracy === null ? "无有效成绩" : `${report.summary.accuracy}%`}{report.validity === "partial" ? "，仅对应成功样本，不能替代完整清单成绩。" : ""}</p>
      <div data-testid="baseline-comparison">
        {report.baseline_comparison.status === "missing" && <p>基准对比：暂无基准；不以零值替代。</p>}
        {report.baseline_comparison.status === "incomparable" && <p>基准对比：测试条件不一致，不可直接比较；不计算差值。</p>}
        {report.baseline_comparison.status === "matched" && <p>基准对比：{report.baseline_comparison.baseline_key} {report.baseline_comparison.baseline_version}，基准 {report.baseline_comparison.baseline_value}{report.baseline_comparison.baseline_unit}，实测 {report.baseline_comparison.measured_value}{report.baseline_comparison.baseline_unit}，差值 {report.baseline_comparison.difference === null ? "不可计算" : `${report.baseline_comparison.difference > 0 ? "+" : ""}${report.baseline_comparison.difference}pp`}。</p>}
      </div>
      <AnalysisPanel reportId={report.id} status={report.analysis_status} onStatus={(state) => setReport((current) => current ? { ...current, analysis_status: state } : current)} />
      <p>运行ID：{report.run_id}（任务页可回溯逐次执行证据）</p>
      <details><summary>报告标识与校验值</summary><p>报告ID：{report.id}</p><p>报告SHA-256：{report.sha256}</p><p>快照SHA-256：{report.snapshot_sha256}</p></details>
      <button onClick={() => setEvidenceRequested(true)}>读取并校验报告证据</button>
      {evidence !== null && <details open><summary>报告证据已通过后端校验</summary><pre data-testid="real-report-evidence" style={{ overflow: "auto", maxHeight: 400 }}>{JSON.stringify(evidence, null, 2)}</pre></details>}
    </article>}
  </section>;
}
