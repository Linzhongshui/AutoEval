import { useEffect, useState } from "react";
import { apiGetPage, apiPost } from "../services/api";

type Resource = { id: string; binding_key: string; host: string; port: number; username: string; fingerprint: string; workdir: string };

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
    apiGetPage<Resource[]>(`/ssh-resources?limit=20&offset=${offset}`, controller.signal).then((page) => { setRows(page.data); setNext(page.next_offset); })
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
  return <details className="diagnostic-tasks">
    <summary>客户SSH服务器（真实后端）</summary>
    <p>仅直连控制，不安装常驻Agent。主机指纹须来自已批准输入；不会自动信任首次连接。作业仅在执行目录内的专属.autoeval子目录中创建和清理。</p>
    {Object.entries(labels).map(([key, label]) => <label key={key}>{label}<input aria-label={label} value={fields[key as keyof typeof fields]} onChange={(event) => setFields({ ...fields, [key]: event.target.value })} /></label>)}
    <label>原生工具目录（可选）<input aria-label="SSH原生工具目录" value={toolRoot} onChange={(event) => setToolRoot(event.target.value)} /></label>
    <label>SSH凭据类型<select aria-label="SSH凭据类型" value={kind} onChange={(event) => { setKind(event.target.value); setSecret(""); }}><option value="password">密码</option><option value="private_key">私钥（当前支持未加密密钥）</option></select></label>
    <label>SSH凭据{kind === "password" ? <input type="password" autoComplete="new-password" aria-label="SSH凭据" value={secret} onChange={(event) => setSecret(event.target.value)} /> : <textarea aria-label="SSH凭据" value={secret} onChange={(event) => setSecret(event.target.value)} rows={5} />}</label>
    <button disabled={busy || !secret || Object.values(fields).some((value) => !value.trim())} onClick={() => void save()}>登记SSH资源</button>
    <p role="status">{message}</p>
    <ul>{rows.map((row) => <li key={row.id}>{row.binding_key} · {row.username}@{row.host}:{row.port} · {row.workdir}<button disabled={busy} onClick={() => void validate(row.id)}>预检SSH资源 {row.binding_key}</button></li>)}</ul>
    <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>SSH资源上一页</button><button disabled={next === null} onClick={() => { if (next !== null) setOffset(next); }}>SSH资源下一页</button>
  </details>;
}
