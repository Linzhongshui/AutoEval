import { ArrowUpRight, Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiGet, apiPost, apiPostBlob } from "../../shared/api";

type Band = "high" | "low" | "non_badcase";

type Verdict = {
  is_badcase: boolean;
  band: Band;
  suspicion: number;
  method: string;
  confidence: string;
  p_hat: number | null;
  hard_signals: string[];
  soft_signals: string[];
  multiplier: number;
  why_not_badcase: string | null;
  reasons: string[];
};

type HistoryScore = {
  report_id: string;
  run_id: string;
  created_at: string;
  score: number;
};

type CaseRow = {
  sample_id: string;
  current: {
    score: number | null;
    state: string;
    attempt_no: number;
    error_code: string | null;
    has_evidence: boolean;
    missing?: boolean;
    evidence_status?: string;
    score_status?: string;
    trace_status?: string;
  };
  history: { n: number; k: number; mean: number | null; scores: HistoryScore[] };
  delta: number | null;
  verdict: Verdict;
};

type CaseDetail = {
  sample_id: string;
  dataset_key: string;
  current: {
    score: number | null;
    state: string;
    missing: boolean;
    evidence_status: string | null;
    available: boolean;
    prompt: string | null;
    response: string | null;
  };
  history: {
    report_id: string;
    run_id: string;
    created_at: string;
    score: number;
    available: boolean;
    prompt: string | null;
    response: string | null;
  }[];
};

type Dataset = {
  dataset_key: string;
  config: Record<string, unknown>;
  history: { approved_reports: number; report_ids: string[] };
  summary: { total: number; high: number; low: number; non_badcase: number; missing?: number };
  cases: CaseRow[];
};

type Comparison = {
  run_id: string;
  report_id: string;
  generated_at: string;
  report: {
    validity: string;
    evidence_status: string;
    review_status: string;
    remote_model: string | null;
    created_at: string;
  };
  algorithm: {
    name: string;
    alpha: number;
    beta: number;
    min_history: number;
    p_threshold: number;
  };
  datasets: Dataset[];
};

const BANDS: Record<Band, { label: string; tone: string }> = {
  high: { label: "可疑度较高", tone: "orange" },
  low: { label: "可疑度较低", tone: "blue" },
  non_badcase: { label: "非 badcase", tone: "neutral" },
};

const REVIEW_LABELS: Record<string, string> = {
  pending: "未录入有效历史",
  approved: "已录入有效历史",
  revoked: "已撤销有效历史",
};

const keyOf = (dataset: Dataset, row: CaseRow) => `${dataset.dataset_key}|${row.sample_id}`;
const scoreText = (value: number | null | undefined) =>
  typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
const numberText = (value: number | null | undefined, digits = 4) =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
const time = (value: string) =>
  value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString("zh-CN") : "—";

