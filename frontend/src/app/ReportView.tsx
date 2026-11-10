import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AnalysisPanel } from "../components/AnalysisPanel";
import { apiGet } from "../services/api";

type Summary = {
  expected_samples: number;
  executed_attempts: number;
  successful_samples: number;
  failed_samples: number;
  missing_samples: number;
  accuracy: number | null;
  subset_scope: string;
  dataset_samples: number;
  metric_scope: string;
  scoring_status?: string;
};

type BaselineComparison = {
  status: "matched" | "missing" | "incomparable";
  baseline_key: string | null;
  baseline_version: string | null;
  baseline_value: number | null;
  baseline_unit: string | null;
  baseline_direction: string | null;
  measured_value: number | null;
  difference: number | null;
};

export type Report = {
  id: string;
  run_id: string;
  remote_model: string;
  validity: string;
  created_at: string;
  summary: Summary;
  sha256: string;
  snapshot_sha256: string;
  run_mode: string;
  execution_origin: string;
  gate_status: string;
  baseline_comparison: BaselineComparison;
  analysis_status: string;
  analysis_id: string | null;
};

const validityLabels: Record<string, string> = {
  complete: "所选清单完整",
  partial: "部分有效",
  failed_summary: "执行失败摘要",
  invalid: "评分无效",
};

function accuracyText(value: number | null) {
  return value === null ? "—" : `${value}%`;
}

function baselineValue(value: number | null, unit: string | null) {
  if (value === null) return "—";
  return `${value}${unit === "percent" ? "%" : unit ? ` ${unit}` : ""}`;
}

function evidenceText(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? "—";
}

