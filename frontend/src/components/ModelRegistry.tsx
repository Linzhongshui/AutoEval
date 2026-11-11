import { isTestModel, isModelScopeId } from "../services/modelIdentities";
import { SearchableSelect } from "./SearchableSelect";
import { ModelIdentifierSelect } from "./ModelIdentifierSelect";
import { useEffect, useState } from "react";
import { apiGetOptions } from "../services/api";
import { REGISTRY_PAGE_SIZE } from "./OffsetPagination";

type Params = { output: number; concurrency: number; temperature: number; top_p: number; scope: string };
type RegisteredModel = { id: string; model_id: string; name: string;
  default_config_version_id: string | null; binding_revision: number };
type Config = { id: string; display_name: string; version_label: string };
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || "请求失败");
  return body.data;
}
export function ModelRegistry({ onApply }: {
  onApply: (modelId: string, items: Record<string, Params>, configKey: string, versionLabel: string) => void;
}) {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [modelOffset] = useState(0);
  const [, setModelNext] = useState<number | null>(null);
  const [configOffset] = useState(0);
  const [, setConfigNext] = useState<number | null>(null);
  const [selected, setSelected] = useState("");
  const [configId, setConfigId] = useState("");
  const [modelId, setModelId] = useState("");
  const [modelName, setModelName] = useState("");
  const [version, setVersion] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async (modelPage = modelOffset, configPage = configOffset) => {
    const [m, c] = await Promise.all([
      apiGetOptions<RegisteredModel[]>(`/models?offset=${modelPage}&limit=${REGISTRY_PAGE_SIZE}`),
      apiGetOptions<Config[]>(`/test-configs?offset=${configPage}&limit=${REGISTRY_PAGE_SIZE}`),
    ]);
    setModels(m.data.filter((row) => !isTestModel(row.model_id) && isModelScopeId(row.model_id))); setModelNext(m.next_offset);
    setConfigs(c.data); setConfigNext(c.next_offset);
  };
  useEffect(() => { refresh().catch(() => setMessage("模型登记服务不可用，请启动后端与数据库后刷新。")); }, [modelOffset, configOffset]);
  const perform = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setMessage("");
    try { await action(); } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败");
    } finally { setBusy(false); }
  };
  return <section className="model-registry" aria-label="模型与默认配置">

    <p className="muted registry-intro">登记模型后配置调用服务，并绑定默认测评配置。</p><section className="registry-section"><h3>登记模型</h3>
    <div className="registry-create-grid">
      <label className="registry-identifier">模型标识<ModelIdentifierSelect value={modelId} onChange={(id) => { setModelId(id); setModelName(id.split("/").pop() || id); }} disabled={busy} /></label>
      <label>名称<input aria-label="登记模型名称" value={modelName} onChange={e => setModelName(e.target.value)} /></label>
      <label>模型版本<input placeholder="例如：v1" aria-label="登记模型版本" value={version} onChange={e => setVersion(e.target.value)} /></label>
    </div>
    <div className="registry-actions"><button className="primary" disabled={busy || !modelId.trim() || !modelName.trim() || !version.trim()}
      onClick={() => perform(async () => {
        const model = await request<RegisteredModel>("/models", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: modelId.trim(), name: modelName.trim(), version: version.trim() }) });
        await refresh(); setSelected(model.id); setMessage("模型已登记，尚未配置调用服务。");
      })}>登记模型</button></div></section><section className="registry-section"><div className="spread"><h3>默认配置绑定</h3><button className="link" disabled={busy} onClick={() => perform(refresh)}>刷新列表</button></div><div className="registry-binding-grid"><div className="registry-binding-field">
    <label>已登记模型<SearchableSelect aria-label="已登记模型" value={selected} onChange={e => setSelected(e.target.value)}>
      <option value="">请选择</option>{models.map(m => <option key={m.id} value={m.id}>{m.model_id}{m.name !== m.model_id ? ` · ${m.name}` : ""}</option>)}
    </SearchableSelect></label>
    </div><div className="registry-binding-field"><label>默认配置版本<SearchableSelect aria-label="绑定默认配置版本" value={configId} onChange={e => setConfigId(e.target.value)}>
      <option value="">请选择</option>{configs.map(c => <option key={c.id} value={c.id}>{c.display_name} / {c.version_label}</option>)}
    </SearchableSelect></label>
    </div></div><div className="registry-actions"><button className="primary" disabled={busy || !selected || !configId} onClick={() => perform(async () => {
      const model = models.find(m => m.id === selected)!;
      await request(`/models/${selected}/default-test-config`, { method: "PUT",
        headers: { "Content-Type": "application/json", "If-Match": String(model.binding_revision) },
        body: JSON.stringify({ config_version_id: configId }) });
      await refresh(); setMessage("默认配置绑定已保存。");
    })}>保存默认绑定</button>
    <button disabled={busy || !selected} onClick={() => perform(async () => {
      const config = await request<{ model_id: string; config_key: string; version_label: string; items: Record<string, Params> }>(`/models/${selected}/default-test-config`);
      onApply(config.model_id, config.items, config.config_key, config.version_label); setMessage("已加载默认配置到当前表单；使用已保存服务的探索入口可创建真实任务。");
    })}>加载模型默认配置</button>
    </div></section>
    {message && <p className="notice" role="status">{message}</p>}
  </section>;
}
