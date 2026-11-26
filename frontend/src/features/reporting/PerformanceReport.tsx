import { useState } from "react";
import { Activity, ArrowLeft, ArrowUpRight, CheckCircle2, Clock3, Download, FileSpreadsheet, Search, SlidersHorizontal } from "lucide-react";
import "./PerformanceReport.css";
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

const scopeLabels: Record<string, string> = {
  smoke: "链路验证", internal_only: "内部对比", official_agentx: "官方口径", invalid: "不可比较",
};

function Measurements({ result: measurement, agentx }: { result: Measurement; agentx: boolean }) {
  const result = { ...measurement, metrics: measurement.metrics ?? [], csv_preview: measurement.csv_preview ?? [] };
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"metrics" | "csv">("metrics");
  const highlights = agentx ? [
    ["首 token 延迟 · P90", "time_to_first_token", "p90"],
    ["请求吞吐", "request_throughput", "avg"],
    ["请求数", "request_count", "avg"],
    ["请求延迟 · P90", "request_latency", "p90"],
  ] : [
    ["首 token 延迟 · P90", "TTFT", "total / P90"],
    ["请求吞吐", "Request Throughput", "total"],
    ["实测平均输入", "InputTokens", "total / Average"],
    ["实测平均输出", "OutputTokens", "total / Average"],
  ];
  const search = query.trim().toLowerCase();
  const matches = result.metrics.filter(([metric, stat]) => (metric + " " + stat).toLowerCase().includes(search));
  const parsed = result.parse_status === "success";
  return <section className="card perf-section">
    <header className="perf-heading"><h2>{result.concurrency ? `会话并发 ${result.concurrency} · 性能指标` : "性能指标"}</h2>
      <span className="perf-caption">解析{parsed ? "成功" : `状态 · ${result.parse_status}`}</span></header>
    <div className="perf-context">
      {result.comparison_scope && <span className="perf-chip">可比范围 · {result.comparison_scope}{scopeLabels[result.comparison_scope] && `（${scopeLabels[result.comparison_scope]}）`}</span>}
      {result.benchmark_valid != null && <span>{result.benchmark_valid ? "符合正式测评条件" : "未满足正式测评条件"}</span>}
      {result.invalid_reasons?.map(reason => <span key={reason}>{reason === "run_mode_not_benchmark" ? "本次使用 smoke 模式" : reason}</span>)}
    </div>
    {!!result.missing_artifacts?.length && <p className="notice">缺少原生产物 · {result.missing_artifacts.join("、")}</p>}
    {result.metrics.length > 0 && <dl className="perf-kpis">
      {highlights.map(([label, metric, stat]) => {
        const row = result.metrics.find(([name, scope]) => name === metric && scope === stat);
        return <div key={metric}><dt>{label}</dt><dd>{row
          ? <><strong title={String(row[2])}>{row[2].toLocaleString("zh-CN", {maximumSignificantDigits: 6})}</strong><small>{row[3]}</small></>
          : <span className="perf-caption">未采集</span>}</dd></div>;
      })}
    </dl>}
    <div className="perf-tools">
      <div className="perf-switch" role="group" aria-label="指标视图">
        <button aria-pressed={view === "metrics"} onClick={() => setView("metrics")}>指标明细 <span>{result.metrics.length}</span></button>
        {result.csv_preview.length > 0 && <button aria-pressed={view === "csv"} onClick={() => setView("csv")}>CSV 预览</button>}
      </div>
      {view === "metrics" && result.metrics.length > 0 && <label className="perf-search"><Search size={15} aria-hidden="true" />
        <input aria-label="筛选指标或统计口径" placeholder="搜索指标或统计口径" value={query} onChange={e => setQuery(e.target.value)} /></label>}
    </div>
    {view === "csv" ? <div className="perf-scroll" tabIndex={0} aria-label="原生 CSV 预览"><table>
      <caption>原生 CSV 预览（最多 50 行）</caption>
      <thead><tr>{result.csv_preview[0].map((cell, i) => <th key={i}>{cell}</th>)}</tr></thead>
      <tbody>{result.csv_preview.slice(1).map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
    </table></div> : matches.length ? <div className="perf-scroll" tabIndex={0} aria-label="原生指标明细"><table>
      <thead><tr><th>指标</th><th>统计口径 / 阶段</th><th className="perf-number">实测值</th><th>单位</th></tr></thead>
      <tbody>{matches.map(([name, stat, value, unit], i) => <tr key={i}><td>{name}</td><td>{stat}</td><td className="perf-number">{value}</td><td>{unit || "—"}</td></tr>)}</tbody>
    </table></div> : <p className="perf-empty">{result.metrics.length ? "没有匹配的指标" : "未采集到可解析的性能指标"}</p>}
  </section>;
}

export function PerformanceReport({ report, back }: { report: Report; back: () => void }) {
  const result = report.summary.performance;
  const verified = report.evidence_status === "verified";
  const agentx = result?.config?.kind === "agentx";
  const files = result?.files?.filter(f => f.path.toLowerCase().endsWith(".csv")) ?? [];
  return <div className="perf-report">
    <button className="link perf-back" onClick={back}><ArrowLeft size={15} />返回报告列表</button>
    <section className="card perf-section perf-overview">
      <header className="perf-heading"><div className="perf-title"><span className="perf-icon"><Activity size={22} /></span><div>
        <h2>{agentx ? "AgentX 轨迹回放" : result?.config?.kind === "inference" ? "普通推理" : ""}性能报告</h2>
        <div className="perf-meta"><b>{report.remote_model}</b><span><Clock3 size={13} />{new Date(report.created_at).toLocaleString("zh-CN", {hour12: false})}</span></div>
      </div></div>
      <a className="perf-task" href={`#run/${report.run_id}`}>查看测评任务 <ArrowUpRight size={15} /></a></header>
      <div className="perf-status">
        <span className={report.validity === "complete" ? "perf-chip good" : "perf-chip"}>{report.validity === "complete" ? "执行完整" : "执行部分完成或失败"}</span>
        {verified && <span><CheckCircle2 size={14} />证据已核验</span>}
        {typeof result?.tool_exit_code === "number" && <span>工具退出码 {result.tool_exit_code}</span>}
        {result?.via_budget_gateway && <span>经预算网关转发</span>}
      </div>
      {result?.config && <dl className="perf-config">{Object.entries(result.config).map(([key, value]) =>
        <div key={key}><dt>{labels[key] || key}</dt><dd>{Array.isArray(value) ? value.join("、") : key === "kind" ? (agentx ? "轨迹回放" : "普通推理") : value}</dd></div>)}</dl>}
      {result?.execution && <details className="perf-env"><summary><SlidersHorizontal size={14} />冻结的执行环境</summary><dl className="perf-env-grid">
        {Object.entries(result.execution).map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{value}</dd></div>)}</dl></details>}
    </section>
    {!verified || !result ? <p role="status" className="card">原生性能证据不可用</p> : <>
      {(result.levels ?? [result]).map(level => <Measurements key={level.concurrency ?? "single"} result={level} agentx={agentx} />)}
      {files.length > 0 && <section className="card perf-section"><header className="perf-heading"><h2>原生 CSV 下载</h2><span className="perf-caption">{files.length} 个文件</span></header>
        <div className="perf-files">{files.map(file => <a key={file.path} download aria-label={`下载 ${file.path}`} href={`/api/autoeval/v1/reports/${report.id}/performance-csv?path=${encodeURIComponent(file.path)}`}>
          <FileSpreadsheet size={20} /><span><b>{file.path.split("/").pop()}</b><small>{file.path}</small></span><Download size={16} /></a>)}</div>
      </section>}
    </>}
  </div>;
}
