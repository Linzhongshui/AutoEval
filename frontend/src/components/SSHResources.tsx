import { OffsetPagination } from "./OffsetPagination";
import { useEffect, useState } from "react";
import { apiGetPage, apiPost } from "../services/api";

type Resource = { id: string; binding_key: string; host: string; port: number; username: string; fingerprint: string; workdir: string; native_tool_root: string | null; native_bridge_sha256: string | null; native_lock_sha256: string | null; native_tool_revision: string | null };

export function SSHResources() {
  const [fields, setFields] = useState({ binding_key: "", host: "", port: "22", username: "", fingerprint: "", workdir: "" });
  const [kind, setKind] = useState("password");
  const [toolRoot, setToolRoot] = useState("");
  const [secret, setSecret] = useState("");
  const [rows, setRows] = useState<Resource[]>([]);
  const [offset, setOffset] = useState(0);
  const [next, setNext] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const visible: Resource[] = []; let position: number | null = 0;
      while (position !== null) {
        const page: { data: Resource[]; next_offset: number | null } = await apiGetPage<Resource[]>(`/ssh-resources?limit=100&offset=${position}`, controller.signal);
        visible.push(...page.data.filter((row) => !/^(?:browser-ssh-[a-f0-9]{12}|ssh-registry-[a-f0-9]{32})$/.test(row.binding_key)));
        if (page.next_offset !== null && page.next_offset <= position) throw Error("分页异常");
        position = page.next_offset;
      }
      if (!controller.signal.aborted) { setRows(visible.slice(offset, offset + 20)); setNext(offset + 20 < visible.length ? offset + 20 : null); }
    })()
      .catch(() => { if (!controller.signal.aborted) setMessage("SSH资源加载失败。"); });
    return () => controller.abort();
  }, [offset, revision]);
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      const credential = await apiPost<{ credential_ref: string }>("/ssh-resources/credentials", { auth_kind: kind, value: secret });
      setSecret("");
      await apiPost("/ssh-resources", { ...fields, port: Number(fields.port), auth_kind: kind, credential_ref: credential.credential_ref, native_tool_root: toolRoot.trim() || null });
      setOffset(0); setRevision((value) => value + 1); setMessage("SSH资源已登记；请显式预检，登记不代表可执行测评。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "SSH资源登记失败。"); }
    finally { setBusy(false); }
  };
  const validate = async (id: string) => {
    setBusy(true); setMessage("");
    try {
      const checked = await apiPost<{ evaluation_ready: boolean }>(`/ssh-resources/${id}/validate`);
      setMessage(checked.evaluation_ready ? "SSH原生GPQA预检通过：批准工具与源码锁已核验，可在探索任务中选择该资源。" : "SSH预检通过：主机指纹已核验，Python3及SFTP可用；当前仅支持框架诊断，测评工具尚未接入。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "SSH预检失败。"); }
    finally { setBusy(false); }
  };
  const labels: Record<keyof typeof fields, string> = { binding_key: "SSH资源名称", host: "SSH主机地址", port: "SSH端口", username: "SSH用户名", fingerprint: "已批准主机指纹", workdir: "SSH执行目录" };
  return <section className="diagnostic-tasks resource-management-form resource-fields-grid">
    <h3>客户 SSH 服务器</h3>
    <p>仅直连控制，不安装常驻Agent。主机指纹须来自已批准输入；不会自动信任首次连接。作业仅在执行目录内的专属.autoeval子目录中创建和清理。</p>
    {Object.entries(labels).map(([key, label]) => <label className={["fingerprint", "workdir"].includes(key) ? "field-wide" : ""} key={key}>{label}<input aria-label={label} value={fields[key as keyof typeof fields]} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} /></label>)}
    <label className="field-wide">原生工具目录（可选）<input aria-label="SSH原生工具目录" value={toolRoot} onChange={(event) => setToolRoot(event.target.value)} /></label>
    <p>填写工具目录时固定登记时批准的桥接、源码锁及版本。升级工具请使用独立目录和新资源绑定，保留旧任务依赖的原目录。</p>
    <label>SSH凭据类型<select aria-label="SSH凭据类型" value={kind} onChange={(event) => { setKind(event.target.value); setSecret(""); }}><option value="password">密码</option><option value="private_key">私钥（当前支持未加密密钥）</option></select></label>
    <label className="field-wide">SSH凭据{kind === "password" ? <input type="password" autoComplete="new-password" aria-label="SSH凭据" value={secret} onChange={(event) => setSecret(event.target.value)} /> : <textarea aria-label="SSH凭据" value={secret} onChange={(event) => setSecret(event.target.value)} rows={5} />}</label>
    <button disabled={busy || !secret || Object.values(fields).some((value) => !value.trim())} onClick={() => void save()}>登记SSH资源</button>
    <p role="status">{message}</p>
    <h3>已登记资源</h3>
    {!rows.length && <p className="muted">暂无已登记资源</p>}
    <ul>{rows.map((row) => <li key={row.id}>{row.binding_key} · {row.username}@{row.host}:{row.port} · {row.workdir}<button disabled={busy} onClick={() => void validate(row.id)}>预检</button>{row.native_tool_root && <details><summary>已固定工具版本</summary>{row.native_bridge_sha256 ? <><p>目录：{row.native_tool_root}</p><p>版本：{row.native_tool_revision}</p><p>桥接SHA-256：{row.native_bridge_sha256}</p><p>源码锁SHA-256：{row.native_lock_sha256}</p></> : <p>历史记录没有唯一版本证据；请按批准工具重新登记资源，后台不会自动批准当前代码。</p>}</details>}</li>)}</ul>
    <OffsetPagination label="SSH资源" offset={offset} nextOffset={next} onChange={setOffset} disabled={busy} />
  </section>;
}
