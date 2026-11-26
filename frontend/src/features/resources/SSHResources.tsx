import { Badge } from "../../shared/ui/Badge";
import { Card } from "../../shared/ui/Card";
import { TableWrap } from "../../shared/ui/TableWrap";
import { REGISTRY_PAGE_SIZE } from "../../shared/constants";
import { OffsetPagination } from "../../shared/ui/OffsetPagination";
import { useEffect, useState } from "react";
import { apiGetOptions, apiPost } from "../../shared/api";

type Resource = { id: string; binding_key: string; host: string; port: number; username: string; fingerprint: string; workdir: string; native_tool_root: string | null; native_bridge_sha256: string | null; native_lock_sha256: string | null; native_tool_revision: string | null };

const initialFields = { binding_key: "", host: "", port: "22", username: "", fingerprint: "", workdir: "" };

type Check = { passed: boolean; detail: string; time: string };

export function SSHResources({ adding: routeAdding, onAdd, onCancel, onSaved, onBack }: {
  adding?: boolean;
  onAdd?: () => void;
  onCancel?: () => void;
  onSaved?: () => void;
  onBack?: () => void;
} = {}) {
  const [localAdding, setLocalAdding] = useState(false);
  const adding = routeAdding ?? localAdding;
  const [query, setQuery] = useState("");
  const [checks, setChecks] = useState<Record<string, Check>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [createdId, setCreatedId] = useState("");

  const [fields, setFields] = useState(initialFields);
  const [kind, setKind] = useState("password");
  const [toolRoot, setToolRoot] = useState("");
  const [secret, setSecret] = useState("");
  const [rows, setRows] = useState<Resource[]>([]);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (adding) return;
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    apiGetOptions<Resource[]>("/ssh-resources", controller.signal)
      .then(({ data }) => { if (!controller.signal.aborted) setRows(data); })
      .catch(() => { if (!controller.signal.aborted) setLoadError("SSH 节点加载失败。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision, adding]);
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      let reference = credentialRef;
      if (!reference) {
        const credential = await apiPost<{ credential_ref: string }>("/ssh-resources/credentials", { auth_kind: kind, value: secret });
        reference = credential.credential_ref;
        setCredentialRef(reference);
        setSecret("");
      }
      const row = await apiPost<Resource>("/ssh-resources", { ...fields, port: Number(fields.port), auth_kind: kind, credential_ref: reference, native_tool_root: toolRoot.trim() || null });
      setCredentialRef("");
      setCreatedId(row.id);
      setMessage("节点已登记，可以验证 SSH 连接。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "SSH资源登记失败。"); }
    finally { setBusy(false); }
  };
  const validate = async (id: string) => {
    setBusy(true); setMessage("");
    try {
      const result = await apiPost<{ evaluation_ready: boolean }>(`/ssh-resources/${id}/validate`);
      const detail = result.evaluation_ready
        ? "主机指纹、Python 3、SFTP 与原生 AISBench 已通过检查。"
        : "主机指纹、Python 3 和 SFTP 已通过检查。";
      setChecks(previous => ({ ...previous, [id]: { passed: true, detail, time: new Date().toLocaleString() } }));
    } catch (error) {
      setChecks(previous => ({ ...previous, [id]: { passed: false, detail: error instanceof Error ? error.message : "SSH 连接验证失败。", time: new Date().toLocaleString() } }));
    }
    finally { setBusy(false); }
  };
  const labels: Record<keyof typeof fields, string> = { binding_key: "节点名称", host: "主机地址", port: "端口", username: "用户名", fingerprint: "已批准主机指纹", workdir: "SSH 执行目录" };
  const resetForm = () => {
    setCreatedId("");
    setMessage("");
    setFields(initialFields);
    setKind("password");
    setToolRoot("");
    setSecret("");
    setCredentialRef("");
  };
  const finish = () => {
    resetForm();
    setOffset(0);
    setRevision(value => value + 1);
    if (onSaved) onSaved();
    else setLocalAdding(false);
  };
  if (adding) return <Card className="stack ssh-pool">
    {createdId ? <>
      <h2>{fields.binding_key}</h2>
      <p role="status">{message || checks[createdId]?.detail}</p>
      <div className="inline">
        <button disabled={busy} onClick={() => void validate(createdId)}>验证 SSH 连接</button>
        <button className="primary" disabled={busy} onClick={finish}>{onBack ? "返回控制台" : "返回资源池"}</button>
      </div>
    </> : <form className="stack" onSubmit={event => { event.preventDefault(); void save(); }}>
      <h2>节点信息</h2>
      <div className="ssh-pool-fields">
        {Object.entries(labels).map(([key, label]) => <label className={["fingerprint", "workdir"].includes(key) ? "field-wide" : ""} key={key}>{label}<input required type={key === "port" ? "number" : "text"} min={key === "port" ? 1 : undefined} max={key === "port" ? 65535 : undefined} value={fields[key as keyof typeof fields]} onChange={event => setFields({ ...fields, [key]: event.target.value })} /></label>)}
        <label>SSH 凭据类型<select value={kind} onChange={event => { setKind(event.target.value); setSecret(""); setCredentialRef(""); }}><option value="password">密码</option><option value="private_key">私钥</option></select></label>
        <label className="field-wide">SSH 凭据{kind === "password" ? <input type="password" autoComplete="new-password" value={secret} onChange={event => { setSecret(event.target.value); setCredentialRef(""); }} /> : <textarea value={secret} onChange={event => { setSecret(event.target.value); setCredentialRef(""); }} rows={5} />}</label>
        {credentialRef && <p className="muted field-wide">凭据已保存，可修正节点信息后重试登记。</p>}
      </div>
      <h2>工具能力</h2>
      <p className="muted">容器镜像、挂载模板和并发容量由服务端配置。测评所需工具版本在控制台按数据集预检。</p>
      <label>原生工具目录（可选）<input value={toolRoot} onChange={event => setToolRoot(event.target.value)} /></label>
      {message && <p role="alert">{message}</p>}
      <div className="inline">
        <button type="button" disabled={busy} onClick={() => { resetForm(); if (onCancel) onCancel(); else setLocalAdding(false); }}>取消</button>
        <button className="primary" disabled={busy || (!secret && !credentialRef) || Object.values(fields).some(value => !value.trim())}>保存节点</button>
      </div>
    </form>}
  </Card>;

  const filtered = rows.filter(row => row.binding_key.toLowerCase().includes(query.trim().toLowerCase()));
  const page = filtered.slice(offset, offset + REGISTRY_PAGE_SIZE);
  return <Card className="stack ssh-pool">
    <div className="spread"><h2>SSH 节点</h2><div className="inline">
      {onBack && <button onClick={onBack}>返回控制台</button>}
      <button className="primary" onClick={() => onAdd ? onAdd() : setLocalAdding(true)}>添加节点</button>
    </div></div>
    <p className="muted">连接验证检查 SSH 基础环境。容器工具和数据目录按测评任务预检。</p>
    {loading ? <p role="status">正在加载节点…</p> : loadError ? <div className="inline"><p role="alert">{loadError}</p><button onClick={() => setRevision(value => value + 1)}>重新加载</button></div> : !rows.length ? <p>当前资源池为空。添加节点后即可回控制台选择。</p> : <>
      <input type="search" aria-label="搜索节点名称" placeholder="搜索节点名称" value={query} onChange={event => { setQuery(event.target.value); setOffset(0); }} />
      {page.length ? <TableWrap><table><thead><tr><th>节点名称</th><th>SSH 连接</th><th>工具能力</th><th>操作</th></tr></thead><tbody>
        {page.map(row => {
          const check = checks[row.id];
          return <tr key={row.id}>
            <td>{row.binding_key}<small>{row.username}@{row.host}:{row.port}</small></td>
            <td><Badge tone={check ? check.passed ? "green" : "red" : "gray"}>{check ? check.passed ? "验证通过" : "验证失败" : "未验证"}</Badge>
              {check && <details><summary>{check.time}</summary><p>{check.detail}</p></details>}
            </td>
            <td>{row.native_tool_revision ? <span title={row.native_tool_revision}>AISBench 原生 · {row.native_tool_revision.slice(0, 12)}</span> : "按服务端配置"}</td>
            <td><button disabled={busy} onClick={() => void validate(row.id)}>验证 SSH 连接</button></td>
          </tr>;
        })}
      </tbody></table></TableWrap> : <p>没有匹配的节点。</p>}
      <OffsetPagination label="SSH 节点" offset={offset} nextOffset={offset + REGISTRY_PAGE_SIZE < filtered.length ? offset + REGISTRY_PAGE_SIZE : null} onChange={setOffset} disabled={busy} />
    </>}
  </Card>;
}