export function ReportView({ id, go }: { id: string; go: (path: string) => void }) {
  const [report, setReport] = useState<Report | null>(null);
  const [tab, setTab] = useState("结果分析");
  const [message, setMessage] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);
  const [evidenceRequested, setEvidenceRequested] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setReport(null);
    setMessage("");
    setTab("结果分析");
    setEvidence(null);
    setEvidenceRequested(false);
    setEvidenceOpen(false);
    apiGet<Report>(`/reports/${id}`, controller.signal)
      .then(setReport)
      .catch(() => {
        if (!controller.signal.aborted) setMessage("报告不存在或无法读取。");
      });
    return () => controller.abort();
  }, [id]);

  useEffect(() => {
    if (!evidenceRequested) return;
    const controller = new AbortController();
    setMessage("");
    apiGet(`/reports/${id}/evidence`, controller.signal)
      .then(setEvidence)
      .catch(() => {
        if (!controller.signal.aborted) {
          setMessage("报告证据不可用或完整性校验失败；不能据此确认报告有效。");
        }
      });
    return () => controller.abort();
  }, [id, evidenceRequested]);

  useEffect(() => {
    if (!evidenceOpen) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setEvidenceOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = prior;
      document.removeEventListener("keydown", close);
    };
  }, [evidenceOpen]);

  if (!report) {
    return (
      <div className="stack report-workspace">
        <div className="report-navigation-bar">
          <button className="link back" onClick={() => go("reports")}>
            返回报告列表
          </button>
        </div>
        <section className="card">
          <p role="status">{message || "报告加载中…"}</p>
        </section>
      </div>
    );
  }

  const { summary, baseline_comparison: baseline } = report;
  const coverage =
    report.validity === "complete"
      ? "complete"
      : report.validity === "partial"
        ? "partial"
        : "error";
  const stats: Array<[string, number | string]> = [
    ["expected_samples", summary.expected_samples],
    ["executed_attempts", summary.executed_attempts],
    ["successful_samples", summary.successful_samples],
    ["failed_samples", summary.failed_samples],
    ["missing_samples", summary.missing_samples],
    ["accuracy", accuracyText(summary.accuracy)],
    ["dataset_samples", summary.dataset_samples],
  ];
  const difference =
    baseline.status === "matched" && baseline.difference !== null
      ? `${baseline.difference > 0 ? "+" : ""}${baseline.difference}${baseline.baseline_unit === "percent" ? "pp" : baseline.baseline_unit ? ` ${baseline.baseline_unit}` : ""}`
      : "—";

  return (
    <div className="stack report-workspace" data-testid="real-report-detail">
      <div className="report-navigation-bar">
        <nav aria-label="报告返回导航" className="report-return-links">
          <button className="link" onClick={() => go("reports")}>
            返回报告列表
          </button>
        </nav>
      </div>

      <section className="card">
        <div className="spread">
          <h2>
            报告总览 <span className="badge">{report.id}</span>
          </h2>
          <span className={`coverage ${coverage}`}>
            {report.validity} · {validityLabels[report.validity] || report.validity}
          </span>
        </div>
        <div className="execution-meta">
          <span>remote_model <b>{report.remote_model}</b></span>
          <span>created_at <b>{report.created_at}</b></span>
          <span>run_id <b>{report.run_id}</b></span>
          <span>validity <b>{report.validity}</b></span>
          <span>execution_origin <b>{report.execution_origin}</b></span>
          <span>gate_status <b>{report.gate_status}</b></span>
          <span>run_mode <b>{report.run_mode}</b></span>
          <span>subset_scope <b>{summary.subset_scope}</b></span>
          <span>metric_scope <b>{summary.metric_scope}</b></span>
          <span>scoring_status <b>{summary.scoring_status || "—"}</b></span>
        </div>
        <div className="report-summary-stats table-wrap">
          {stats.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        {report.validity === "partial" && (
          <div className="notice">
            accuracy 仅成功样本；缺测与失败样本不按零分补入，不能替代完整清单成绩。
          </div>
        )}
        <div className="notice">
          当前清单 {summary.expected_samples} 个样本 / 数据集 {summary.dataset_samples} 个样本；本报告不代表全量成绩。运行 completed 不等于报告 complete，报告有效性以 validity 为准。
        </div>
        <p>
          <a className="link" href={`#run/${report.run_id}`}>
            查看来源任务与case历史
          </a>
        </p>
        <details className="report-analysis-summary">
          <summary>报告标识与校验值</summary>
          <div className="table-wrap">
            <table>
              <tbody>
                <tr><th>报告 ID</th><td>{report.id}</td></tr>
                <tr><th>报告 sha256</th><td>{report.sha256}</td></tr>
                <tr><th>快照 sha256</th><td>{report.snapshot_sha256}</td></tr>
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="card stack report-dataset-result">
        <div className="spread">
          <div>
            <h2>{report.remote_model}</h2>
            <p className="muted">
              {summary.subset_scope} · {summary.metric_scope} · {report.execution_origin}
            </p>
          </div>
          <span className={`coverage ${coverage}`}>{report.validity}</span>
        </div>
        <div className="tabs">
          {["结果分析", "报告证据"].map((name) => (
            <button
              className={tab === name ? "active" : ""}
              key={name}
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
        </div>

        {tab === "结果分析" ? (
          <>
            <div className="report-quality-metrics">
              <div>
                <span>accuracy{report.validity === "partial" ? "（仅成功样本）" : ""}</span>
                <strong>{accuracyText(summary.accuracy)}</strong>
              </div>
              <div>
                <span>成功 / 预期</span>
                <strong>
                  {summary.successful_samples}<small> / {summary.expected_samples}</small>
                </strong>
              </div>
              <div>
                <span>scoring_status</span>
                <strong>{summary.scoring_status || "—"}</strong>
              </div>
            </div>

            <div data-testid="baseline-comparison">
              <h3>基准对比 · {baseline.status}</h3>
              {baseline.status === "missing" && (
                <p>基准对比：暂无基准；不以零值替代，不计算差值。</p>
              )}
              {baseline.status === "incomparable" && (
                <p>基准对比：测试条件不一致，不可直接比较；不计算差值。</p>
              )}
              {baseline.status === "matched" && (
                <p>
                  基准对比：{baseline.baseline_key} {baseline.baseline_version}；基准 {baselineValue(baseline.baseline_value, baseline.baseline_unit)}，实测 {baselineValue(baseline.measured_value, baseline.baseline_unit)}，差值 {difference}。
                </p>
              )}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>指标</th><th>实测值</th><th>基准值</th><th>差异</th><th>比较条件</th></tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>accuracy<small>{summary.metric_scope}</small></td>
                      <td>{accuracyText(summary.accuracy)}</td>
                      <td>{baselineValue(baseline.baseline_value, baseline.baseline_unit)}</td>
                      <td>{difference}</td>
                      <td>
                        {baseline.status === "matched"
                          ? `${baseline.baseline_key} ${baseline.baseline_version} · ${baseline.baseline_direction}`
                          : baseline.status === "missing"
                            ? "无匹配基准"
                            : "测试条件不一致，不可直接比较"}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <section className="report-local-analysis">
              <AnalysisPanel
                reportId={report.id}
                status={report.analysis_status}
                onStatus={(state) =>
                  setReport((current) =>
                    current ? { ...current, analysis_status: state } : current,
                  )
                }
              />
            </section>
          </>
        ) : (
          <section>
            <div className="notice">
              证据仅在点击后读取，并由后端校验完整性；以下按原始文本或 JSON 展示。执行 succeeded 不代表逐 case 判分通过。
            </div>
            <p>
              <button
                onClick={() => {
                  setEvidenceOpen(true);
                  if (!evidenceRequested) setEvidenceRequested(true);
                }}
              >
                读取并校验报告证据
              </button>
            </p>
            <p role="status">{message}</p>
          </section>
        )}
      </section>

      {evidenceOpen &&
        createPortal(
          <div className="case-drawer-backdrop" onClick={() => setEvidenceOpen(false)}>
            <section
              className="case-drawer"
              role="dialog"
              aria-modal="true"
              aria-label="报告证据详情"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="spread">
                <h2>报告证据 · {report.id.slice(0, 8)}</h2>
                <button autoFocus onClick={() => setEvidenceOpen(false)}>关闭</button>
              </div>
              <p>报告证据已通过后端校验后原样返回，不生成额外判分或分析结论。</p>
              {evidence !== null ? (
                <pre className="snapshot" data-testid="real-report-evidence">
                  {evidenceText(evidence)}
                </pre>
              ) : (
                <p role="status">{message || "正在读取并校验报告证据…"}</p>
              )}
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
