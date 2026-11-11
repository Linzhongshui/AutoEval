import { Activity, BarChart3, Info } from "lucide-react";
import type { Report } from "../app/ReportView";

const percent = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;

export type DatasetChartResult = {
  dataset_key: string;
  display_name?: string;
  summary: Report["summary"];
  validity: string;
  evidence_status: string;
  baseline_comparison: Report["baseline_comparison"];
};

export function ReportCharts({ report }: { report: Report }) {
  const datasets = report.dataset_results ?? [{ dataset_key: "GPQA", summary: report.summary, validity: report.validity, evidence_status: report.evidence_status, baseline_comparison: report.baseline_comparison }];
  return <section className="report-charts" aria-label="报告全部数据集图表">
    <section className="report-chart-panel">
      <header className="spread"><h3><BarChart3 size={18} />精度测评</h3><span className="badge">{datasets.length} 个数据集</span></header>
      <p className="muted">各数据集准确率 · 越高越好 · 不计算综合分</p>
      <div className="chart-legend"><span><i className="chart-swatch measured" />本次测评</span><span><i className="chart-swatch reference" />基线</span></div>
      <figure className="accuracy-comparison" aria-label="多数据集准确率与基线分组对比图">
        <div className="chart-ticks" aria-hidden="true"><span>0%</span><span>25%</span><span>50%</span><span>75%</span><span>100%</span></div>
        {datasets.map((dataset) => {
          const baseline = dataset.baseline_comparison;
          const measured = report.evidence_status === "verified" && dataset.evidence_status === "verified" && ["complete", "partial"].includes(dataset.validity) && dataset.summary.scoring_status === "succeeded" && percent(dataset.summary.accuracy) ? dataset.summary.accuracy : null;
          const reference = measured !== null && dataset.validity === "complete" && baseline.status === "matched" && baseline.baseline_unit === "percent" && baseline.measured_value === measured && percent(baseline.baseline_value) ? baseline.baseline_value : null;
          return <div className="dataset-chart-group" key={dataset.dataset_key}>
            <div className="spread"><b>{dataset.display_name || dataset.dataset_key}</b><small>{dataset.summary.subset_scope}</small></div>
            {([["本次测评", measured, "measured"], ["基线", reference, "reference"]] as const).map(([label, value, tone]) => <div className="chart-row" key={label}><span>{label}</span><div className="chart-track">{value !== null && <div className={`chart-bar ${tone}`} style={{width: `${value}%`}} role="meter" aria-label={`${dataset.display_name || dataset.dataset_key} ${label}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} />}</div><strong>{value === null ? "—" : `${value.toFixed(2)}%`}</strong></div>)}
            <p className="chart-baseline-version">{measured !== null && reference !== null ? `较基线 ${measured-reference > 0 ? "+" : ""}${(measured-reference).toFixed(2)} 个百分点` : measured === null ? "暂无可核验准确率" : "暂无可比基线"} · 基线版本：{baseline.baseline_key ? `${baseline.baseline_key} / ${baseline.baseline_version || "未提供"}` : "未配置"}</p>
          </div>;
        })}
        {!datasets.length && <p className="empty">暂无数据集结果</p>}
        <figcaption>各数据集独立比较；缺失值不填零，部分覆盖不与完整基线比较。</figcaption>
      </figure>
    </section>
    <section className="report-chart-panel"><header className="spread"><h3><Activity size={18} />性能测评</h3><span className="badge neutral">未接入</span></header><p className="muted">同一指标下按数据集分组比较本次测评与基线</p><div className="performance-chart-empty" role="status"><Activity size={30} /><strong>暂无性能测评数据</strong><p>当前报告未采集吞吐量或延迟，无法绘制多数据集性能对比。</p></div><p className="chart-explanation"><Info size={14} />不同单位的性能指标分别展示，不混用量纲或填充示例值。</p></section>
  </section>;
}
