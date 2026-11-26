import { Activity, BarChart3 } from "lucide-react";
import type { Report } from "./ReportView";

const percent = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;

const formatDelta = (value: number, baseline: number) => (value > baseline ? '+' : '') + (value - baseline).toFixed(2);

export type DatasetChartResult = {
  dataset_key: string;
  display_name?: string;
  summary: Report["summary"];
  validity: string;
  evidence_status: string;
  baseline_comparison: Report["baseline_comparison"];
};

export function ReportCharts({ report }: { report: Report }) {
  const datasets = report.dataset_results ?? [{ dataset_key: report.dataset_key || "GPQA", summary: report.summary, validity: report.validity, evidence_status: report.evidence_status, baseline_comparison: report.baseline_comparison }];
  const groups = datasets.map(dataset => {
    const baseline = dataset.baseline_comparison;
    const measured = report.evidence_status === "verified" && dataset.evidence_status === "verified" && ["complete", "partial"].includes(dataset.validity) && dataset.summary.scoring_status === "succeeded" && percent(dataset.summary.accuracy) ? dataset.summary.accuracy : null;
    const reference = measured !== null && dataset.validity === "complete" && baseline.status === "matched" && baseline.baseline_unit === "percent" && baseline.measured_value === measured && percent(baseline.baseline_value) ? baseline.baseline_value : null;
    const scope = dataset.summary.subset_scope;
    return { dataset, measured, reference, baseline, scope: scope === "full" ? "全量" : scope === "lite" ? "Lite" : scope };
  });
  const scopes = new Set(groups.map(g => g.scope));
  const hasBaseline = groups.some(g => g.reference !== null);
  return <section className="report-charts dataset-axis-layout" aria-label="报告全部数据集图表">
    <section className="report-chart-panel">
      <header className="spread"><h3><BarChart3 size={18} />精度测评</h3><span className="badge">{scopes.size === 1 && groups[0]?.scope && groups[0].scope + " · "}{groups.length} 个数据集</span></header>
      <div className="chart-legend"><span><i className="chart-swatch measured" />本次测评</span>{hasBaseline && <span><i className="chart-swatch reference" />基线</span>}</div>
      <figure className="accuracy-comparison axis-figure" aria-label="多数据集准确率与基线分组对比图">
        {groups.length ? <div className="axis-scroll"><div className="axis-plot" style={{minWidth: groups.length * 130 + 48}}>
          <div className="axis-scale">{[100,75,50,25,0].map(n => <span key={n}>{n}%</span>)}</div>
          {groups.map(({dataset, measured, reference, scope}) => <div className="axis-group" key={dataset.dataset_key}>
            <div className="axis-bars">{([["本次测评",measured],["基线",reference]] as const).map(([label,n]) =>
              n === null ? (label === "本次测评" && <small key={label}>缺测</small>) :
              <div key={label} role="meter" aria-label={dataset.dataset_key+" "+label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={n}
                title={reference !== null && measured !== null ? "较基线 "+formatDelta(measured, reference)+" 个百分点" : label}
                className={"axis-bar "+(label === "基线" ? "reference" : "")} style={{height:n+"%"}}><b>{Number(n.toFixed(2))}%</b></div>)}</div>
            <strong>{dataset.display_name || dataset.dataset_key}</strong>{scopes.size > 1 && <small>{scope}</small>}
          </div>)}
        </div></div> : <p>暂无数据集结果</p>}
        <figcaption>{!hasBaseline && "本报告暂无可比基线。"}各数据集独立计分，部分覆盖时仅展示本次成绩。</figcaption>
      </figure>
      <details><summary>查看基线详情</summary>{groups.map(({dataset, measured, reference, baseline}) => <p key={dataset.dataset_key} className="chart-baseline-version">
        <b>{dataset.display_name || dataset.dataset_key}</b> · {reference !== null && measured !== null ? "较基线 "+formatDelta(measured, reference)+" 个百分点" : measured === null ? "暂无可核验准确率" : dataset.validity === "partial" ? "部分覆盖" : baseline.baseline_key ? "暂无可比基线" : "基线未配置"}
        {baseline.baseline_key && <> · {baseline.baseline_key} / {baseline.baseline_version || "版本未提供"}</>}
        {baseline.attached_after_execution && " · 执行后补录的标准库参考"}
      </p>)}</details>
    </section>
    <div className="performance-chart-empty performance-inline" role="status"><Activity size={16}/>性能测评 · 暂无性能测评数据</div>
  </section>;
}
