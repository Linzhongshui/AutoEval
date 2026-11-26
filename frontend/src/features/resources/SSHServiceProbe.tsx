import { useState } from "react";
import { apiGetOptions, apiPost } from "../../shared/api";

type Resource = { id: string; binding_key: string; host: string; port: number; version: number };
const outcomes: Record<string, string> = {
  matched: "连接成功，已匹配部署的模型",
  model_not_found: "已连接，模型列表中没有该模型",
  connection_error: "节点无法连接模型服务，请检查网络与证书",
  ssh_error: "SSH 连接或节点探测程序执行失败",
  credential_unavailable: "凭据不可读取",
  invalid_response: "模型列表响应无效",
  upstream_error: "模型服务返回错误",
};

export function SSHServiceProbe({ targetId }: { targetId: string }) {
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [selected, select] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    setBusy(true);
    setMessage("");
    try {
      const page = await apiGetOptions<Resource[]>("/ssh-resources");
      setResources(page.data);
      if (!page.data.length) setMessage("请先在 SSH 资源池登记主机。");
    } catch { setMessage("SSH 资源加载失败，请重试。"); }
    finally { setBusy(false); }
  }

  async function probe() {
    const resource = resources?.find(row => row.id === selected);
    if (!resource) return;
    setBusy(true);
    setMessage("");
    try {
      const { outcome, details } = await apiPost<{ outcome: string; details: { http_status?: number } }>(
        `/targets/${targetId}/connection-tests`, { ssh_resource_id: selected },
      );
      setMessage(`${resource.binding_key} · ${outcomes[outcome] ?? outcome}${details.http_status ? ` (HTTP ${details.http_status})` : ""}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "检测失败"); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    {!resources?.length ? <button type="button" disabled={busy} onClick={() => void load()}>选择 SSH 主机检测</button> :
      <div className="inline">
        <select aria-label="连通性检测 SSH 主机" value={selected} disabled={busy}
          onChange={event => { select(event.target.value); setMessage(""); }}>
          <option value="">选择 SSH 主机</option>
          {resources.map(row => <option key={row.id} value={row.id}>{row.binding_key} · v{row.version} · {row.host}:{row.port}</option>)}
        </select>
        <button type="button" disabled={busy || !selected} onClick={() => void probe()}>从该主机检测</button>
      </div>}
    {message && <small role="status">{message}</small>}
  </div>;
}
