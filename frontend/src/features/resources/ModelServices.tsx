import { useEffect, useState } from "react";
import { apiGetOptions, apiPost } from "../../shared/api";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { serviceLabel, serviceLabels, type ServiceKind } from "./serviceKind";
import { ServiceBindings } from "./ServiceBindings";
type Service = { service_kind?: ServiceKind | null; id: string; service_name: string; model_key: string; model_version: string; remote_model: string; base_url: string; archived: boolean };
export function ModelServices() {
  const [rows, setRows] = useState<Service[]>([]); const [message, setMessage] = useState(""); const [query, setQuery] = useState(""); const [revision, setRevision] = useState(0); const [busy, setBusy] = useState(false);
  const [source, setSource] = useState("all");
  useEffect(() => { const c = new AbortController(); apiGetOptions<Service[]>("/target-bindings", c.signal).then(p => setRows(p.data)).catch(() => { if (!c.signal.aborted) setMessage("服务加载失败"); }); return () => c.abort(); }, [revision]);
  async function act(fn: () => Promise<unknown>) { setBusy(true); try { await fn(); setRevision(v => v + 1); } catch (e) { setMessage(e instanceof Error ? e.message : "操作失败"); } finally { setBusy(false); } }
  async function update(row: Service, name: string, archived: boolean, kind?: string) {
    const response = await fetch(`/api/autoeval/v1/target-bindings/${row.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ service_name: name, archived, service_kind: kind || undefined }) });
    if (!response.ok) throw Error("保存失败"); setMessage(archived ? "服务已移除，历史记录保留。" : "服务信息已保存。");
  }
  const search = query.trim().toLowerCase();
  const visibleRows = rows.filter(row =>
    (source === "all" || source === (row.service_kind || "unknown")) &&
    [row.service_name, row.model_key, row.model_version, row.remote_model, row.base_url]
      .some(value => value?.toLowerCase().includes(search))
  );
  return <section className="card stack"><div className="spread"><h2>模型服务</h2><div className="inline"><ManagementDrawer title="新增服务" onDismiss={() => setRevision(v => v + 1)}><ServiceBindings /></ManagementDrawer><button disabled={busy} onClick={() => void act(async () => { const result = await apiPost<{ archived_ids: string[] }>("/target-bindings/deduplicate", {}); setMessage(`已移除 ${result.archived_ids.length} 条完全重复服务，历史引用保留。`); })}>清理重复服务</button></div></div><div className="service-filter"><label>服务来源<select value={source} onChange={e => setSource(e.target.value)}>
    <option value="all">全部来源</option><option value="local">{serviceLabels.local}</option><option value="official">{serviceLabels.official}</option><option value="unknown">待确认</option></select></label>
    <label>搜索服务<input aria-label="搜索模型服务" placeholder="服务名、模型或 API 地址" value={query} onChange={e => setQuery(e.target.value)} /></label></div>{message && <p role="status">{message}</p>}<div className="table-wrap"><table><thead><tr><th>服务名称</th><th>服务来源</th><th>模型 / 版本</th><th>远程模型名</th><th>API 地址</th><th>连接检测</th><th>操作</th></tr></thead><tbody>{visibleRows.map(row => <tr key={row.id}><td>{row.service_name}<small>{row.id.slice(0, 8)}</small></td><td><span className="service-kind">{serviceLabel(row.service_kind)}</span></td><td>{row.model_key}<small>{row.model_version}</small></td><td>{row.remote_model}</td><td>{row.base_url}</td><td><button disabled={busy} onClick={() => void act(async () => { const result = await apiPost<{ outcome: string }>(`/targets/${row.id}/connection-tests`, {}); setMessage(`${row.service_name}：${result.outcome === "matched" ? "连接与模型匹配成功（未调用生成）" : result.outcome}`); })}>检测连接</button></td><td><ManagementDrawer title="编辑服务"><form onSubmit={e => { e.preventDefault(); const fields = new FormData(e.currentTarget); const name = String(fields.get("name") || "").trim(); if (name) void act(() => update(row, name, false, String(fields.get("kind") || ""))); }}><label>服务名称<input name="name" required maxLength={128} defaultValue={row.service_name} /></label><label>服务来源<select name="kind" defaultValue={row.service_kind || ""}>{!row.service_kind && <option value="">待确认</option>}<option value="local">{serviceLabels.local}</option><option value="official">{serviceLabels.official}</option></select></label><button disabled={busy}>保存</button></form></ManagementDrawer><button disabled={busy} onClick={() => void act(() => update(row, row.service_name, true))}>删除</button><a href={`#evaluate?target=${row.id}`}>用于测评</a></td></tr>)}{visibleRows.length === 0 && <tr><td colSpan={7}>暂无匹配的模型服务</td></tr>}</tbody></table></div></section>;
}