export function BadcaseComparison({
  runId,
  go,
  embedded = false,
}: {
  runId: string;
  go: (path: string) => void;
  embedded?: boolean;
}) {
  const [data, setData] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [dataset, setDataset] = useState("");
  const [band, setBand] = useState("");
  const [scoreFilter, setScoreFilter] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState("");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailMessage, setDetailMessage] = useState("");
  const [exporting, setExporting] = useState("");
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setData(null);
    setMessage("");
    setDataset("");
    setBand("");
    setScoreFilter("");
    setQuery("");
    setSelected(new Set());
    setExpanded("");
    apiGet<Comparison>(`/runs/${runId}/badcase-comparison`, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setMessage(error instanceof Error ? error.message : "Badcase 对比读取失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId]);

  useEffect(() => {
    if (!expanded) {
      setDetail(null);
      setDetailMessage("");
      return;
    }
    const split = expanded.indexOf("|");
    const datasetKey = expanded.slice(0, split);
    const sampleId = expanded.slice(split + 1);
    const controller = new AbortController();
    setDetail(null);
    setDetailMessage("");
    setDetailLoading(true);
    apiGet<CaseDetail>(
      `/runs/${runId}/badcase-case?sample_id=${encodeURIComponent(sampleId)}&dataset_key=${encodeURIComponent(datasetKey)}`,
      controller.signal,
    )
      .then(setDetail)
      .catch((error) => {
        if (!controller.signal.aborted) {
          setDetailMessage(error instanceof Error ? error.message : "推理内容读取失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [expanded, runId]);

  const activeDatasets = useMemo(
    () => (data ? data.datasets.filter((item) => !dataset || item.dataset_key === dataset) : []),
    [data, dataset],
  );
  const rows = useMemo(
    () =>
      activeDatasets.flatMap((item) =>
        item.cases.map((row) => ({ dataset: item, row })),
      ),
    [activeDatasets],
  );
  const filtered = useMemo(
    () =>
      rows.filter(({ row }) => {
        if (band && row.verdict.band !== band) return false;
        if (scoreFilter === "zero" && row.current.score !== 0) return false;
        const term = query.trim().toLowerCase();
        return !term || row.sample_id.toLowerCase().includes(term);
      }),
    [rows, band, scoreFilter, query],
  );
  const selectedRows = rows.filter(({ dataset: item, row }) => selected.has(keyOf(item, row)));
  const summary = useMemo(
    () =>
      activeDatasets.reduce(
        (total, item) => ({
          total: total.total + item.summary.total,
          high: total.high + item.summary.high,
          low: total.low + item.summary.low,
          non_badcase: total.non_badcase + item.summary.non_badcase,
          missing: total.missing + (item.summary.missing ?? 0),
          reports: Math.max(total.reports, item.history.approved_reports),
        }),
        { total: 0, high: 0, low: 0, non_badcase: 0, missing: 0, reports: 0 },
      ),
    [activeDatasets],
  );
  const allSelected =
    filtered.length > 0 &&
    filtered.every(({ dataset: item, row }) => selected.has(keyOf(item, row)));
  const selectedDataset = new Set(selectedRows.map((item) => item.dataset.dataset_key));
  const reviewStatus = data?.report.review_status ?? "pending";

  const toggle = (item: Dataset, row: CaseRow) => {
    const key = keyOf(item, row);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((current) => {
      const next = new Set(current);
      if (allSelected) {
        filtered.forEach(({ dataset: item, row }) => next.delete(keyOf(item, row)));
      } else {
        filtered.forEach(({ dataset: item, row }) => next.add(keyOf(item, row)));
      }
      return next;
    });
  };

  const download = async (
    scope: "high" | "suspicious" | "selected" | "all",
    overrides?: { sampleIds?: string[]; datasetKey?: string },
  ) => {
    if (!data) return;
    const sampleIds = overrides?.sampleIds ?? selectedRows.map((item) => item.row.sample_id);
    if (scope === "selected" && !sampleIds.length) {
      setMessage("请先选择需要导出的 case。");
      return;
    }
    setExporting(scope + (overrides?.sampleIds ? ":" + sampleIds[0] : ""));
    setMessage("");
    try {
      const result = await apiPostBlob(`/runs/${data.run_id}/badcase-export`, {
        dataset_key:
          overrides?.datasetKey ??
          (dataset || (selectedDataset.size === 1 ? [...selectedDataset][0] : null)),
        scope,
        sample_ids: scope === "selected" ? sampleIds : [],
        include_traces: true,
      });
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已生成 ${result.filename}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分析包导出失败");
    } finally {
      setExporting("");
    }
  };

  const toggleReview = async () => {
    if (!data) return;
    setReviewing(true);
    setMessage("");
    try {
      const result = await apiPost<{ review_status: string }>(
        `/reports/${data.report_id}/review`,
        { decision: reviewStatus === "approved" ? "revoke" : "approve" },
      );
      setData((current) =>
        current
          ? { ...current, report: { ...current.report, review_status: result.review_status } }
          : current,
      );
      setMessage(
        result.review_status === "approved"
          ? "已录入为有效历史。"
          : "已撤销有效历史。",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "审核状态更新失败");
    } finally {
      setReviewing(false);
    }
  };

  if (loading) {
    return (
      <section className="card">
        <p role="status">正在汇总同配置历史与 case 证据…</p>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="card badcase-empty">
        <h2>Badcase 对比不可用</h2>
        <p role="alert">{message || "报告不存在、尚未生成或原始证据未通过校验。"}</p>
        <button onClick={() => go("reports")}>返回报告管理</button>
      </section>
    );
  }

  const configBlock = (
    <>
      <div className="badcase-meta">
        <span>
          报告状态 <b>{data.report.validity}</b>
        </span>
        <span>
          证据 <b>{data.report.evidence_status}</b>
        </span>
        <span>
          有效历史 <b>{REVIEW_LABELS[reviewStatus] || reviewStatus}</b>
        </span>
        <span>
          算法 <b>Beta-Binomial T1</b>
        </span>
      </div>
      {data.datasets.map((item) => (
        <div className="badcase-config" key={item.dataset_key}>
          <b>{item.dataset_key}</b>
          <span>历史报告 {item.history.approved_reports} 份</span>
          <span>清单 {String(item.config.manifest_sha256 || "—").slice(0, 12)}</span>
          <span>工具 {String(item.config.tool_revision || "—").slice(0, 12)}</span>
          <span>
            output {String(item.config.output ?? "—")} · 并发{" "}
            {String(item.config.concurrency ?? "—")} · scope{" "}
            {String(item.config.scope ?? "—")}
          </span>
        </div>
      ))}
      {!data.datasets.length && <p className="muted">该报告没有可比较的数据集。</p>}
    </>
  );

  return (
    <div className="stack badcase-page" data-testid="badcase-comparison">
      {embedded ? (
        <div className="badcase-embedded-head">{configBlock}</div>
      ) : (
        <section className="card">
          <div className="spread">
            <div>
              <h2>Badcase 对比</h2>
              <p className="muted">
                任务 {data.run_id.slice(0, 8)} · 报告 {data.report_id.slice(0, 8)} ·{" "}
                {data.report.remote_model || "未知模型"} · {time(data.report.created_at)}
              </p>
            </div>
            <div className="inline">
              <button onClick={() => go(`report/${data.report_id}`)}>
                查看报告 <ArrowUpRight size={15} />
              </button>
              <a className="button" href={`#run/${data.run_id}`}>
                查看任务
              </a>
              <button
                onClick={toggleReview}
                disabled={
                  reviewing ||
                  data.report.validity !== "complete" ||
                  data.report.evidence_status !== "verified"
                }
              >
                {reviewStatus === "approved" ? "撤销有效历史" : "录入为有效历史"}
              </button>
            </div>
          </div>
          {configBlock}
        </section>
      )}

      <section className="badcase-summary" aria-label="可疑度汇总">
        <div>
          <span>Case 总数</span>
          <strong>{summary.total}</strong>
        </div>
        <div>
          <span>可疑度较高</span>
          <strong>{summary.high}</strong>
        </div>
        <div>
          <span>可疑度较低</span>
          <strong>{summary.low}</strong>
        </div>
        <div>
          <span>非 badcase</span>
          <strong>{summary.non_badcase - summary.missing}</strong>
        </div>
        <div>
          <span>缺测</span>
          <strong>{summary.missing}</strong>
        </div>
        <div>
          <span>有效历史报告</span>
          <strong>{summary.reports}</strong>
        </div>
      </section>

      <section className="card">
        <div className="badcase-toolbar">
          <label className="select-field">
            <span>数据集</span>
            <select value={dataset} onChange={(event) => setDataset(event.target.value)}>
              <option value="">全部数据集</option>
              {data.datasets.map((item) => (
                <option key={item.dataset_key}>{item.dataset_key}</option>
              ))}
            </select>
          </label>
          <label className="select-field">
            <span>可疑度</span>
            <select value={band} onChange={(event) => setBand(event.target.value)}>
              <option value="">全部</option>
              <option value="high">可疑度较高</option>
              <option value="low">可疑度较低</option>
              <option value="non_badcase">非 badcase</option>
            </select>
          </label>
          <label className="select-field">
            <span>得分</span>
            <select value={scoreFilter} onChange={(event) => setScoreFilter(event.target.value)}>
              <option value="">全部得分</option>
              <option value="zero">得分为 0</option>
            </select>
          </label>
          <input
            aria-label="搜索样本"
            placeholder="搜索 sample id"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <span className="muted">共 {filtered.length} 条</span>
          <div className="inline badcase-export-actions">
            <button onClick={() => download("high")} disabled={!summary.high || !!exporting}>
              <Download size={15} /> 导出高可疑 ({summary.high})
            </button>
            <button
              onClick={() => download("suspicious")}
              disabled={summary.high + summary.low === 0 || !!exporting}
            >
              <Download size={15} /> 导出全部可疑 ({summary.high + summary.low})
            </button>
            <button
              onClick={() => download("selected")}
              disabled={!selectedRows.length || !!exporting}
            >
              <Download size={15} /> 导出选中 ({selectedRows.length})
            </button>
            <button onClick={() => download("all")} disabled={!summary.total || !!exporting}>
              <Download size={15} /> 导出全部 Case ({summary.total})
            </button>
          </div>
        </div>
        {message && <p role="status">{message}</p>}
        {summary.reports === 0 && (
          <p className="notice">
            暂无同配置已审核历史。失败 case 仅按“失败即复盘”的降级口径标为低可疑，不能推断本不该失败。
            可先录入有效历史，或通过 API 测评建立同模型服务、同数据集、同清单、同工具版本、同参数的基准。
          </p>
        )}
        <div className="table-wrap">
          <table className="badcase-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="选择当前筛选的全部 case"
                    checked={allSelected}
                    onChange={toggleAll}
                  />
                </th>
                <th>数据集</th>
                <th>Case / 样本</th>
                <th>当前得分</th>
                <th>当前状态</th>
                <th>历史平均</th>
                <th>有效历史数</th>
                <th>得分差</th>
                <th>可疑度</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(({ dataset: item, row }) => {
                const tone = BANDS[row.verdict.band];
                const expandedRow = expanded === keyOf(item, row);
                return [
                  <tr key={keyOf(item, row)}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`选择 ${row.sample_id}`}
                        checked={selected.has(keyOf(item, row))}
                        onChange={() => toggle(item, row)}
                      />
                    </td>
                    <td>{item.dataset_key}</td>
                    <td>
                      <button className="link" onClick={() => setExpanded(expandedRow ? "" : keyOf(item, row))}>
                        {row.sample_id}
                      </button>
                      <small>
                        {row.current.missing ? "清单内缺测" : `第 ${row.current.attempt_no} 次`}
                      </small>
                    </td>
                    <td>{scoreText(row.current.score)}</td>
                    <td>
                      {row.current.missing ? (
                        <span className="badge neutral">缺测</span>
                      ) : (
                        <div className="badcase-statuses">
                          <span className={`case-status ${row.current.state === "succeeded" ? "passed" : "error"}`}>
                            {row.current.state}
                          </span>
                          {row.current.score_status === "missing" && (
                            <span className="badge orange">评分失败</span>
                          )}
                          {row.current.evidence_status === "unavailable" && (
                            <span className="badge orange">证据不可用</span>
                          )}
                        </div>
                      )}
                      {row.current.error_code && <small>{row.current.error_code}</small>}
                    </td>
                    <td>{numberText(row.history.mean)}</td>
                    <td>{row.history.n}</td>
                    <td>{row.delta === null ? "—" : `${row.delta > 0 ? "+" : ""}${row.delta}`}</td>
                    <td>
                      <span className={`badge ${tone.tone}`}>{tone.label}</span>
                      <small>{row.verdict.suspicion.toFixed(4)}</small>
                    </td>
                    <td>
                      <button
                        className="link"
                        onClick={() =>
                          download("selected", {
                            sampleIds: [row.sample_id],
                            datasetKey: item.dataset_key,
                          })
                        }
                        disabled={!!exporting}
                        title="导出该 case 的独立分析包"
                      >
                        导出
                      </button>
                    </td>
                  </tr>,
                  expandedRow ? (
                    <tr className="badcase-row-detail" key={`${keyOf(item, row)}-detail`}>
                      <td colSpan={10}>
                        <div className="badcase-verdict">
                          <span>p_hat <b>{numberText(row.verdict.p_hat)}</b></span>
                          <span>方法 <b>{row.verdict.method}</b></span>
                          <span>置信 <b>{row.verdict.confidence}</b></span>
                          <span>硬信号 <b>{row.verdict.hard_signals.join(", ") || "—"}</b></span>
                          <span>软信号 <b>{row.verdict.soft_signals.join(", ") || "—"}</b></span>
                        </div>
                        <p className="muted">{row.verdict.reasons.join("；")}</p>
                        {row.verdict.why_not_badcase && <p className="muted">{row.verdict.why_not_badcase}</p>}
                        {detailLoading && <p role="status">正在读取当前与历史推理内容…</p>}
                        {detailMessage && <p role="alert">{detailMessage}</p>}
                        {detail && (
                          <div className="badcase-answer-diff">
                            <div>
                              <h4>当前回答（本次）</h4>
                              <p className="muted">
                                得分 {scoreText(detail.current.score)} ·{" "}
                                {detail.current.missing ? "缺测" : detail.current.state} · 证据{" "}
                                {detail.current.evidence_status || "—"}
                              </p>
                              <pre>{detail.current.response || "推理内容未归档"}</pre>
                            </div>
                            <div>
                              <h4>历史正确回答</h4>
                              {detail.history
                                .filter((item) => item.score >= 1)
                                .map((item) => (
                                  <div key={item.report_id}>
                                    <p className="muted">
                                      得分 {item.score} · 报告 {item.report_id.slice(0, 8)} ·{" "}
                                      {time(item.created_at)}
                                    </p>
                                    <pre>{item.response || "推理内容未归档"}</pre>
                                  </div>
                                ))}
                              {!detail.history.some((item) => item.score >= 1) && (
                                <p className="muted">暂无历史正确回答。</p>
                              )}
                            </div>
                          </div>
                        )}
                        {!detail && !detailLoading && row.history.n === 0 && (
                          <div className="notice">
                            暂无同配置已审核历史，无法进行同口径差异对比。请先在报告中把历史执行录入为有效历史；
                            或通过 API 测评创建基准，基准的模型服务、数据集、清单、工具版本和执行参数必须与当前完全一致。
                            <a className="primary button" href="#console">前往新建测评</a>
                          </div>
                        )}
                        <div className="table-wrap">
                          <table>
                            <thead>
                              <tr><th>历史报告</th><th>任务</th><th>得分</th><th>时间</th></tr>
                            </thead>
                            <tbody>
                              {row.history.scores.map((score) => (
                                <tr key={`${score.report_id}-${score.run_id}`}>
                                  <td>
                                    <button className="link" onClick={() => go(`report/${score.report_id}`)}>
                                      {score.report_id.slice(0, 8)}
                                    </button>
                                  </td>
                                  <td>{score.run_id.slice(0, 8)}</td>
                                  <td>{scoreText(score.score)}</td>
                                  <td>{time(score.created_at)}</td>
                                </tr>
                              ))}
                              {!row.history.scores.length && (
                                <tr><td colSpan={4} className="muted">暂无同配置历史得分。</td></tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
          {!filtered.length && <div className="empty">没有符合筛选条件的 case。</div>}
        </div>
      </section>
    </div>
  );
}
