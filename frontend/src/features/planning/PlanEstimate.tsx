import { useEffect, useState } from "react";

export type Report = {
  input_sha256: string; conditional: boolean; confidence: string; warnings: string[];
  representative_duration_sec: number;
  estimate: { total_duration_sec: number; range: { p10_sec: number; p90_sec: number } };
  plan: { dataset_order: string[]; dataset_concurrency: number; case_concurrency: Record<string, number> };
  planner_revision?: string; throughput_source?: { measured_at?: string; type?: string };
  tasks: { task_id: string; standalone_duration_sec: number; scheduled_duration_sec: number; scheduled_start_sec: number; scheduled_end_sec: number }[];
};

export const duration = (seconds: number | null | undefined) => {
  if (seconds == null) return "未知";
  const total = Math.max(0, Math.round(seconds));
  return [total >= 3600 ? `${Math.floor(total / 3600)}小时` : "", total >= 60 ? `${Math.floor(total % 3600 / 60)}分` : "", `${total % 60}秒`].filter(Boolean).join(" ");
};

export function EstimateElapsed() {
  const [start] = useState(Date.now);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  return <span className="estimate-elapsed" aria-label="估算已耗时">已耗时 {duration((now - start) / 1000)}</span>;
}

export function PlanEstimate({ report }: { report: Report }) {
  const confidence = ({ high: "高", medium: "中", low: "低" } as Record<string, string>)[report.confidence] || report.confidence;
  return <section className="estimate-detail" aria-label="耗时估算与参数建议">
    <div className="estimate-result"><small>预计总耗时</small><strong>{duration(report.estimate.total_duration_sec)}</strong><span>预测区间（P10–P90）<br />{duration(report.estimate.range.p10_sec)} – {duration(report.estimate.range.p90_sec)}</span><span>置信度：{confidence}</span></div>
    <p className="estimate-note">不含平台排队及报告分析耗时。{report.conditional && "当前为条件估算，需执行资源预检后重新估算。"}</p>
    <div className="estimate-datasets">{report.tasks.map(t => <article className="estimate-dataset" key={t.task_id}><header><strong>{t.task_id}</strong><span>样本并发 {report.plan.case_concurrency[t.task_id]}</span></header><dl><div><dt>单独执行</dt><dd>{duration(t.standalone_duration_sec)}</dd></div><div><dt>计划内耗时</dt><dd>{duration(t.scheduled_duration_sec)}</dd></div><div><dt>开始 → 结束</dt><dd>{duration(t.scheduled_start_sec)} → {duration(t.scheduled_end_sec)}</dd></div></dl></article>)}</div>
    <p className="estimate-note">执行顺序：{report.plan.dataset_order.join(" → ")} · 同时运行 {report.plan.dataset_concurrency} 个数据集。并行共享吞吐与资源，各项时长不能直接相加。</p>
    <details className="estimate-source"><summary>估算来源与限制</summary><dl><div><dt>组件版本</dt><dd>{report.planner_revision || "未记录"}</dd></div><div><dt>吞吐依据</dt><dd>{report.throughput_source?.type === "probe" ? "真实吞吐探测" : report.throughput_source?.type || "未记录"}</dd></div><div><dt>采集时间</dt><dd>{report.throughput_source?.measured_at ? new Date(report.throughput_source.measured_at).toLocaleString("zh-CN") : "未记录"}</dd></div></dl><p>代表性仿真终点：{duration(report.representative_duration_sec)}</p></details>
    {report.warnings?.map((w, i) => <small className="estimate-note" key={i}>{w}</small>)}
  </section>;
}
