import { useEffect, useState } from "react";
import { apiGetPage } from "../services/api";
import { OffsetPagination, REGISTRY_PAGE_SIZE } from "./OffsetPagination";

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
  const [modelOffset, setModelOffset] = useState(0);
  const [modelNext, setModelNext] = useState<number | null>(null);
  const [targetOffset, setTargetOffset] = useState(0);
  const [targetNext, setTargetNext] = useState<number | null>(null);
  const [versionId, setVersionId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [remoteModel, setRemoteModel] = useState("deepseek-flash");
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async (modelPage = modelOffset, targetPage = targetOffset) => {
    const [m, t] = await Promise.all([
      apiGetPage<Model[]>(`/models?offset=${modelPage}&limit=${REGISTRY_PAGE_SIZE}`),
      apiGetPage<Target[]>(`/target-bindings?offset=${targetPage}&limit=${REGISTRY_PAGE_SIZE}`),
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
  return <details className="card stack" aria-label="真实服务绑定">
    <summary>模型服务与连接检测</summary>
    <p>连接检测只查询模型列表，不发送生成请求。成功不代表测评已启用。</p>
    <label>已登记模型<select aria-label="服务绑定模型" defaultValue="" onChange={async e => {
      setVersionId(""); setVersions([]);
      if (!e.target.value) return;
      try { setVersions(await api<Version[]>(`/models/${e.target.value}/versions`)); }
      catch { setMessage("读取模型版本失败"); }
    }}><option value="">请选择</option>{models.map(m => <option key={m.id} value={m.id}>{m.model_id}</option>)}</select></label>
    <OffsetPagination label="模型" offset={modelOffset} nextOffset={modelNext} disabled={busy}
      onChange={(offset) => { setVersionId(""); setVersions([]); setModelOffset(offset); }} />
    <label>模型版本<select aria-label="服务绑定模型版本" value={versionId} onChange={e => setVersionId(e.target.value)}>
      <option value="">请选择</option>{versions.map(v => <option key={v.id} value={v.id}>{v.version}</option>)}
    </select></label>
    <label>API地址<input aria-label="真实API地址" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} /></label>
    <label>远程模型名<input aria-label="远程模型名" value={remoteModel} onChange={e => setRemoteModel(e.target.value)} /></label>
    <label>API Key<input aria-label="真实API Key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></label>
    <button disabled={busy || !key || !versionId} onClick={() => perform(async () => {
      const credential = await api<{ credential_ref: string }>("/credentials", { value: key });
      setKey("");
      const target = await api<{ id: string }>("/target-bindings", {
        model_version_id: versionId, base_url: baseUrl, remote_model: remoteModel,
        credential_ref: credential.credential_ref,
      });
      await refresh(); setTargetId(target.id); setMessage("服务绑定已保存，尚未检测。");
    })}>保存服务绑定</button>
    <label>已保存服务<select aria-label="已保存真实服务" value={targetId} onChange={e => { setTargetId(e.target.value); setMessage(""); }}>
      <option value="">请选择</option>{targets.map(t => <option key={t.id} value={t.id}>{t.remote_model} · {t.base_url} · {t.id.slice(0, 8)}</option>)}
    </select></label>
    <OffsetPagination label="服务" offset={targetOffset} nextOffset={targetNext} disabled={busy}
      onChange={(offset) => { setTargetId(""); setTargetOffset(offset); }} />
    <button disabled={busy || !targetId} onClick={() => perform(async () => {
      const result = await api<{ outcome: string; details: { models?: string[]; http_status?: number } }>(`/targets/${targetId}/connection-tests`, {});
      setMessage(result.outcome === "matched" ? "鉴权与目标模型匹配成功；未测试生成，测评尚未启用。"
        : `连接检测：${result.outcome}${result.details.http_status ? `（HTTP ${result.details.http_status}）` : ""}`);
    })}>检测已保存服务</button>
    <button disabled={busy} onClick={() => perform(refresh)}>刷新服务列表</button>
    {targetId && <p><a href={`#evaluate?target=${encodeURIComponent(targetId)}`}>使用此服务创建探索测评</a>（进入后加载模型默认配置；提交前需确认资源，不会自动调用模型）</p>}
    <p role="status">{message}</p>
  </details>;
}
