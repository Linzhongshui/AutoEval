import { useEffect, useState } from "react";
import { apiPost } from "../../shared/api";
import { PageNumbers } from "../../shared/ui/PageNumbers";
import { CustomAdapterEditor } from "./CustomAdapterEditor";
import { StandardInputs } from "./StandardInputs";
import { aisbenchCatalog } from "./standardCatalog";
import { Note } from "../../shared/ui/Note";
import { ConfigurationDrawer } from "../../shared/ui/ConfigurationDrawer";
import type { Param, Profile } from "../evaluation/types";
import { baseParams } from "../evaluation/logic";
import { DatasetTree } from "./datasetTree";
import { ParameterCards } from "./parameterCards";

export function Configurations({ profiles, setProfiles, go, notify }: {
  profiles: Profile[];
  setProfiles: (p: Profile[]) => void;
  go: (p: string) => void;
  notify: (s: string) => void;
}) {
  const [catalogNames, setCatalogNames] = useState<string[]>([]);
  const [catalogError, setCatalogError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    aisbenchCatalog(controller.signal).then((rows) => setCatalogNames([...new Set(rows.map((row) => row.benchmark))])).catch(() => { if (!controller.signal.aborted) setCatalogError("AISBench 数据集目录加载失败，请重新打开页面。"); });
    return () => controller.abort();
  }, []);
  const [kind, setKind] = useState("标准配置");
  const [officialVersion, setOfficialVersion] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);
  const [query, setQuery] = useState("");
  const [versions, setVersions] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Profile | null>(null);
  const [active, setActive] = useState("GPQA");
  const [params, setParams] = useState<Record<string, Param>>({});
  const [versionName, setVersionName] = useState("");
  const [saveTo, setSaveTo] = useState("新建配置");
  const [saving, setSaving] = useState(false);
  const [add, setAdd] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [catalog, setCatalog] = useState("");
  const [catalogMode, setCatalogMode] = useState("全量");
  const standardVersions = Array.from(new Set(
    profiles.filter((p) => p.official).flatMap((p) => p.versions),
  ));
  const currentOfficialVersion = standardVersions.includes(officialVersion)
    ? officialVersion
    : standardVersions[0] || "";
  const officialRows = profiles.filter((p) => p.official && p.versions.includes(currentOfficialVersion));
  const filtered = (kind === "历史标准配置" ? officialRows : profiles.filter((p) => !p.official))
    .filter((p) => [p.name, p.source, p.model, p.modelId].join(" ").toLowerCase().includes(query.toLowerCase()));
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  useEffect(() => setPage(1), [kind, currentOfficialVersion, query]);

  const open = (p: Profile) => {
    setEditing({ ...p, items: [...p.items] });
    setActive(p.items[0] || "GPQA");
    const selectedVersion = p.official ? currentOfficialVersion : versions[p.id] || p.versions[0];
    setParams(structuredClone(p.data?.[selectedVersion]) || Object.fromEntries(p.items.map((d, i) => [d, baseParams(i)])));
    setVersionName("");
    setSaveTo("新建配置");
  };

  const configurationTabs = <div className="tabs configuration-tabs" role="tablist" aria-label="配置类型">
    {["标准配置", "自定义配置"].map((name) =>
      <button type="button" role="tab" aria-selected={name === "标准配置" ? kind !== "自定义配置" : kind === name} className={(name === "标准配置" ? kind !== "自定义配置" : kind === name) ? "active" : ""} key={name} onClick={() => setKind(name)}>{name}</button>)}
  </div>;
  if (kind === "标准配置") return <section className="card stack configuration-panel">
    {configurationTabs}
    <div className="spread"><p className="muted">标准配置只读。在详情中查看标准参数与版本来源。</p><button className="link" onClick={() => setKind("历史标准配置")}>查看历史标准配置</button></div>
    <StandardInputs />
  </section>;

  return (
    <div className="stack">
      <section className="card configuration-panel">{configurationTabs}</section>
      {kind === "历史标准配置" && <div className="spread"><h3>历史标准配置</h3><button className="link" onClick={() => setKind("标准配置")}>返回当前标准配置</button></div>}
      <Note>
        标准配置只读；自定义配置保存为新版本，历史版本保持不变。
      </Note>
      <div className="config-toolbar">
        <input aria-label="搜索配置" placeholder="搜索配置名称或来源" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="primary" onClick={() => open({
          id: "new", name: "新配置", source: "未保存", official: false, versions: [], items: ["GPQA"],
        })}>新建配置</button>
        <button onClick={() => notify("导入格式、校验与失败恢复规则待确认，暂未开放文件导入。")}>导入配置</button>
      </div>
      <section className="card stack">
        <div className="config-list-heading">
          {kind === "历史标准配置" && (
            <label className="official-version">
              仓库版本
              <select aria-label="标准配置版本" value={currentOfficialVersion} onChange={(e) => setOfficialVersion(e.target.value)}>
                {standardVersions.map((v) => <option key={v}>{v}</option>)}
              </select>
            </label>
          )}
        </div>
        <p className="muted">
          {kind === "历史标准配置"
            ? `当前版本 ${currentOfficialVersion || "无"} · 后端返回 ${officialRows.length} 个配置 · 仅供查看`
            : "自定义配置可保存多个版本，版本名称由维护者定义。"}
        </p>
        <div className="table-wrap">
          <table>
            <thead><tr>{[
              "配置名称", "模型标识", "配置来源", ...(kind === "自定义配置" ? ["配置版本"] : []), "数据集", "操作",
            ].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.modelId || "未关联模型"}</td>
                  <td>{p.source}</td>
                  {kind === "自定义配置" && (
                    <td>
                      <select aria-label={`${p.name}版本`} value={versions[p.id] || p.versions[0]} onChange={(e) => setVersions({ ...versions, [p.id]: e.target.value })}>
                        {p.versions.map((v) => <option key={v}>{v}</option>)}
                      </select>
                    </td>
                  )}
                  <td>{p.items.length} 个数据集</td>
                  <td><button className="link" onClick={() => open(p)}>{p.official ? "查看" : "维护配置"}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filtered.length && <div className="empty">暂无匹配的配置</div>}
        </div>
        <div className="pagination" aria-label="配置列表分页">
          <span>共 {filtered.length} 条 · 每页 {pageSize} 条</span>
          <label className="pagination-page-size"><span>每页</span><select aria-label="每页条数" value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1);}}>{[5,15,30,50].map(size=><option key={size} value={size}>{size} 条</option>)}</select></label>
          <button disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>上一页</button>
          <PageNumbers current={currentPage} total={pageCount} onChange={setPage} />
          <button disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button>
        </div>
      </section>
      {editing && (
        <ConfigurationDrawer>
          <div className="stack standard-detail custom-config-detail">
            <div className="spread">
              <h2>{editing.official ? "查看标准配置（只读）" : "维护自定义配置"}</h2>
              <button onClick={() => setEditing(null)}>关闭</button>
            </div>
            <div className="inline">
              <span>来源：{editing.source}</span>
              {editing.model && <span>模型：{editing.model} · {editing.modelId}</span>}
              <span>当前版本：{editing.official ? currentOfficialVersion : versions[editing.id] || editing.versions[0] || "未保存"}</span>
            </div>
            {editing.official && <details className="notice"><summary>标准来源与只读参数</summary>{(() => { const source = editing.provenance?.[currentOfficialVersion]; return source?.url ? <><a href={source.url} target="_blank" rel="noreferrer">查看批准配置来源</a><p>来源版本：{source.revision}</p><small>SHA-256：{source.sha256}</small></> : <p>此历史配置未提供可展示的来源元数据。</p>; })()}<p>本页标准参数只读。新同步的标准仓输入需在“标准仓输入与版本”中独立评审，不会替代当前配置。</p><pre className="snapshot">{JSON.stringify(params, null, 2)}</pre></details>}
            <div className="workflow-grid">
              <aside className="workflow-datasets">
                <DatasetTree
                  items={editing.items}
                  selected={editing.items}
                  active={active}
                  onActive={setActive}
                  onSelect={editing.official ? undefined : (items) => {
                    setEditing({ ...editing, items });
                    if (!items.includes(active)) setActive(items[0] || "");
                  }}
                />
                {!editing.official && <button onClick={() => { setPicked([]); setAdd(true); }}>添加数据集</button>}
              </aside>
              <div className="card stack custom-parameter-panel"><h3>{active}</h3>{params[active]?.adapter_input ? <details><summary>旧版兼容参数</summary><ParameterCards items={editing.items} active={active} params={{ ...params, [active]: { ...params[active], adapter_input: undefined } }} onChange={(next) => setParams({ ...next, [active]: { ...next[active], adapter_input: params[active].adapter_input } })} readonly={editing.official} /></details> : <ParameterCards items={editing.items} active={active} params={params} onChange={setParams} readonly={editing.official} />}
              {!editing.official && active && <CustomAdapterEditor dataset={active} value={params[active]?.adapter_input} onChange={(next) => { const updated = { ...(params[active] || baseParams()) }; if (next) updated.adapter_input = next; else delete updated.adapter_input; setParams({ ...params, [active]: updated }); }} />}</div>
            </div>
            {!editing.official && (
              <div className="config-save-panel">
                <h3>保存设置</h3>
                <div className="config-save-fields">
                  <label>
                    <span>保存方式</span>
                    <select value={saveTo} onChange={(e) => setSaveTo(e.target.value)}>
                      <option>新建配置</option>
                      {profiles.filter((p) => !p.official).map((p) => <option key={p.id} value={p.id}>保存到：{p.name}</option>)}
                    </select>
                  </label>
                  <label>
                    <span>自定义版本名称 <span className="required-mark">*</span></span>
                    <input placeholder="例如：多模态验证-第三版" required aria-describedby="config-save-help" value={versionName} onChange={(e) => setVersionName(e.target.value)} />
                  </label>
                </div>
                <p id="config-save-help" className="config-save-help">
                  {saveTo === "新建配置" ? "创建一份独立配置，版本名称同时作为配置名称。" : "将本次参数保存为所选配置的新版本，保留已有历史版本。"}
                  {" "}保存到后端数据库；失败时保留当前编辑内容。
                </p>
                <div className="config-save-actions">
                  <button onClick={() => setEditing(null)}>取消</button>
                  <button
                    className="primary"
                    disabled={saving || !versionName.trim() || !editing.items.length}
                    onClick={async () => {
                      if (saving) return;
                      const invalid = document.querySelector<HTMLInputElement>(".adapter-fields :invalid");
                      if (invalid) { invalid.reportValidity(); return; }
                      const target = saveTo === "新建配置" ? null : profiles.find((p) => p.id === saveTo);
                      if (saveTo !== "新建配置" && !target) { notify("目标配置不存在，请刷新"); return; }
                      const key = target?.id || `custom-${crypto.randomUUID()}`;
                      const items = Object.fromEntries(editing.items.map((name) => [name, params[name]]));
                      setSaving(true);
                      try {
                        const savedVersion = await apiPost<{ version: number }>("/test-configs", {
                            config_key: key,
                            display_name: target?.name || versionName.trim(),
                            version_label: versionName.trim(),
                            expected_version: target?.persistedVersion || 0,
                            items,
                        });
                        const saved: Profile = {
                          ...editing,
                          id: key,
                          name: target?.name || versionName.trim(),
                          official: false,
                          source: "后端持久化",
                          persistedVersion: savedVersion.version,
                          versions: [versionName.trim(), ...(target?.versions || [])],
                          items: [...editing.items],
                          data: { ...target?.data, [versionName.trim()]: structuredClone(items) },
                        };
                        setProfiles(target ? profiles.map((p) => p.id === key ? saved : p) : [...profiles, saved]);
                        setEditing(null);
                        notify("配置已保存到后端，刷新后可重新加载。");
                      } catch (error) {
                        notify(error instanceof Error ? error.message : "后端不可用，配置未保存");
                      } finally { setSaving(false); }
                    }}
                  >保存配置</button>
                </div>
              </div>
            )}
          </div>
        </ConfigurationDrawer>
      )}
      {add && (
        <div className="dataset-overlay">
          <section className="dataset-dialog">
            <h3>添加数据集</h3>
            <input placeholder="搜索数据集" value={catalog} onChange={(e) => setCatalog(e.target.value)} />
            <p className="muted">{catalogError || "仅显示标准仓已登记的 AISBench 数据集，展示不代表已开放执行。"}</p><select value={catalogMode} onChange={(e) => setCatalogMode(e.target.value)}><option>全量</option><option>Lite</option></select>
            <DatasetTree
              items={catalogError ? [] : catalogNames.filter((d) => d.toLowerCase().includes(catalog.toLowerCase()))}
              selected={picked}
              disabled={editing?.items || []}
              onSelect={setPicked}
              scope={catalogMode}
            />
            <Note>重复项暂禁用以避免重复；正式去重规则待确认。</Note>
            <div className="inline">
              <button onClick={() => setAdd(false)}>取消</button>
              <button className="primary" disabled={!picked.length} onClick={() => {
                if (editing) {
                  setEditing({ ...editing, items: [...editing.items, ...picked] });
                  setParams({ ...params, ...Object.fromEntries(picked.map((d) => [d, { ...baseParams(), scope: catalogMode }])) });
                }
                setAdd(false);
              }}>确认添加</button>
            </div>
          </section>
        </div>
      )}
      <button className="link back" onClick={() => go("console")}>返回控制台</button>
    </div>
  );
}

