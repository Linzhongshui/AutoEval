import { ManagementDrawer } from "./ManagementDrawer";
import { useEffect, useState } from "react";
import { apiGetPage } from "../services/api";
import { datasetIdentity, datasetNote } from "../services/datasetIdentities";

type Row = { entry: { dataset: string; metric: string; unit: string; scope: string; source_name: string; source_version: string; conditions: Record<string, unknown> } };
export function WorkbenchDatasets({ revision }: { revision: number }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController(); setMessage("加载中…"); setRows([]);
    void (async () => {
      const result: Row[] = []; let offset: number | null = 0;
      while (offset !== null) {
        const page: { data: Row[]; next_offset: number | null } = await apiGetPage<Row[]>(`/data-workbench/entries?offset=${offset}&limit=100`, controller.signal);
        result.push(...page.data);
        if (page.next_offset !== null && page.next_offset <= offset) throw Error("分页异常");
        offset = page.next_offset;
      }
      if (!controller.signal.aborted) { setRows(result); setMessage(""); }
    })().catch(() => { if (!controller.signal.aborted) setMessage("数据集读取失败，请刷新重试。"); });
    return () => controller.abort();
  }, [revision]);
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    const key = datasetIdentity(row.entry.dataset);
    groups.set(key, [...(groups.get(key) || []), row]);
  }
  return <section className="card"><h2>数据集列表</h2><p className="muted">汇总全部维护记录（含草稿及已撤回），仅规范展示名称，不修改原始记录或执行配置。名称相同不代表成绩可直接比较。</p><input aria-label="搜索数据集" placeholder="搜索数据集或原始名称" value={query} onChange={(e) => setQuery(e.target.value)} />{message && <p role="status">{message}</p>}<div className="table-wrap"><table><thead><tr><th>数据集</th><th>原始名称 / 核对说明</th><th>指标 / 单位</th><th>范围 / 版本</th><th>记录数</th><th>来源与条件</th></tr></thead><tbody>{[...groups].sort(([a], [b]) => a.localeCompare(b)).filter(([name, entries]) => [name, ...entries.map((r) => r.entry.dataset)].some((v) => v.toLowerCase().includes(query.toLowerCase()))).map(([name, entries]) => <tr key={name}><td><b>{name}</b></td><td>{[...new Set(entries.map((r) => r.entry.dataset))].join("、")}<small>{datasetNote(name)}</small></td><td>{[...new Set(entries.map((r) => `${r.entry.metric} / ${r.entry.unit}`))].join("、")}</td><td>{[...new Set(entries.map((r) => `${r.entry.scope} / ${r.entry.conditions.dataset_version || "版本未披露"}`))].join("、")}</td><td>{entries.length}</td><td><ManagementDrawer title="查看"><h3>{name} · 来源与条件</h3>{entries.map((r, i) => <div key={i}><p>{r.entry.dataset} · {r.entry.source_name} · {r.entry.source_version}</p><pre className="snapshot">{JSON.stringify(r.entry.conditions, null, 2)}</pre></div>)}</ManagementDrawer></td></tr>)}</tbody></table></div>{!message && !groups.size && <p className="empty">暂无数据集记录</p>}</section>;
}
