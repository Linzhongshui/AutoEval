import { useEffect, useState } from "react";
import { aisbenchCatalog, type StandardCatalogEntry } from "../services/standardCatalog";
import { AdapterFields } from "./AdapterFields";

export function CustomAdapterEditor({ value, onChange, dataset }: { dataset: string; value?: Record<string, unknown>; onChange: (next: Record<string, unknown> | undefined) => void }) {
  const [standards, setStandards] = useState<StandardCatalogEntry[]>([]);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    aisbenchCatalog(controller.signal).then((rows) => setStandards(rows.filter((row) => row.benchmark === dataset || dataset === "GPQA" && row.benchmark === "GPQA_Diamond"))).catch(() => { if (!controller.signal.aborted) setMessage("标准模板加载失败，请重新打开配置。"); });
    return () => controller.abort();
  }, [dataset]);
  return <section className="stack custom-adapter-editor"><h4>完整测评参数</h4><p className="muted">从标准模板补全字段后可编辑，保存为独立版本。未开放执行。</p>
    <label>从标准仓补全字段<select value="" onChange={(event) => {
      const row = standards[Number(event.target.value)];
      if (row) onChange(JSON.parse(row.files["standard_config.json"].raw));
    }}><option value="">请选择来源模型与基准（将替换完整参数）</option>{standards.map((row, index) => <option key={`${row.source_model}/${row.benchmark}`} value={index}>{row.source_model} / {row.benchmark}</option>)}</select></label>
    {message && <p role="alert">{message}</p>}
    {value && <><AdapterFields value={value} onChange={onChange} /><details><summary>完整配置 JSON</summary><pre className="snapshot">{JSON.stringify(value, null, 2)}</pre></details><button className="link" onClick={() => onChange(undefined)}>移除完整工具参数</button></>}
  </section>;
}
