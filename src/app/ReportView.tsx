import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
export const reportDatasets = [
  {
    name: "GPQA",
    type: "科学问答",
    status: "完整",
    metric: "准确率",
    value: 72.4,
    baseline: 68.1,
    performance: true,
  },
  {
    name: "MMLU",
    type: "科学问答",
    status: "完整",
    metric: "准确率",
    value: 76.2,
    baseline: 74.8,
    performance: false,
  },
  {
    name: "GSM8K",
    type: "科学问答",
    status: "完整",
    metric: "准确率",
    value: 81.6,
    baseline: null,
    performance: true,
  },
  {
    name: "MMMU-Pro",
    type: "多模态",
    status: "部分",
    metric: "准确率",
    value: 61.8,
    baseline: 58.9,
    performance: false,
  },
  {
    name: "OCRBench",
    type: "多模态",
    status: "完整",
    metric: "得分",
    value: 78.2,
    baseline: 76.4,
    performance: false,
  },
  {
    name: "AutomationBench",
    type: "Agent 工作流",
    status: "完整",
    metric: "任务成功率",
    value: 48,
    baseline: 41.6,
    performance: false,
  },
  {
    name: "工具调用验证集",
    type: "Agent 工作流",
    status: "完整",
    metric: "任务成功率",
    value: 64,
    baseline: 61,
    performance: true,
  },
  {
    name: "工作流回归集",
    type: "Agent 工作流",
    status: "失败",
    metric: "任务成功率",
    value: null,
    baseline: null,
    performance: false,
  },
];
type Evidence = { title: string; text: string };
export function ReportView({
  id,
  model,
  modelId,
  version,
  analysis,
  go,
  notify,
}: {
  id: string;
  model: string;
  modelId: string;
  version: string;
  analysis: string;
  go: (p: string, id?: string) => void;
  notify: (s: string) => void;
}) {
  const [selected, setSelected] = useState("GPQA");
  const [tab, setTab] = useState("结果分析");
  const [detailOpen, setDetailOpen] = useState(false);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [sampleFilter, setSampleFilter] = useState("全部判分");
  const [sampleQuery, setSampleQuery] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!evidence) return;
    const prior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEvidence(null);
    };
    document.addEventListener("keydown", close);
    return () => {
      document.body.style.overflow = prior;
      document.removeEventListener("keydown", close);
    };
  }, [evidence]);
  const d = reportDatasets.find((d) => d.name === selected)!;
  const agent = d.type === "Agent 工作流";
  const failed = d.status === "失败";
  const partial = d.status === "部分";
  const select = (name: string) => {
    setDetailOpen(true);
    setSelected(name);
    setTab("结果分析");
    setSampleFilter("全部判分");
    setSampleQuery("");
    setPage(1);
  };
  const delta = (
    value: number | null,
    baseline: number | null,
    partial = false,
  ) =>
    value === null
      ? "—"
      : partial
        ? "不可直接比较"
        : baseline === null
          ? "暂无基准"
          : `${value - baseline >= 0 ? "+" : ""}${(value - baseline).toFixed(1)} ${d.metric === "得分" ? "分" : "pct"}`;
  const samples = failed
    ? []
    : Array.from({ length: partial ? 80 : 100 }, (_, i) => ({
        id: `${d.name}-#${String(i + 1).padStart(3, "0")}`,
        result: i % 5 === 0 ? "未通过" : "通过",
        reason:
          i % 5 === 0
            ? agent
              ? "工具参数缺失，断言未通过"
              : "作答与标准答案不一致"
            : "符合判分条件",
      }));
  const sampleRows = samples.filter(
    (s) =>
      (sampleFilter === "全部判分" || s.result === sampleFilter) &&
      (s.id + " " + s.reason).toLowerCase().includes(sampleQuery.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(sampleRows.length / 5));
  const current = Math.min(page, pages);
  return (
    <div className="stack report-workspace">
      <div className="report-navigation-bar">
        <nav aria-label="报告返回导航" className="report-return-links">
          <button className="link" onClick={() => go("reports")}>
            返回报告列表
          </button>
          {detailOpen && (
            <>
              <span aria-hidden="true" className="report-return-divider" />
              <button className="link" onClick={() => setDetailOpen(false)}>
                返回报告总览
              </button>
            </>
          )}
        </nav>
        {detailOpen && (
          <label>
            切换数据集
            <select
              aria-label="切换报告数据集"
              value={selected}
              onChange={(e) => select(e.target.value)}
            >
              {reportDatasets.map((x) => (
                <option key={x.name}>{x.name}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {!detailOpen && (
        <section className="card">
          <div className="spread">
            <h2>
              报告总览 <span className="badge">{id}</span>
            </h2>
            <span className="badge">静态扩展示例 · 8 个数据集</span>
          </div>
          <div className="execution-meta">
            <span>
              模型 <b>{model}</b>
            </span>
            <span>
              modelId <b>{modelId}</b>
            </span>
            <span>
              配置 <b>v1.3 · {version}</b>
            </span>
            <span>
              运行方式 <b>串行</b>
            </span>
            <span>
              测评时间 <b>2026-11-09 14:00</b>
            </span>
          </div>
          <div className="report-summary-stats">
            {[
              ["数据集", 8],
              ["完整完成", 6],
              ["部分完成", 1],
              ["执行失败", 1],
              ["总耗时", "42 分钟"],
              ["分析状态", analysis],
            ].map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <details open className="report-analysis-summary">
            <summary>
              关键结论 <span className="badge">{analysis}</span>
            </summary>
            {analysis === "分析成功" ? (
              <p>
                科学问答结果较稳定；多模态结果存在覆盖不完整情况，不能直接与完整基准比较。Agent
                任务需优先检查工具参数与环境异常。以下归因为示例推断，证据见对应数据集。
              </p>
            ) : (
              <p>
                {analysis === "分析失败"
                  ? "分析服务请求超时（示例），原始结果仍可查看。"
                  : "分析进行中，原始结果仍可查看。"}
              </p>
            )}
          </details>
          <h3 className="report-result-heading">数据集结果</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {[
                    "数据集",
                    "类型",
                    "覆盖",
                    "核心指标",
                    "指标值（示例）",
                    "基准差异",
                    "操作",
                  ].map((t) => (
                    <th key={t}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reportDatasets.map((x) => (
                  <tr key={x.name}>
                    <td>{x.name}</td>
                    <td>{x.type}</td>
                    <td>
                      <span
                        className={`coverage ${x.status === "完整" ? "complete" : x.status === "部分" ? "partial" : "error"}`}
                      >
                        {x.status === "完整"
                          ? "100/100"
                          : x.status === "部分"
                            ? "80/100"
                            : "0/100"}{" "}
                        · {x.status}
                      </span>
                    </td>
                    <td>{x.metric}</td>
                    <td>
                      {x.value === null
                        ? "—"
                        : `${x.value}${x.metric === "得分" ? " 分" : "%"}`}
                    </td>
                    <td>
                      {x.status === "部分"
                        ? "不可直接比较"
                        : x.value === null
                          ? "—"
                          : x.baseline === null
                            ? "暂无基准"
                            : `${(x.value - x.baseline).toFixed(1)} ${x.metric === "得分" ? "分" : "pct"}`}
                    </td>
                    <td>
                      <button className="link" onClick={() => select(x.name)}>
                        查看结果
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            各数据集按自身指标展示，不计算跨数据集综合分。所有数值为静态样例。
          </p>
        </section>
      )}
      {detailOpen && (
        <div className="report-detail-view">
          <section className="card stack report-dataset-result">
            <div className="spread">
              <div>
                <h2>{d.name}</h2>
                <p className="muted">
                  {d.type} · 全量 · 有效样本{" "}
                  {failed ? "0" : partial ? "80" : "100"} / 100 · 配置 v1.3
                </p>
              </div>
              <span
                className={`coverage ${failed ? "error" : partial ? "partial" : "complete"}`}
              >
                {d.status}
              </span>
            </div>
            {partial && (
              <div className="notice">
                20
                个样本未取得有效结果。当前指标仅覆盖有效样本，与完整基准不可直接比较。
              </div>
            )}
            {failed ? (
              <>
                <div className="notice">
                  执行失败：运行环境初始化失败（静态示例）。无有效结果，不展示指标或差异。
                </div>
                <button
                  className="link back"
                  onClick={() =>
                    setEvidence({
                      title: `${d.name} 执行异常`,
                      text: "[示例日志] 环境初始化失败，未开始采样。\n有效样本：0 / 100\n本报告保留失败摘要，不以零分代替缺失结果。",
                    })
                  }
                >
                  查看失败日志
                </button>
              </>
            ) : (
              <>
                <div className="tabs">
                  {[
                    "结果分析",
                    ...(d.performance ? ["性能结果"] : []),
                    "样本明细",
                  ].map((t) => (
                    <button
                      className={tab === t ? "active" : ""}
                      key={t}
                      onClick={() => setTab(t)}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                {tab === "结果分析" ? (
                  <>
                    <div className="report-quality-metrics">
                      <div>
                        <span>{d.metric}</span>
                        <strong>
                          {d.value}
                          {d.metric === "得分" ? " 分" : "%"}
                        </strong>
                      </div>
                      {agent && (
                        <div>
                          <span>断言通过比例（示例）</span>
                          <strong>72.0%</strong>
                        </div>
                      )}
                      <div>
                        <span>有效样本</span>
                        <strong>
                          {partial ? 80 : 100}
                          <small> / 100</small>
                        </strong>
                      </div>
                    </div>
                    <h3>{agent ? "分领域任务表现" : "分项结果"}</h3>
                    <div className="report-breakdown">
                      {(agent
                        ? ["数据处理", "协作办公", "业务工作流"]
                        : d.type === "多模态"
                          ? ["图像理解", "图表推理", "文字识别"]
                          : ["知识理解", "逻辑推理", "综合应用"]
                      ).map((label, i) => {
                        const value = Math.max(
                          0,
                          (d.value || 0) + [5, -4, -1][i],
                        );
                        return (
                          <div key={label}>
                            <span>{label}</span>
                            <progress max="100" value={value} />
                            <b>
                              {value.toFixed(1)}
                              {d.metric === "得分" ? " 分" : "%"}
                            </b>
                          </div>
                        );
                      })}
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            {[
                              "指标",
                              "实测值（示例）",
                              "基准值（示例）",
                              "差异",
                              "比较条件",
                            ].map((h) => (
                              <th key={h}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>{d.metric}</td>
                            <td>
                              {d.value}
                              {d.metric === "得分" ? " 分" : "%"}
                            </td>
                            <td>
                              {d.baseline === null
                                ? "暂无基准"
                                : `${d.baseline}${d.metric === "得分" ? " 分" : "%"}`}
                            </td>
                            <td>{delta(d.value, d.baseline, partial)}</td>
                            <td>
                              {partial
                                ? "覆盖不一致"
                                : "同数据集 / 子集 / 配置（示例）"}
                            </td>
                          </tr>
                          {agent && (
                            <tr>
                              <td>断言通过比例</td>
                              <td>72.0%</td>
                              <td>暂无基准</td>
                              <td>—</td>
                              <td>公开任务集 · 示例</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : tab === "性能结果" ? (
                  <>
                    <div className="notice">
                      以下仅为该数据集的性能界面样例，不表示已接入真实采集。并发
                      60 / 输入 2048 / 输出 2048。
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            {[
                              "指标",
                              "示例值",
                              "统计口径",
                              "基准值",
                              "差异",
                            ].map((h) => (
                              <th key={h}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {[
                            [
                              "输出吞吐",
                              "126 tok/s",
                              "总输出 Token / 执行耗时",
                            ],
                            ["首 Token 延迟", "182 ms", "P50"],
                            ["端到端延迟", "1240 ms", "P50"],
                          ].map((row) => (
                            <tr key={row[0]}>
                              {row.map((c) => (
                                <td key={c}>{c}</td>
                              ))}
                              <td>暂无基准</td>
                              <td>—</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : null}
                {tab === "样本明细" && (
                  <>
                    <h3>{agent ? "任务与工具调用明细" : "样本明细"}</h3>
                    <div className="filters">
                      <select
                        aria-label="报告样本判分筛选"
                        value={sampleFilter}
                        onChange={(e) => {
                          setSampleFilter(e.target.value);
                          setPage(1);
                        }}
                      >
                        {["全部判分", "通过", "未通过"].map((s) => (
                          <option key={s}>{s}</option>
                        ))}
                      </select>
                      <input
                        aria-label="搜索报告样本"
                        placeholder="搜索样本 ID / 失败原因"
                        value={sampleQuery}
                        onChange={(e) => {
                          setSampleQuery(e.target.value);
                          setPage(1);
                        }}
                      />
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>样本 / 任务</th>
                            <th>判分</th>
                            <th>说明</th>
                            <th>证据</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sampleRows
                            .slice((current - 1) * 5, current * 5)
                            .map((s) => (
                              <tr key={s.id}>
                                <td>{s.id}</td>
                                <td>{s.result}</td>
                                <td>{s.reason}</td>
                                <td>
                                  <button
                                    className="link"
                                    onClick={() =>
                                      setEvidence({
                                        title: s.id,
                                        text: `数据集：${d.name}\n输入：示例任务内容（未接入真实样本）\n模型响应：示例响应\n判分：${s.result}\n说明：${s.reason}${agent ? "\n工具调用：create_task\n断言：检查 title 必填字段" : ""}\n所有证据仅供界面展示。`,
                                      })
                                    }
                                  >
                                    查看
                                  </button>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                      {!sampleRows.length && (
                        <div className="empty">暂无匹配样本</div>
                      )}
                    </div>
                    <div className="pagination">
                      <span>
                        共 {sampleRows.length} 条 · 第 {current} / {pages} 页
                      </span>
                      <button
                        disabled={current === 1}
                        onClick={() => setPage(current - 1)}
                      >
                        上一页
                      </button>
                      <button
                        disabled={current === pages}
                        onClick={() => setPage(current + 1)}
                      >
                        下一页
                      </button>
                    </div>
                  </>
                )}
              </>
            )}
            {(tab === "结果分析" || failed) && (
              <section className="report-local-analysis">
                <div className="spread">
                  <h3>本数据集自动分析</h3>
                  <span className="badge">{analysis}</span>
                </div>
                {analysis === "分析成功" ? (
                  <>
                    <p>
                      {failed
                        ? "事实：没有有效结果。建议先排查执行环境，暂不进行能力归因。"
                        : partial
                          ? "事实：结果覆盖不完整。推断：当前分数可能受样本分布影响，补齐后再比较。"
                          : agent
                            ? "事实：部分任务未通过断言。推断：工具参数构造可能是主要影响因素，需结合失败样本验证。"
                            : "事实：已完成有效样本测评。建议优先检查未通过样本；当前展示为示例分析。"}
                    </p>
                    <button
                      className="link"
                      onClick={() =>
                        setEvidence({
                          title: `${d.name} 分析证据`,
                          text: "证据来源：当前数据集样本与执行日志。\n本内容为静态示例，不代表真实 Agent 分析。",
                        })
                      }
                    >
                      查看本数据集证据
                    </button>
                  </>
                ) : (
                  <>
                    <p>
                      {analysis === "分析失败"
                        ? "分析失败，原始结果已保留。"
                        : "分析中，完成后在此展示该数据集结论与证据。"}
                    </p>
                    {analysis === "分析失败" && (
                      <button
                        onClick={() => notify("静态示例：未调用分析服务。")}
                      >
                        重试分析
                      </button>
                    )}
                  </>
                )}
              </section>
            )}
          </section>
        </div>
      )}
      {evidence &&
        createPortal(
          <div
            className="case-drawer-backdrop"
            onClick={() => setEvidence(null)}
          >
            <section
              className="case-drawer"
              role="dialog"
              aria-modal="true"
              aria-label="报告证据详情"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="spread">
                <h2>{evidence.title}</h2>
                <button autoFocus onClick={() => setEvidence(null)}>
                  关闭
                </button>
              </div>
              <pre className="snapshot">{evidence.text}</pre>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
