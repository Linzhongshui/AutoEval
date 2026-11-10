import { createPortal } from "react-dom";
import { useState, useEffect } from "react";
import { ModelRegistry } from "../components/ModelRegistry";
type Param = {
  output: number;
  concurrency: number;
  temperature: number;
  top_p: number;
  scope: string;
};
type Profile = {
  persistedVersion?: number;
  id: string;
  name: string;
  source: string;
  model?: string;
  modelId?: string;
  official: boolean;
  versions: string[];
  items: string[];
  data?: Record<string, Record<string, Param>>;
};
const names = ["GPQA", "MMMU-Pro", "AutomationBench"];
const datasetTypes = [
  { label: "科学问答", items: ["GPQA"] },
  { label: "多模态", items: ["MMMU-Pro"] },
  { label: "Agent 工作流", items: ["AutomationBench"] },
];
function DatasetTree({
  items,
  selected,
  disabled = [],
  active,
  onSelect,
  onActive,
  scope,
}: {
  items: string[];
  selected?: string[];
  disabled?: string[];
  active?: string;
  onSelect?: (items: string[]) => void;
  onActive?: (name: string) => void;
  scope?: string;
}) {
  return (
    <div className="dataset-tree" aria-label="按类型分组的数据集">
      {datasetTypes.map((group) => {
        const children = group.items.filter((d) => items.includes(d));
        if (!children.length) return null;
        return (
          <details open key={group.label} className="dataset-tree-group">
            <summary>
              {group.label}
              <span>{children.length}</span>
            </summary>
            <div className="dataset-tree-children">
              {children.map((d) => (
                <div
                  key={d}
                  className={`dataset-tree-row ${active === d ? "is-active" : ""}`}
                >
                  {onSelect && (
                    <input
                      aria-label={`选择 ${d}`}
                      type="checkbox"
                      disabled={disabled.includes(d)}
                      checked={selected?.includes(d) || disabled.includes(d)}
                      onChange={(e) =>
                        onSelect(
                          e.target.checked
                            ? [...(selected || []).filter((x) => x !== d), d]
                            : (selected || []).filter((x) => x !== d),
                        )
                      }
                    />
                  )}
                  {onActive ? (
                    <button
                      className="dataset-tree-name"
                      title={d}
                      onClick={() => onActive(d)}
                    >
                      {d}
                    </button>
                  ) : (
                    <label
                      className="dataset-tree-name"
                      onClick={() => {
                        if (onSelect && !disabled.includes(d))
                          onSelect(
                            selected?.includes(d)
                              ? selected.filter((x) => x !== d)
                              : [...(selected || []), d],
                          );
                      }}
                    >
                      {d}
                    </label>
                  )}
                  {scope && <span className="dataset-tree-meta">{scope}</span>}
                  {disabled.includes(d) && (
                    <span className="dataset-tree-meta">已添加</span>
                  )}
                </div>
              ))}
            </div>
          </details>
        );
      })}
      {!items.length && <div className="empty">未找到匹配的数据集</div>}
    </div>
  );
}
const base = (i = 0): Param => ({
  output: 2048,
  concurrency: 60 - i * 20,
  temperature: 0.6,
  top_p: 0.95,
  scope: "全量",
});
const seed: Profile[] = [
  {
    id: "official",
    name: "标准配置",
    source: "固定仓库",
    official: true,
    versions: ["v1.3", "v1.2", "v1.1"],
    items: names,
  },
  {
    id: "custom",
    name: "多模态验证",
    source: "当前用户",
    official: false,
    versions: ["多模态验证-第二版", "多模态验证-初版"],
    items: names.slice(0, 2),
  },
];
export function useProfiles() {
  const [profiles, setProfiles] = useState<Profile[]>(seed.filter((p) => p.official));
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/autoeval/v1/test-configs?limit=200", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("配置服务不可用");
        return response.json();
      })
      .then((body) => {
        const grouped = new Map<string, Profile>();
        for (const item of body.data as Array<{ config_key: string; display_name: string;
          version: number; version_label: string; kind: string; items: Record<string, Param> }>) {
          if (item.kind !== "custom") continue;
          const existing = grouped.get(item.config_key);
          if (existing) {
            existing.versions.push(item.version_label);
            existing.data![item.version_label] = item.items;
          } else grouped.set(item.config_key, { id: item.config_key, name: item.display_name,
            source: "后端持久化", official: false, persistedVersion: item.version,
            versions: [item.version_label], items: Object.keys(item.items),
            data: { [item.version_label]: item.items } });
        }
        setProfiles([...seed.filter((p) => p.official), ...grouped.values()]);
      }).catch(() => { /* Saving reports dependency errors explicitly; no fake persisted data. */ });
    return () => controller.abort();
  }, []);
  return [profiles, setProfiles] as const;
}
function Note({ children }: { children: React.ReactNode }) {
  return <div className="notice">{children}</div>;
}
function ParameterCards({
  active,
  items,
  params,
  onChange,
  readonly = false,
}: {
  items: string[];
  params: Record<string, Param>;
  onChange: (p: Record<string, Param>) => void;
  readonly?: boolean;
  active: string;
}) {
  return (
    <div className="stack">
      {items
        .filter((d) => d === active)
        .map((d) => {
          const value = params[d] || base();
          const locked = readonly;
          return (
            <section className="card" key={d}>
              <h3>
                {d}
                {locked ? " · 只读" : ""}
              </h3>
              <div className="params">
                {(
                  ["output", "concurrency", "temperature", "top_p"] as const
                ).map((k, i) => (
                  <label key={k}>
                    {["输出长度", "并发", "temperature", "top_p"][i]}
                    <input
                      type="number"
                      min="0"
                      disabled={locked}
                      value={value[k]}
                      onChange={(e) =>
                        onChange({
                          ...params,
                          [d]: { ...value, [k]: Number(e.target.value) },
                        })
                      }
                    />
                  </label>
                ))}
              </div>
              <label className="parameter-scope">
                数据范围
                <select
                  disabled={locked}
                  value={value.scope}
                  onChange={(e) =>
                    onChange({
                      ...params,
                      [d]: { ...value, scope: e.target.value },
                    })
                  }
                >
                  <option>全量</option>
                  <option>Lite</option>
                </select>
              </label>
            </section>
          );
        })}
      {!items.length && <div className="empty">请从左侧选择数据集</div>}
    </div>
  );
}
function ConfigurationDrawer({ children }: { children: React.ReactNode }) {
  return (
    <div className="workflow-backdrop">
      <section
        className="workflow-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="配置编辑"
      >
        {children}
      </section>
    </div>
  );
}
export function Configurations({
  profiles,
  setProfiles,
  go,
  notify,
}: {
  profiles: Profile[];
  setProfiles: (p: Profile[]) => void;
  go: (p: string) => void;
  notify: (s: string) => void;
}) {
  const [kind, setKind] = useState("标准配置");
  const [officialVersion, setOfficialVersion] = useState("v1.3");
  const [page, setPage] = useState(1);
  const pageSize = 5;
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
  const officialRows: Profile[] = Array.from(
    {
      length:
        officialVersion === "v1.3" ? 12 : officialVersion === "v1.2" ? 9 : 6,
    },
    (_, i) => ({
      id: `official-${officialVersion}-${i}`,
      name: `Demo Vision ${String.fromCharCode(65 + i)} 测评配置`,
      model: `Demo Vision ${String.fromCharCode(65 + i)}`,
      modelId: `demo-vlm-${String(i + 1).padStart(3, "0")}`,
      source: "固定仓库",
      official: true,
      versions: [officialVersion],
      items: i % 3 === 0 ? names : names.slice(0, 2),
      data: {
        [officialVersion]: Object.fromEntries(
          names.map((d, j) => [
            d,
            { ...base(j), output: officialVersion === "v1.3" ? 2048 : 1024 },
          ]),
        ),
      },
    }),
  );
  const filtered = (
    kind === "标准配置" ? officialRows : profiles.filter((p) => !p.official)
  ).filter((p) =>
    [p.name, p.source, p.model, p.modelId]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  useEffect(() => setPage(1), [kind, officialVersion, query]);
  const open = (p: Profile) => {
    setEditing({ ...p, items: [...p.items] });
    setActive(p.items[0] || "GPQA");
    const offset = p.versions.indexOf(versions[p.id] || p.versions[0]);
    setParams(
      structuredClone(p.data?.[versions[p.id] || p.versions[0]]) ||
        Object.fromEntries(
          p.items.map((d, i) => [
            d,
            { ...base(i), output: offset > 0 ? 1024 : 2048 },
          ]),
        ),
    );
    setVersionName("");
    setSaveTo("新建配置");
  };
  return (
    <div className="stack">
      <Note>
        标准配置来自固定仓库，版本读取
        tag；标准仓库版本仍为只读示例；自定义配置通过后端数据库保存与加载。
      </Note>
      <div className="config-toolbar">
        <input
          aria-label="搜索配置"
          placeholder="搜索配置名称或创建者"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          className="primary"
          onClick={() =>
            open({
              id: "new",
              name: "新配置",
              source: "当前用户",
              official: false,
              versions: [],
              items: ["GPQA"],
            })
          }
        >
          新建配置
        </button>
        <button
          onClick={() =>
            notify("导入格式、校验与失败恢复规则待确认，暂未开放文件导入。")
          }
        >
          导入配置
        </button>
      </div>
      <section className="card stack">
        <div className="config-list-heading">
          <div className="tabs" role="tablist" aria-label="配置类型">
            {["标准配置", "自定义配置"].map((t) => (
              <button
                role="tab"
                aria-selected={kind === t}
                className={kind === t ? "active" : ""}
                key={t}
                onClick={() => setKind(t)}
              >
                {t}
              </button>
            ))}
          </div>
          {kind === "标准配置" && (
            <label className="official-version">
              仓库版本
              <select
                aria-label="标准配置版本"
                value={officialVersion}
                onChange={(e) => setOfficialVersion(e.target.value)}
              >
                {["v1.3", "v1.2", "v1.1"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        <p className="muted">
          {kind === "标准配置"
            ? `当前版本 ${officialVersion} · 包含 ${officialRows.length} 个模型的测评配置 · 仅供查看`
            : "自定义配置由创建者维护，版本名称由创建者定义。"}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "配置名称",
                  "模型 / modelId",
                  "配置来源",
                  ...(kind === "自定义配置" ? ["配置版本"] : []),
                  "数据集",
                  "操作",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered
                .slice((currentPage - 1) * pageSize, currentPage * pageSize)
                .map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>
                      {p.model || "未指定模型"}
                      <small>{p.modelId || "通用自定义配置"}</small>
                    </td>
                    <td>{p.source}</td>
                    {kind === "自定义配置" && (
                      <td>
                        <select
                          aria-label={`${p.name}版本`}
                          value={versions[p.id] || p.versions[0]}
                          onChange={(e) =>
                            setVersions({ ...versions, [p.id]: e.target.value })
                          }
                        >
                          {p.versions.map((v) => (
                            <option key={v}>{v}</option>
                          ))}
                        </select>
                      </td>
                    )}
                    <td>{p.items.length} 个数据集</td>
                    <td>
                      <button className="link" onClick={() => open(p)}>
                        {p.official ? "查看" : "维护配置"}
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!filtered.length && <div className="empty">暂无匹配的配置</div>}
        </div>
        <div className="pagination" aria-label="配置列表分页">
          <span>
            共 {filtered.length} 条 · 每页 {pageSize} 条
          </span>
          <button
            disabled={currentPage === 1}
            onClick={() => setPage(currentPage - 1)}
          >
            上一页
          </button>
          {Array.from({ length: pageCount }, (_, i) => (
            <button
              key={i}
              className={currentPage === i + 1 ? "primary" : ""}
              aria-current={currentPage === i + 1 ? "page" : undefined}
              onClick={() => setPage(i + 1)}
            >
              {i + 1}
            </button>
          ))}
          <button
            disabled={currentPage === pageCount}
            onClick={() => setPage(currentPage + 1)}
          >
            下一页
          </button>
        </div>
      </section>
      {editing && (
        <ConfigurationDrawer>
          <div className="stack">
            <div className="spread">
              <h2>
                {editing.official ? "查看标准配置（只读）" : "维护自定义配置"}
              </h2>
              <button onClick={() => setEditing(null)}>关闭</button>
            </div>
            <div className="inline">
              <span>来源：{editing.source}</span>
              {editing.model && (
                <span>
                  模型：{editing.model} · {editing.modelId}
                </span>
              )}
              <span>
                当前版本：
                {versions[editing.id] || editing.versions[0] || "未保存"}
              </span>
              <span>基线：待确认</span>
            </div>
            <div className="workflow-grid">
              <aside className="workflow-datasets">
                <DatasetTree
                  items={editing.items}
                  selected={editing.items}
                  active={active}
                  onActive={setActive}
                  onSelect={
                    editing.official
                      ? undefined
                      : (items) => {
                          setEditing({ ...editing, items });
                          if (!items.includes(active))
                            setActive(items[0] || "");
                        }
                  }
                />
                {!editing.official && (
                  <button
                    onClick={() => {
                      setPicked([]);
                      setAdd(true);
                    }}
                  >
                    添加数据集
                  </button>
                )}
              </aside>
              <ParameterCards
                items={editing.items}
                active={active}
                params={params}
                onChange={setParams}
                readonly={editing.official}
              />
            </div>
            {!editing.official && (
              <div className="config-save-panel">
                <h3>保存设置</h3>
                <div className="config-save-fields">
                  <label>
                    <span>保存方式</span>
                    <select
                      value={saveTo}
                      onChange={(e) => setSaveTo(e.target.value)}
                    >
                      <option>新建配置</option>
                      {profiles
                        .filter((p) => !p.official)
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            保存到：{p.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    <span>
                      自定义版本名称 <span className="required-mark">*</span>
                    </span>
                    <input
                      placeholder="例如：多模态验证-第三版"
                      required
                      aria-describedby="config-save-help"
                      value={versionName}
                      onChange={(e) => setVersionName(e.target.value)}
                    />
                  </label>
                </div>
                <p id="config-save-help" className="config-save-help">
                  {saveTo === "新建配置"
                    ? "创建一份独立配置，版本名称同时作为配置名称。"
                    : "将本次参数保存为所选配置的新版本，保留已有历史版本。"}{" "}
                  保存到后端数据库；失败时保留当前编辑内容。
                </p>
                <div className="config-save-actions">
                  <button onClick={() => setEditing(null)}>取消</button>
                  <button
                    className="primary"
                    disabled={saving || !versionName.trim() || !editing.items.length}
                    onClick={async () => {
                      if (saving) return;
                      const target = saveTo === "新建配置" ? null : profiles.find((p) => p.id === saveTo);
                      if (saveTo !== "新建配置" && !target) { notify("目标配置不存在，请刷新"); return; }
                      const key = target?.id || `custom-${crypto.randomUUID()}`;
                      setSaving(true);
                      try {
                        const response = await fetch("/api/autoeval/v1/test-configs", {
                          method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ config_key: key,
                            display_name: target?.name || versionName.trim(),
                            version_label: versionName.trim(), expected_version: target?.persistedVersion || 0,
                            items: Object.fromEntries(editing.items.map((name) => [name, params[name]])) }),
                        });
                        const body = await response.json();
                        if (!response.ok) throw new Error(body.error?.message || "保存失败");
                        const saved: Profile = { ...editing, id: key,
                          name: target?.name || versionName.trim(), official: false, source: "后端持久化",
                          persistedVersion: body.data.version, versions: [versionName.trim(), ...(target?.versions || [])],
                          data: { ...target?.data, [versionName.trim()]: structuredClone(params) } };
                        setProfiles(target ? profiles.map((p) => p.id === key ? saved : p) : [...profiles, saved]);
                        setEditing(null); notify("配置已保存到后端，刷新后可重新加载。");
                      } catch (error) {
                        notify(error instanceof Error ? error.message : "后端不可用，配置未保存");
                      } finally { setSaving(false); }
                    }}
                  >
                    保存配置
                  </button>
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
            <input
              placeholder="搜索数据集"
              value={catalog}
              onChange={(e) => setCatalog(e.target.value)}
            />
            <select
              value={catalogMode}
              onChange={(e) => setCatalogMode(e.target.value)}
            >
              <option>全量</option>
              <option>Lite</option>
            </select>
            <DatasetTree
              items={names.filter((d) =>
                d.toLowerCase().includes(catalog.toLowerCase()),
              )}
              selected={picked}
              disabled={editing?.items || []}
              onSelect={setPicked}
              scope={catalogMode}
            />
            <Note>重复项暂禁用以避免重复；正式去重规则待确认。</Note>
            <div className="inline">
              <button onClick={() => setAdd(false)}>取消</button>
              <button
                className="primary"
                disabled={!picked.length}
                onClick={() => {
                  if (editing) {
                    setEditing({
                      ...editing,
                      items: [...editing.items, ...picked],
                    });
                    setParams({
                      ...params,
                      ...Object.fromEntries(
                        picked.map((d) => [
                          d,
                          { ...base(), scope: catalogMode },
                        ]),
                      ),
                    });
                  }
                  setAdd(false);
                }}
              >
                确认添加
              </button>
            </div>
          </section>
        </div>
      )}
      <button className="link back" onClick={() => go("console")}>
        返回控制台
      </button>
    </div>
  );
}
export function EvaluationConsole({
  profiles,
  setProfiles,
  notify,
}: {
  profiles: Profile[];
  setProfiles: (p: Profile[]) => void;
  notify: (s: string) => void;
}) {
  const [model, setModel] = useState("demo-vlm-001");
  const [evaluationVersion, setEvaluationVersion] = useState("v1.3");
  const versionParams = (version: string) =>
    Object.fromEntries(
      names.map((d, i) => [
        d,
        { ...base(i), output: version === "v1.3" ? 2048 : 1024 },
      ]),
    );
  const switchVersion = (version: string) => {
    setEvaluationVersion(version);
    setParams(versionParams(version));
    setSaved(false);
    setDrawer(false);
  };
  const [custom, setCustom] = useState(false);
  const customChoices = profiles
    .filter((p) => !p.official)
    .flatMap((p) =>
      p.versions.map((version) => ({
        key: p.id + "::" + version,
        profile: p,
        version,
      })),
    );
  const [customKey, setCustomKey] = useState("");
  const chosenCustom = customChoices.find((c) => c.key === customKey);
  const chooseCustom = (key: string) => {
    setCustomKey(key);
    const choice = customChoices.find((c) => c.key === key);
    setSaved(false);
    setDrawer(false);
    if (!choice) {
      setSelected([]);
      return;
    }
    const values = Object.fromEntries(
      names.map((d, i) => [
        d,
        choice.profile.data?.[choice.version]?.[d] || base(i),
      ]),
    );
    setParams(structuredClone(values));
    setSelected([...choice.profile.items]);
    setScopes(Object.fromEntries(names.map((d) => [d, values[d].scope])));
  };

  const [selected, setSelected] = useState(names);
  const [scopes, setScopes] = useState<Record<string, string>>(
    Object.fromEntries(names.map((d) => [d, "全量"])),
  );
  const [run, setRun] = useState("串行");
  // Populate ranges from an estimate service once a reliable source is available.
  const estimates: Record<
    string,
    Record<string, [number, number] | null>
  > = Object.fromEntries(names.map((d) => [d, { 全量: null, Lite: null }]));
  const ranges = selected.map((d) => estimates[d]?.[scopes[d]] ?? null);
  const missingEstimates = ranges.filter((range) => range === null).length;
  const totalRange = missingEstimates
    ? null
    : [0, 1].map((bound) =>
        run === "串行"
          ? ranges.reduce((sum, range) => sum + range![bound], 0)
          : Math.max(0, ...ranges.map((range) => range![bound])),
      );
  const totalDuration = !selected.length
    ? "0 分钟"
    : totalRange
      ? `${totalRange[0]}–${totalRange[1]} 分钟`
      : "暂无可靠估算";

  const [drawer, setDrawer] = useState(false);
  const [draft, setDraft] = useState(names);
  const [active, setActive] = useState("GPQA");
  const [params, setParams] = useState<Record<string, Param>>(
    Object.fromEntries(names.map((d, i) => [d, base(i)])),
  );
  const [draftParams, setDraftParams] = useState(params);
  const [saved, setSaved] = useState(false);
  const [view, setView] = useState<string | null>(null);
  const [saveAsNew, setSaveAsNew] = useState(false);
  const [newConfigName, setNewConfigName] = useState("");
  const [newVersionName, setNewVersionName] = useState("");
  const [api, setApi] = useState(true);
  const [datasetSearch, setDatasetSearch] = useState("");
  const visibleDatasets = names.filter((d) =>
    d.toLowerCase().includes(datasetSearch.toLowerCase()),
  );
  return (
    <div className="console-grid console-workflow">
      <div className="card console-configuration">
        <header className="console-configuration-heading">
          <h2>发起测评</h2>
          <p>选择模型、确认配置和数据集，完成本次测评设置。</p>
          <span className="console-demo-note">
            静态演示：不会连接模型或创建真实任务。
          </span>
        </header>
        <section className="console-step">
          <h3 className="console-step-title">
            <span className="step-number">1</span>模型与服务
          </h3>
          <div className="tabs">
            <button
              className={api ? "active" : ""}
              onClick={() => setApi(true)}
            >
              API接入
            </button>
            <button
              className={!api ? "active" : ""}
              onClick={() => setApi(false)}
            >
              IP/Port 拉起 · 演示
            </button>
          </div>
          {api ? (
            <><ModelRegistry onApply={(id, values, configKey, versionLabel) => {
              setCustom(true); setCustomKey(configKey + "::" + versionLabel);
              setModel(id); setParams(values); setSelected(Object.keys(values));
              setScopes(Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value.scope])));
              setSaved(false);
            }} /><div className="form-grid">
              <label>模型ID</label>
              <select
                value={model}
                onChange={(e) => {
                  setModel(e.target.value);
                  switchVersion("v1.3");
                  setCustom(false);
                  setSaved(false);
                }}
              >
                <option>demo-vlm-001</option>
                <option>demo-vlm-002</option>
              {!['demo-vlm-001', 'demo-vlm-002'].includes(model) && <option value={model}>{model}</option>}
              </select>
              <details open className="console-service-details">
                <summary>
                  服务配置 <span>未连接</span>
                </summary>
                <div className="form-grid">
                  <label>API 地址</label>
                  <input placeholder="https://api.example.com/v1" />
                  <label>API Key</label>
                  <input type="password" placeholder="请输入 API Key" />
                  <label>接口类型</label>
                  <select>
                    <option>OpenAI Compatible</option>
                  </select>
                  <span>未连接</span>
                  <button
                    onClick={() => notify("静态预览：未接入真实连接测试。")}
                  >
                    测试连接
                  </button>
                </div>
              </details>
            </div></>
          ) : (
            <div className="stack">
              <input placeholder="IP 地址" />
              <input placeholder="端口" />
              <button onClick={() => notify("演示入口，不会拉起真实服务。")}>
                演示拉起
              </button>
            </div>
          )}
        </section>
        <section className="console-step stack">
          <h3 className="console-step-title">
            <span className="step-number">2</span>测评配置
          </h3>
          <div className="console-config-fields">
            <fieldset className="console-config-type">
              <legend>配置类型</legend>
              <div className="console-config-segments">
                {["标准配置", "自定义配置"].map((m, i) => (
                  <label key={m} className={custom === !!i ? "selected" : ""}>
                    <input
                      type="radio"
                      name="console-config-type"
                      checked={custom === !!i}
                      onChange={() => {
                        setCustom(!!i);
                        if (i)
                          chooseCustom(
                            customKey || customChoices[0]?.key || "",
                          );
                        else {
                          switchVersion(evaluationVersion);
                          setSelected(names);
                          setScopes(
                            Object.fromEntries(names.map((d) => [d, "全量"])),
                          );
                        }
                        setSaved(false);
                      }}
                    />
                    {m}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="evaluation-version-field">
              <span>{custom ? "自定义配置" : "配置版本"}</span>
              {custom ? (
                <select
                  aria-label="自定义配置列表"
                  value={customKey}
                  onChange={(e) => chooseCustom(e.target.value)}
                  disabled={!customChoices.length}
                >
                  {!customChoices.length && (
                    <option value="">暂无自定义配置</option>
                  )}
                  {customChoices.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.profile.name} · {c.version}
                    </option>
                  ))}
                </select>
              ) : (
                <select
                  aria-label="配置版本"
                  value={evaluationVersion}
                  onChange={(e) => switchVersion(e.target.value)}
                >
                  {["v1.3", "v1.2", "v1.1"].map((v) => (
                    <option key={v} value={v}>
                      {v} · {model === "demo-vlm-001" ? "RC" : "Release"}
                      {v === "v1.3" ? "（最新）" : ""}
                    </option>
                  ))}
                </select>
              )}
            </label>
          </div>
          <Note>
            {custom
              ? saved
                ? "自定义配置已保存到当前页面内存。"
                : chosenCustom
                  ? `当前自定义配置：${chosenCustom.profile.name}，来源：${chosenCustom.profile.source}。选择后加载对应数据集与参数。`
                  : "暂无自定义配置，请先在测评配置中创建。"
              : `当前选择 ${evaluationVersion} 标准配置，官方参数只读。版本和参数均为本地示例。`}
          </Note>
          {custom && (
            <button
              disabled={!chosenCustom}
              onClick={() => {
                setDraft([...selected]);
                setActive(selected[0] || "");
                setDraftParams(structuredClone(params));
                setSaveAsNew(false);
                setNewConfigName("");
                setNewVersionName("");
                setDrawer(true);
              }}
            >
              编辑自定义配置
            </button>
          )}
        </section>
        <section className="console-step">
          <h3 className="console-step-title">
            <span className="step-number">3</span>测评数据集
          </h3>
          <div className="dataset-selection-toolbar">
            <input
              aria-label="搜索可选数据集"
              placeholder="搜索数据集"
              value={datasetSearch}
              onChange={(e) => setDatasetSearch(e.target.value)}
            />
            <label>
              <input
                type="checkbox"
                aria-label="全选当前数据集"
                checked={
                  visibleDatasets.length > 0 &&
                  visibleDatasets.every((d) => selected.includes(d))
                }
                disabled={!visibleDatasets.length}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? Array.from(new Set([...selected, ...visibleDatasets]))
                      : selected.filter((d) => !visibleDatasets.includes(d)),
                  )
                }
              />
              全选当前
            </label>
            <span>已选 {selected.length} 个</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>选择</th>
                  <th>数据集类型</th>
                  <th>数据集</th>
                  <th>数据范围</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleDatasets.map((d) => (
                  <tr key={d}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.includes(d)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, d]
                              : selected.filter((x) => x !== d),
                          )
                        }
                      />
                    </td>
                    <td>
                      {datasetTypes.find((t) => t.items.includes(d))?.label}
                    </td>
                    <td>{d}</td>
                    <td>
                      <select
                        aria-label={`${d}范围`}
                        value={scopes[d]}
                        onChange={(e) =>
                          setScopes({ ...scopes, [d]: e.target.value })
                        }
                      >
                        <option>全量</option>
                        <option>Lite</option>
                      </select>
                    </td>
                    <td>
                      <div className="inline">
                        <button className="link" onClick={() => setView(d)}>
                          查看参数
                        </button>
                        <button
                          className="link"
                          disabled={!custom}
                          onClick={() => {
                            setDraft([...selected]);
                            setActive(d);
                            setDraftParams(structuredClone(params));
                            setSaveAsNew(false);
                            setNewConfigName("");
                            setNewVersionName("");
                            setDrawer(true);
                          }}
                        >
                          编辑参数
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!visibleDatasets.length && (
            <div className="empty">没有匹配的数据集</div>
          )}
          <Note>
            每个数据集独立选择全量 / Lite；Lite 适用场景与具体样本范围待确认。
          </Note>
        </section>
      </div>
      <section className="card stack summary">
        <h2>本次测评</h2>
        <h3>{model}</h3>
        <span>
          配置：{custom ? "自定义配置" : "标准配置"} ·{" "}
          {custom ? chosenCustom?.version || "未选择" : evaluationVersion} ·{" "}
          {model === "demo-vlm-001" ? "RC" : "Release"}
        </span>
        <fieldset className="run-mode-options">
          <legend>运行方式</legend>
          <div className="run-mode-choices">
            {["串行", "并行"].map((mode) => (
              <label key={mode} className={run === mode ? "is-selected" : ""}>
                <input
                  type="radio"
                  name="evaluation-run-mode"
                  value={mode}
                  checked={run === mode}
                  onChange={() => setRun(mode)}
                />
                <span>{mode}</span>
              </label>
            ))}
          </div>
          <p className="run-mode-description">
            {run === "串行"
              ? "按数据集依次执行。"
              : "同时执行多个数据集，并行上限与失败策略待确认。"}
          </p>
        </fieldset>
        <section className="summary-scope">
          <div className="spread">
            <h3>测评范围</h3>
            <strong>{selected.length} 个数据集</strong>
          </div>
          <p>
            全量 {selected.filter((d) => scopes[d] === "全量").length} · Lite{" "}
            {selected.filter((d) => scopes[d] === "Lite").length}
          </p>
          <details>
            <summary>展开选择明细</summary>
            <div className="summary-dataset-list">
              {selected.map((d) => (
                <div key={d}>
                  <div className="spread">
                    <b>{d}</b>
                    <span>{scopes[d]}</span>
                  </div>
                  <small>预计耗时：暂无可靠估算</small>
                </div>
              ))}
              {!selected.length && <p>尚未选择数据集</p>}
            </div>
          </details>
        </section>
        <div className="total-duration" role="status" aria-live="polite">
          <div className="total-duration-heading">
            <span>测评预计总耗时</span>
            <span className="badge">
              {run} · {selected.length} 个数据集
            </span>
          </div>
          <strong>{totalDuration}</strong>
          <p>
            {run === "串行"
              ? "计算口径：所选数据集预计耗时之和。"
              : "计算口径：所选数据集同时开始，取最长预计耗时；受实际并发资源限制。"}
          </p>
          {!!missingEstimates && (
            <small>
              {missingEstimates} 个数据集缺少可靠估算，暂不提供总时长。
            </small>
          )}
          <small>不含排队及报告分析耗时。</small>
        </div>
        <p>分析预计耗时：暂无可靠估算</p>
        <div className="console-submit-status" role="status">
          {!selected.length
            ? "请至少选择一个数据集"
            : custom && !chosenCustom
              ? "请先选择自定义配置"
              : "模型未连接，请先完成连接测试。"}
          <small>当前为静态预览，连接测试与提交仅展示说明。</small>
        </div>
        <button
          className="primary"
          disabled={!selected.length || (custom && !chosenCustom)}
          onClick={() => notify("静态预览：未创建真实任务。运行方式：" + run)}
        >
          发起测评
        </button>
      </section>
      {view && (
        <div className="dataset-overlay" onClick={() => setView(null)}>
          <section
            className="dataset-dialog readable-config-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={`${view} 数据集参数`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="spread">
              <div>
                <h3>{view} 数据集参数</h3>
                <p className="muted">本次测评使用的参数，仅供查看。</p>
              </div>
              <span className="badge neutral">只读</span>
            </div>
            <div className="readable-config-scroll">
              <dl className="readable-config-list">
                {[
                  [
                    "测评范围",
                    scopes[view],
                    scopes[view] === "Lite"
                      ? "使用部分样本进行测评；具体子集与样本数量待确认。"
                      : "使用该配置所定义的完整样本范围。",
                  ],
                  [
                    "回答长度上限",
                    `${params[view].output.toLocaleString()} Token`,
                    "限制每次回答最多生成多少内容。Token 是模型处理文字的计量单位，不等同于汉字数。",
                  ],
                  [
                    "同时处理数量",
                    `${params[view].concurrency} 个请求`,
                    "最多同时向模型发送的请求数；实际处理能力取决于服务资源。",
                  ],
                  [
                    "回答随机性",
                    params[view].temperature,
                    "控制生成内容的随机程度。通常数值越低，回答越稳定；效果取决于模型。",
                  ],
                  [
                    "候选内容范围",
                    params[view].top_p,
                    "控制模型从多大概率范围内选择后续内容。数值越接近 1，候选范围通常越广。",
                  ],
                ].map(([label, value, help]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>
                      <strong>{value}</strong>
                      <p>{help}</p>
                    </dd>
                  </div>
                ))}
              </dl>
              <details className="raw-config-details">
                <summary>查看原始配置（JSON）</summary>
                <pre className="snapshot">
                  {JSON.stringify(
                    { ...params[view], scope: scopes[view] },
                    null,
                    2,
                  )}
                </pre>
              </details>
              <p className="config-example-note">
                参数为本地示例，不代表推荐设置或真实执行结果。
              </p>
            </div>
            <div className="readable-config-footer">
              <button autoFocus onClick={() => setView(null)}>
                关闭
              </button>
            </div>
          </section>
        </div>
      )}
      {drawer && (
        <ConfigurationDrawer>
          <h2>自定义配置</h2>
          <div className="workflow-grid">
            <aside className="workflow-datasets">
              <DatasetTree
                items={names}
                selected={draft}
                active={active}
                onSelect={(items) => {
                  setDraft(items);
                  if (!items.includes(active)) setActive(items[0] || "");
                }}
                onActive={(d) => {
                  if (!draft.includes(d)) setDraft([...draft, d]);
                  setActive(d);
                }}
              />
            </aside>
            <ParameterCards
              items={draft}
              active={active}
              params={draftParams}
              onChange={setDraftParams}
            />
          </div>
          <div className="config-save-panel">
            <h3>保存方式</h3>
            <div className="inline">
              <label>
                <input
                  type="radio"
                  name="console-save-mode"
                  checked={!saveAsNew}
                  onChange={() => setSaveAsNew(false)}
                />{" "}
                仅用于本次测评
              </label>
              <label>
                <input
                  type="radio"
                  name="console-save-mode"
                  checked={saveAsNew}
                  onChange={() => setSaveAsNew(true)}
                />{" "}
                保存为新配置
              </label>
            </div>
            {saveAsNew && (
              <div className="config-save-fields">
                <label>
                  <span>配置名称 *</span>
                  <input
                    aria-label="新配置名称"
                    required
                    value={newConfigName}
                    onChange={(e) => setNewConfigName(e.target.value)}
                    placeholder="例如：多模态专项验证"
                  />
                </label>
                <label>
                  <span>版本名称 *</span>
                  <input
                    aria-label="新配置版本名称"
                    required
                    value={newVersionName}
                    onChange={(e) => setNewVersionName(e.target.value)}
                    placeholder="例如：初版"
                  />
                </label>
              </div>
            )}
            <p className="config-save-help">
              {saveAsNew
                ? "保存到后端自定义配置列表并自动选用，不覆盖原配置。"
                : "仅应用到本次测评，不修改已有配置。"}
            </p>
          </div>
          <div className="actions">
            <button onClick={() => setDrawer(false)}>取消</button>
            <button
              disabled={
                !draft.length ||
                (saveAsNew && (!newConfigName.trim() || !newVersionName.trim()))
              }
              className="primary"
              onClick={async () => {
                if (saveAsNew) {
                  const name = newConfigName.trim();
                  const version = newVersionName.trim();
                  if (profiles.some((p) => !p.official && p.name === name)) {
                    notify("配置名称已存在，请更换名称。");
                    return;
                  }
                  const id = `custom-${crypto.randomUUID()}`;
                  let persistedVersion: number;
                  try {
                    const response = await fetch("/api/autoeval/v1/test-configs", {
                      method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ config_key: id, display_name: name,
                        version_label: version, expected_version: 0,
                        items: Object.fromEntries(draft.map((key) => [key, draftParams[key]])) }),
                    });
                    const body = await response.json();
                    if (!response.ok) throw new Error(body.error?.message || "配置保存失败");
                    persistedVersion = body.data.version;
                  } catch (error) {
                    notify(error instanceof Error ? error.message : "配置未保存"); return;
                  }
                  setProfiles([
                    ...profiles,
                    {
                      id,
                      name,
                      source: "后端持久化",
                      persistedVersion,
                      modelId: model,
                      model:
                        model === "demo-vlm-001"
                          ? "Demo Vision A"
                          : "Demo Vision B",
                      official: false,
                      versions: [version],
                      items: [...draft],
                      data: { [version]: structuredClone(draftParams) },
                    },
                  ]);
                  setCustomKey(id + "::" + version);
                }
                setSelected(draft);
                setParams(draftParams);
                setScopes({
                  ...scopes,
                  ...Object.fromEntries(
                    draft.map((d) => [d, draftParams[d].scope]),
                  ),
                });
                setSaved(true);
                setDrawer(false);
                notify(
                  saveAsNew
                    ? "已保存到后端并自动选用。"
                    : "已应用到本次测评，未修改原配置。",
                );
              }}
            >
              {saveAsNew ? "保存新配置并返回" : "应用并返回"}
            </button>
          </div>
        </ConfigurationDrawer>
      )}
    </div>
  );
}
export function DatasetExecution({
  task,
  model,
  version,
  state,
  items,
}: {
  task: string;
  model: string;
  version: string;
  state: string;
  items: string[];
}) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [tab, setTab] = useState("执行进度");
  const [active, setActive] = useState(items[0]);
  const [filter, setFilter] = useState("全部结果");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(null);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [expanded]);

  const running = state === "执行中";
  const executions = items.map((name, i) => {
    const processed = running ? [100, 68, 0][i] || 0 : 100;
    const errors = state === "部分成功" && i === items.length - 1 ? 5 : 0;
    const failed = processed ? (i === 0 ? 2 : 3) : 0;
    return {
      name,
      processed,
      errors,
      failed,
      passed: Math.max(0, processed - failed - errors),
      pending: 100 - processed,
      status: errors
        ? "执行异常"
        : processed === 100
          ? "已完成"
          : processed
            ? "执行中"
            : "待执行",
      duration: processed ? (i === 0 ? "12 分钟" : "9 分钟") : "—",
      updated: processed ? "2026-11-09 14:20:18" : "—",
    };
  });
  const selected = executions.find((d) => d.name === active) || executions[0];
  if (!selected)
    return (
      <section className="card">
        <p>暂无数据集</p>
      </section>
    );
  const overall = Math.round(
    executions.reduce((n, d) => n + d.processed, 0) / executions.length,
  );
  const totalErrors = executions.reduce((n, d) => n + d.errors, 0);
  const cases = Array.from({ length: 100 }, (_, i) => {
    const id = `${selected.name}-#${String(i + 1).padStart(3, "0")}`;
    const result =
      i >= selected.processed
        ? "待处理"
        : i < selected.errors
          ? "执行异常"
          : i < selected.errors + selected.failed
            ? "判分未通过"
            : "判分通过";
    return {
      id,
      result,
      duration:
        result === "待处理" ? "—" : `${(1.2 + (i % 9) * 0.3).toFixed(1)} s`,
      message:
        result === "执行异常"
          ? "请求超时，未获得有效响应"
          : result === "判分未通过"
            ? "模型作答与标准答案不一致"
            : result === "待处理"
              ? "尚未执行"
              : "作答与标准答案一致",
    };
  });
  const filtered = cases.filter(
    (c) =>
      (filter === "全部结果" || c.result === filter) &&
      (c.id + " " + c.message).toLowerCase().includes(query.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 5));
  const current = Math.min(page, pages);
  const switchDataset = (name: string) => {
    setDetailOpen(true);
    setActive(name);
    setFilter("全部结果");
    setQuery("");
    setPage(1);
    setExpanded(null);
  };
  return (
    <section className="card stack execution-detail">
      <div className="execution-heading">
        <h2>{task}</h2>
        <span
          className={`case-status ${running ? "running" : totalErrors ? "error" : "passed"}`}
        >
          {state}
        </span>
        <span className="badge">静态示例</span>
      </div>
      <div className="execution-meta">
        <span>
          模型 <b>{model}</b>
        </span>
        <span>
          配置 <b>v1.3 · {version}</b>
        </span>
        <span>
          运行方式 <b>串行</b>
        </span>
        <span>
          开始时间 <b>2026-11-09 14:00</b>
        </span>
        <span>
          结束时间 <b>{running ? "尚未结束" : "2026-11-09 14:21"}</b>
        </span>
      </div>
      <div className="tabs">
        {["执行进度", "配置快照"].map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "配置快照" ? (
        <>
          <Note>只读原始结构示例，凭据已脱敏；尚未连接实际执行器。</Note>
          <pre className="snapshot">
            {JSON.stringify(
              {
                task_id: task,
                model: { name: model, api_key: "***" },
                config_version: "v1.3",
                export_version: version,
                run_mode: "serial",
                datasets: items.map((name) => ({
                  name,
                  scope: "full",
                  max_out_len: 2048,
                  generation_kwargs: { temperature: 0.6, top_p: 0.95 },
                })),
              },
              null,
              2,
            )}
          </pre>
        </>
      ) : (
        <>
          {!detailOpen && (
            <section className="task-overview" aria-label="任务总览">
              <div className="spread">
                <h3>任务总览</h3>
                <span className="muted">
                  共 {executions.length} 个数据集 · 点击查看执行详情
                </span>
              </div>
              <div className="overall-execution">
                <div>
                  <span>整体进度</span>
                  <strong>{overall}%</strong>
                  <progress max="100" value={overall} />
                </div>
                <span>
                  已完成数据集{" "}
                  <b>
                    {executions.filter((d) => d.processed === 100).length} /{" "}
                    {items.length}
                  </b>
                </span>
                <span>
                  实际耗时 <b>21 分钟</b>
                </span>
                <span>
                  最后更新 <b>14:20:18</b>
                </span>
              </div>
              <div className="task-overview-stats">
                {[
                  ["Case 总数", executions.length * 100, ""],
                  [
                    "已处理",
                    executions.reduce((n, d) => n + d.processed, 0),
                    "",
                  ],
                  [
                    "判分通过",
                    executions.reduce((n, d) => n + d.passed, 0),
                    "passed",
                  ],
                  [
                    "判分未通过",
                    executions.reduce((n, d) => n + d.failed, 0),
                    "failed",
                  ],
                  ["执行异常", totalErrors, "error"],
                  [
                    "待处理",
                    executions.reduce((n, d) => n + d.pending, 0),
                    "pending",
                  ],
                ].map(([label, value, tone]) => (
                  <div key={label} className={`case-stat ${tone}`}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <div className="table-wrap">
                <table className="task-overview-table">
                  <thead>
                    <tr>
                      {[
                        "数据集",
                        "状态",
                        "进度 / 已处理",
                        "判分通过",
                        "判分未通过",
                        "执行异常",
                        "耗时",
                        "最后更新",
                        "操作",
                      ].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {executions.map((d) => (
                      <tr key={d.name}>
                        <td>
                          <b>{d.name}</b>
                        </td>
                        <td>
                          <span
                            className={`case-status ${d.errors ? "error" : d.processed === 100 ? "passed" : d.processed ? "running" : "pending"}`}
                          >
                            {d.status}
                          </span>
                        </td>
                        <td>
                          {d.processed}% · {d.processed}/100
                        </td>
                        <td>{d.passed}</td>
                        <td>{d.failed}</td>
                        <td>{d.errors}</td>
                        <td>{d.duration}</td>
                        <td>{d.processed ? "14:20:18" : "—"}</td>
                        <td>
                          <button
                            className="link"
                            onClick={() => switchDataset(d.name)}
                          >
                            查看明细
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="task-overview-bottom">
                <span>
                  任务异常：
                  {totalErrors
                    ? `${totalErrors} 个 case 执行异常，详见对应数据集`
                    : "无执行异常"}
                </span>
                <span>
                  报告状态：
                  {running ? "待生成（测评进行中）" : "已生成（示例）"}
                </span>
                <span>预计总耗时：暂无可靠估算</span>
              </div>
            </section>
          )}
          {detailOpen && (
            <div className="task-dataset-view">
              <div className="report-navigation-bar">
                <button
                  className="link"
                  onClick={() => {
                    setDetailOpen(false);
                    setExpanded(null);
                  }}
                >
                  返回任务总览
                </button>
                <label>
                  切换数据集
                  <select
                    aria-label="切换任务数据集"
                    value={selected.name}
                    onChange={(e) => switchDataset(e.target.value)}
                  >
                    {executions.map((d) => (
                      <option key={d.name}>{d.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="execution-body task-single-dataset">
                <div className="stack case-content">
                  <div className="spread">
                    <h3>{selected.name}</h3>
                    <span className="muted">{selected.status}</span>
                  </div>
                  <div className="execution-meta">
                    <span>
                      已处理 <b>{selected.processed} / 100</b>
                    </span>
                    <span>
                      耗时 <b>{selected.duration}</b>
                    </span>
                    <span>
                      更新时间 <b>{selected.updated}</b>
                    </span>
                  </div>
                  <div className="dataset-progress-inline">
                    <progress
                      aria-label="当前数据集执行进度"
                      max="100"
                      value={selected.processed}
                    />
                    <strong>{selected.processed}%</strong>
                    <span>
                      {selected.errors
                        ? `${selected.errors} 个执行异常，请在下方筛选排查`
                        : selected.processed === 0
                          ? "等待执行"
                          : "无执行异常"}
                    </span>
                  </div>
                  <div className="case-statistics">
                    {[
                      ["判分通过", selected.passed, "passed"],
                      ["判分未通过", selected.failed, "failed"],
                      ["执行异常", selected.errors, "error"],
                      ["待处理", selected.pending, "pending"],
                    ].map(([label, count, tone]) => (
                      <div key={label} className={`case-stat ${tone}`}>
                        <span>{label}</span>
                        <strong>{count}</strong>
                      </div>
                    ))}
                  </div>
                  <h3 className="case-list-heading">Case 明细</h3>
                  {!selected.processed ? (
                    <div className="empty">尚未开始，暂无 case 结果或日志</div>
                  ) : (
                    <>
                      <div className="filters">
                        <select
                          aria-label="case 结果筛选"
                          value={filter}
                          onChange={(e) => {
                            setFilter(e.target.value);
                            setPage(1);
                            setExpanded(null);
                          }}
                        >
                          {[
                            "全部结果",
                            "判分通过",
                            "判分未通过",
                            "执行异常",
                            "待处理",
                          ].map((f) => (
                            <option key={f}>{f}</option>
                          ))}
                        </select>
                        <input
                          aria-label="搜索 case"
                          placeholder="搜索 case ID / 错误信息"
                          value={query}
                          onChange={(e) => {
                            setQuery(e.target.value);
                            setPage(1);
                            setExpanded(null);
                          }}
                        />
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              {[
                                "Case ID",
                                "执行状态",
                                "判分结果",
                                "耗时",
                                "摘要",
                                "操作",
                              ].map((h) => (
                                <th key={h}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {filtered
                              .slice((current - 1) * 5, current * 5)
                              .map((c) => (
                                <tr key={c.id}>
                                  <td>{c.id}</td>
                                  <td>
                                    {c.result === "待处理"
                                      ? "待执行"
                                      : c.result === "执行异常"
                                        ? "执行异常"
                                        : "已完成"}
                                  </td>
                                  <td>
                                    <span
                                      className={`case-status ${c.result === "判分通过" ? "passed" : c.result === "判分未通过" ? "failed" : c.result === "执行异常" ? "error" : "pending"}`}
                                    >
                                      {c.result === "执行异常" ||
                                      c.result === "待处理"
                                        ? "—"
                                        : c.result}
                                    </span>
                                  </td>
                                  <td>{c.duration}</td>
                                  <td>{c.message}</td>
                                  <td>
                                    <button
                                      className="link"
                                      disabled={c.result === "待处理"}
                                      onClick={() => setExpanded(c.id)}
                                    >
                                      查看
                                    </button>
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                        {!filtered.length && (
                          <div className="empty">没有符合条件的 case</div>
                        )}
                      </div>
                      <div className="pagination">
                        <span>
                          共 {filtered.length} 条 · 第 {current} / {pages} 页
                        </span>
                        <button
                          disabled={current === 1}
                          onClick={() => {
                            setPage(current - 1);
                            setExpanded(null);
                          }}
                        >
                          上一页
                        </button>
                        <button
                          disabled={current === pages}
                          onClick={() => {
                            setPage(current + 1);
                            setExpanded(null);
                          }}
                        >
                          下一页
                        </button>
                      </div>
                      {expanded &&
                        createPortal(
                          <div
                            className="case-drawer-backdrop"
                            onClick={() => setExpanded(null)}
                          >
                            <section
                              className="case-drawer"
                              role="dialog"
                              aria-modal="true"
                              aria-label="Case 详情"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <div className="spread">
                                <h2>Case 详情</h2>
                                <button
                                  autoFocus
                                  onClick={() => setExpanded(null)}
                                >
                                  关闭
                                </button>
                              </div>
                              <p className="muted">
                                {task} / {selected.name} / {expanded}
                              </p>
                              <div className="logs">
                                <div>
                                  {expanded} · 完整日志与输入响应（示例）
                                </div>
                                <pre>{`任务：${task} / 数据集：${selected.name}
Case：${expanded}
输入：示例评测问题（完整内容占位，未连接真实样本）
响应：${cases.find((c) => c.id === expanded)?.result === "执行异常" ? "无响应" : "示例模型作答"}
判定：${cases.find((c) => c.id === expanded)?.message}
凭据：***`}</pre>
                              </div>
                            </section>
                          </div>,
                          document.body,
                        )}
                    </>
                  )}
                  <p className="muted">
                    判分未通过属于有效测评结果；请求超时等单独计为执行异常。当前数量、耗时和日志均为示例。
                  </p>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
