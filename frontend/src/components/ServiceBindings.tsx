import { SearchableSelect } from "./SearchableSelect";
import { useEffect, useState } from "react";
import { apiGetOptions } from "../services/api";
import { REGISTRY_PAGE_SIZE } from "./OffsetPagination";

type Model = { id: string; model_id: string };
type Version = { id: string; version: string };
type Target = { id: string; remote_model: string; base_url: string };
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || "服务配置请求失败");
  return result.data;
}
export function ServiceBindings() {
  const [models, setModels] = useState<Model[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [modelOffset] = useState(0);
  const [, setModelNext] = useState<number | null>(null);
  const [targetOffset] = useState(0);
  const [, setTargetNext] = useState<number | null>(null);
  const [versionId, setVersionId] = useState("");
  const [, setTargetId] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [remoteModel, setRemoteModel] = useState("deepseek-flash");
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async (modelPage = modelOffset, targetPage = targetOffset) => {
    const [m, t] = await Promise.all([
      apiGetOptions<Model[]>(`/models?offset=${modelPage}&limit=${REGISTRY_PAGE_SIZE}`),
      apiGetOptions<Target[]>(`/target-bindings?offset=${targetPage}&limit=${REGISTRY_PAGE_SIZE}`),
    ]);
    setModels(m.data); setModelNext(m.next_offset);
    setTargets(t.data); setTargetNext(t.next_offset);
  };
  useEffect(() => { refresh().catch(() => setMessage("服务绑定暂不可用")); }, [modelOffset, targetOffset]);
  const perform = async (fn: () => Promise<void>) => {
    setBusy(true); setMessage("");
    try { await fn(); } catch (error) { setMessage(error instanceof Error ? error.message : "请求失败"); }
    finally { setBusy(false); }
  };
  return <section className="card resource-management-form resource-fields-grid" aria-label="模型服务绑定">
    <h3>模型服务与连接检测</h3>
    <p>连接检测只查询模型列表，不发送生成请求。成功不代表测评已启用。</p>
    <label>模型标识<SearchableSelect aria-label="服务绑定模型" defaultValue="" onChange={async e => {
      setVersionId(""); setVersions([]);
      if (!e.target.value) return;
      try { setVersions(await api<Version[]>(`/models/${e.target.value}/versions`)); }
      catch { setMessage("读取模型版本失败"); }
    }}><option value="">请选择</option>{models.map(m => <option key={m.id} value={m.id}>{m.model_id}</option>)}</SearchableSelect></label>
    <label>模型版本<SearchableSelect aria-label="服务绑定模型版本" value={versionId} onChange={e => setVersionId(e.target.value)}>
      <option value="">请选择</option>{versions.map(v => <option key={v.id} value={v.id}>{v.version}</option>)}
    </SearchableSelect></label>
    <label className="field-wide">API地址<input aria-label="真实API地址" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} /></label>
    <label>远程模型名<input aria-label="远程模型名" value={remoteModel} onChange={e => setRemoteModel(e.target.value)} /></label>
    <label className="field-wide">API Key<input aria-label="真实API Key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></label>
    <button disabled={busy || !key || !versionId} onClick={() => perform(async () => {
      const credential = await api<{ credential_ref: string }>("/credentials", { value: key });
      setKey("");
      const target = await api<{ id: string }>("/target-bindings", {
        model_version_id: versionId, base_url: baseUrl, remote_model: remoteModel,
        credential_ref: credential.credential_ref,
      });
      await refresh(); setTargetId(target.id); setMessage("服务绑定已保存，尚未检测。");
    })}>保存服务绑定</button>
    <div className="saved-service-list"><div className="spread"><h3>已保存服务</h3><button disabled={busy} onClick={() => perform(refresh)}>刷新列表</button></div>
      {!targets.length && <p className="muted">暂无已保存服务</p>}
      {targets.map((target) => <article key={target.id}><b>{target.remote_model}</b><p>{target.base_url}</p><div className="inline"><button disabled={busy} onClick={() => perform(async () => {
        const result = await api<{ outcome: string; details: { http_status?: number } }>(`/targets/${target.id}/connection-tests`, {});
        setMessage(`${target.remote_model}：${result.outcome === "matched" ? "鉴权与目标模型匹配成功（未调用生成）" : result.outcome}`);
      })}>检测连接</button><a href={`#evaluate?target=${encodeURIComponent(target.id)}`}>使用此服务</a></div></article>)}
    </div>
    <p role="status">{message}</p>
  </section>;
}
