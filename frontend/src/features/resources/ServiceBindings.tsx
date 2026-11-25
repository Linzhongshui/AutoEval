import { SSHServiceProbe } from "./SSHServiceProbe";
import { Cloud, Server } from "lucide-react";
import { serviceLabel, serviceLabels, type ServiceKind } from "./serviceKind";
import "./ModelServices.css";
import { isDebugModel, isModelScopeId, isTestModel } from "../catalog/modelIdentities";
import { SearchableSelect } from "../../shared/ui/SearchableSelect";
import { useEffect, useState } from "react";
import { apiGetOptions } from "../../shared/api";
import { REGISTRY_PAGE_SIZE } from "../../shared/constants";

type Model = { id: string; model_id: string; name: string };
type Version = { id: string; version: string };
type Target = { service_kind?: ServiceKind | null; id: string; remote_model: string; base_url: string };
type Entry = { entry: { model_name: string; conditions?: Record<string, unknown> } };
type StandardInput = { source_model: string };
type Choice = { value: string; label: string };
async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/autoeval/v1${path}`, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || "服务配置请求失败");
  return result.data;
}
export function ServiceBindings({ onUse }: { onUse?: (id: string) => void }) {
  const [models, setModels] = useState<Model[]>([]);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [modelOffset] = useState(0);
  const [, setModelNext] = useState<number | null>(null);
  const [targetOffset] = useState(0);
  const [, setTargetNext] = useState<number | null>(null);
  const [modelValue, setModelValue] = useState("");
  const [versionState, setVersionState] = useState<"idle" | "loading" | "error">("idle");
  const [versionId, setVersionId] = useState("");
  const [, setTargetId] = useState("");
  const [kind, setKind] = useState<ServiceKind>("local");
  const [baseUrl, setBaseUrl] = useState("");
  const [remoteModel, setRemoteModel] = useState("");
  const [key, setKey] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async (modelPage = modelOffset, targetPage = targetOffset) => {
    const [m, t, entries, standards] = await Promise.all([
      apiGetOptions<Model[]>(`/models?offset=${modelPage}&limit=${REGISTRY_PAGE_SIZE}`),
      apiGetOptions<Target[]>(`/target-bindings?offset=${targetPage}&limit=${REGISTRY_PAGE_SIZE}`),
      apiGetOptions<Entry[]>("/data-workbench/entries").catch(() => null),
      apiGetOptions<StandardInput[]>("/standard-inputs?revision=all").catch(() => null),
    ]);
    const registered = m.data.filter((model) => !isTestModel(model.model_id) && !isDebugModel(model.model_id, model.name));
    const known = new Set(m.data.map((model) => model.model_id));
    const pending = new Set<string>();
    for (const row of entries?.data ?? []) {
      const mapped = row.entry.conditions?.modelscope_model_id;
      const id = typeof mapped === "string" && isModelScopeId(mapped) ? mapped : row.entry.model_name;
      if (id && !known.has(id) && !isTestModel(id) && !isDebugModel(id)) pending.add(id);
    }
    for (const row of standards?.data ?? []) {
      const id = row.source_model;
      if (id && !known.has(id) && !isTestModel(id) && !isDebugModel(id)) pending.add(id);
    }
    setModels(registered); setModelNext(m.next_offset);
    setTargets(t.data); setTargetNext(t.next_offset);
    setChoices([
      ...registered.map((model) => ({ value: model.id, label: model.model_id })),
      ...[...pending].map((id) => ({ value: id, label: id })),
    ].sort((a, b) => a.label.localeCompare(b.label)));
  };
  useEffect(() => { refresh().catch(() => setMessage("服务绑定暂不可用")); }, [modelOffset, targetOffset]);
  const perform = async (fn: () => Promise<void>) => {
    setBusy(true); setMessage("");
    try { await fn(); } catch (error) { setMessage(error instanceof Error ? error.message : "请求失败"); }
    finally { setBusy(false); }
  };
  async function loadVersions(modelId: string) {
    setVersionState("loading");
    try {
      setVersions(await api<Version[]>(`/models/${modelId}/versions`));
      setVersionState("idle");
    } catch {
      setVersionState("error");
    }
  }

  function versionPrompt() {
    if (!modelValue) return "请先选择模型";
    if (versionState === "loading") return "正在读取版本…";
    if (versionState === "error") return "读取版本失败";
    if (versions.length) return "请选择模型版本";
    return busy ? "正在登记模型…" : "该模型暂无已登记版本";
  }

  return <section className="card resource-management-form resource-fields-grid" aria-label="模型服务绑定">
    <h3>接入模型推理服务</h3>
    <div role="group" aria-label="服务来源" className="service-methods">
      {(["local", "official"] as const).map(value => <button type="button" key={value}
        disabled={busy} aria-pressed={kind === value} onClick={() => {
          if (value === kind) return;
          setKind(value); setBaseUrl(""); setRemoteModel(""); setKey(""); setMessage("");
        }}>
        {value === "local" ? <Server size={20} /> : <Cloud size={20} />}
        <span><b>{serviceLabels[value]}</b><small>{value === "local" ? "连接团队部署的推理端点" : "连接模型厂商提供的 API"}</small></span>
      </button>)}
    </div>
    <p>选择平台模型及版本。选择尚未登记的模型时，系统会创建 v1 版本。</p>
    <label>模型标识<SearchableSelect aria-label="服务绑定模型" disabled={busy || versionState === "loading"} value={modelValue} onChange={async e => {
      const choice = e.target.value;
      setModelValue(choice); setVersionId(""); setVersions([]); setVersionState("idle");
      if (!choice) return;
      if (models.some((model) => model.id === choice)) {
        await loadVersions(choice);
        return;
      }
      setBusy(true); setMessage(`正在登记模型 ${choice}…`);
      try {
        const created = await api<{ id: string; version_id: string }>("/models", {
          model_id: choice, name: choice.split("/").pop() || choice, version: "v1",
        });
        setChoices((current) => current.map((item) => item.value === choice ? { value: created.id, label: choice } : item));
        setModelValue(created.id);
        setVersions([{ id: created.version_id, version: "v1" }]);
        setVersionId(created.version_id);
        await refresh();
        setMessage(`已自动登记模型 ${choice}（版本 v1），尚未绑定服务。`);
      } catch (error) { setMessage(error instanceof Error ? error.message : "模型登记失败"); }
      finally { setBusy(false); }
    }}><option value="">搜索并选择模型</option>{choices.map(choice => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</SearchableSelect></label>
    <label>模型版本<SearchableSelect aria-label="服务绑定模型版本" disabled={busy || !versions.length} value={versionId} onChange={e => setVersionId(e.target.value)}>
      <option value="">{versionPrompt()}</option>{versions.map(v => <option key={v.id} value={v.id}>{v.version}</option>)}
    </SearchableSelect></label>
    {versionState === "error" && <button type="button" onClick={() => void loadVersions(modelValue)}>重新读取版本</button>}
    <label className="field-wide">{kind === "local" ? "本地服务 Base URL" : "厂商 API Base URL"}<input type="url" placeholder={kind === "local" ? "https://inference.example.com/v1" : "例如 https://api.deepseek.com"} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} /></label>
    <p>使用已加入平台允许列表的 HTTPS 地址，填写模型列表和推理接口共用的基础路径。</p>
    <label>{kind === "local" ? "部署的模型名" : "厂商模型 ID"}<input placeholder={kind === "local" ? "部署时指定的服务模型名" : "厂商接口使用的模型标识"} value={remoteModel} onChange={e => setRemoteModel(e.target.value)} /></label>
    <label className="field-wide">{kind === "local" ? "本地服务访问密钥" : "厂商 API Key"}<input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} /></label>
    <button disabled={busy || !key || !versionId || !baseUrl.trim() || !remoteModel.trim()} onClick={() => perform(async () => {
      const credential = await api<{ credential_ref: string }>("/credentials", { value: key });
      setKey("");
      const target = await api<{ id: string }>("/target-bindings", {
        model_version_id: versionId, service_kind: kind, base_url: baseUrl.trim(), remote_model: remoteModel.trim(),
        credential_ref: credential.credential_ref,
      });
      await refresh(); setTargetId(target.id); setMessage("服务绑定已保存，尚未检测。");
    })}>保存服务绑定</button>
    <p role="status">{message}</p>
    <div className="saved-service-list"><div className="spread"><h3>已保存服务</h3><button disabled={busy} onClick={() => perform(refresh)}>刷新列表</button></div>
      <p className="muted">本地服务由测评执行环境访问；官方 API 可在此检测模型列表。</p>
      {!targets.length && <p className="muted">暂无已保存服务</p>}
      {targets.map((target) => <article className="saved-service-row" key={target.id}><div><b>{target.remote_model}</b> <small className="service-kind">{serviceLabel(target.service_kind)}</small><p>{target.base_url}</p></div><div className="inline">{target.service_kind === "local" ? <SSHServiceProbe targetId={target.id} /> : <button disabled={busy} onClick={() => perform(async () => {
        const result = await api<{ outcome: string; details: { http_status?: number } }>(`/targets/${target.id}/connection-tests`, {});
        setMessage(`${target.remote_model}：${result.outcome === "matched" ? "鉴权与目标模型匹配成功（未调用生成）" : result.outcome}`);
      })}>检测连接</button>}<button type="button" className="primary" onClick={() => onUse ? onUse(target.id) : location.assign(`#evaluate?target=${encodeURIComponent(target.id)}`)}>使用此服务</button></div></article>)}
    </div>
  </section>;
}
