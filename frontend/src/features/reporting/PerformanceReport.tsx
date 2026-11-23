import type { Report } from "./ReportView";

type Measurement = {
  concurrency?: number;
  status?: string;
  parse_status: string;
  comparison_scope?: string;
  benchmark_valid?: boolean;
  invalid_reasons?: string[];
  missing_artifacts?: string[];
  metrics: [string, string, number, string][];
  csv_preview: string[][];
  csv_path?: string;
};

export type NativePerformance = Measurement & {
  config: Record<string, string | number | number[]>;
  execution?: Record<string, string | number>;
  levels?: Measurement[];
  via_budget_gateway?: boolean;
  tool_exit_code?: number;
  files: { path: string; sha256: string; size: number }[];
};

const labels: Record<string, string> = {
  kind: "负载", input_tokens: "目标输入（token）", max_output_tokens: "最大输出（token）",
  requests: "请求数", concurrency: "并发数", variant: "Weka 语料", run_mode: "运行模式",
  duration: "每档运行时长（秒）", trace_limit: "Trace 数量上限", resource_id: "SSH 节点",
  aisbench_revision: "AISBench 提交", adapter_sha256: "适配器 SHA-256", image_id: "执行镜像",
  context_tokens: "登记上下文（token）", tokenizer_path: "Tokenizer 挂载",
};

function Measurements({ result, name }: { result: Measurement; name: string }) {
  return <section className="card stack"><h2>{name}</h2>
    <p>结果解析 · {result.parse_status}{result.comparison_scope && `　可比范围 · ${result.comparison_scope}`}</p>
    {result.benchmark_valid != null && <p>正式结果有效性 · {result.benchmark_valid ? "有效" : "未满足正式条件"}</p>}
    {!!result.invalid_reasons?.length && <p>{result.invalid_reasons.join(" · ")}</p>}
    {!!result.missing_artifacts?.length && <p>缺少原生产物 · {result.missing_artifacts.join("、")}</p>}
    {result.metrics.length ? <div className="table-wrap"><table>
      <thead><tr><th>指标</th><th>统计口径 / 阶段</th><th>实测值</th><th>单位</th></tr></thead>
      <tbody>{result.metrics.map(([metric, stat, value, unit], index) =>
        <tr key={index}><td>{metric}</td><td>{stat}</td><td>{value}</td><td>{unit || "—"}</td></tr>)}</tbody>
    </table></div> : <p>未采集到可解析的性能指标</p>}
    {result.csv_preview.length > 0 && <div className="table-wrap"><table>
      <caption>原生 CSV 预览（最多 50 行）</caption>
      <thead><tr>{result.csv_preview[0].map((cell, col) => <th key={col}>{cell}</th>)}</tr></thead>
      <tbody>{result.csv_preview.slice(1).map((row, index) =>
        <tr key={index}>{row.map((cell, col) => <td key={col}>{cell}</td>)}</tr>)}</tbody>
    </table></div>}
  </section>;
}

export function PerformanceReport({ report, back }: { report: Report; back: () => void }) {
  const result = report.summary.performance;
  const verified = report.evidence_status === "verified";
  const agentx = result?.config?.kind === "agentx";
  return <div className="stack report-workspace">
    <div><button className="link back" onClick={back}>返回报告列表</button></div>
    <section className="card stack">
      <h2>{agentx ? "AgentX 轨迹回放" : "普通推理"}性能报告</h2>
      <p>{report.remote_model} · <a href={`#run/${report.run_id}`}>查看测评任务</a></p>
      <dl className="summary-grid">{Object.entries(result?.config ?? {}).map(([key, value]) =>
        <div key={key}><dt>{labels[key] || key}</dt><dd>{Array.isArray(value) ? value.join("、") : value === "inference" ? "普通推理" : value}</dd></div>)}</dl>
      {verified && result && !agentx && <dl className="summary-grid">
        {(["InputTokens", "OutputTokens"] as const).map((name, index) => <div key={name}>
          <dt>实测平均{index === 0 ? "输入" : "输出"}（token）</dt>
          <dd>{result.metrics.find(metric => metric[0] === name && metric[1] === "total / Average")?.[2] ?? "未采集"}</dd>
        </div>)}
      </dl>}
      {result?.execution && <details><summary>冻结的执行环境</summary><dl>
        {Object.entries(result.execution).map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{value}</dd></div>)}
      </dl></details>}
      <p>执行结果 · {report.validity === "complete" ? "完整" : "部分或失败"}
        {typeof result?.tool_exit_code === "number" && `　工具退出码 · ${result.tool_exit_code}`}</p>
      {result?.via_budget_gateway && <p>请求经平台预算网关转发</p>}
    </section>
    {!verified || !result ? <p role="status">原生性能证据不可用</p> : <>
      {(result.levels ?? [result]).map(level =>
        <Measurements key={level.concurrency ?? "single"} result={level}
          name={level.concurrency ? `会话并发 ${level.concurrency} · 原生性能指标` : "原生性能指标"} />)}
      <section className="card stack"><h2>原生 CSV 下载</h2>
        {result.files.filter(file => file.path.endsWith(".csv")).map(file =>
          <a key={file.path} download href={`/api/autoeval/v1/reports/${report.id}/performance-csv?path=${encodeURIComponent(file.path)}`}>下载 {file.path}</a>)}
      </section>
    </>}
  </div>;
}
