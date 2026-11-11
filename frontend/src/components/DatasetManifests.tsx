import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../services/api";

type Manifest = { id: string; manifest_key: string; scope: string; sample_count: number; sha256: string };

export function DatasetManifests() {
  const [rows, setRows] = useState<Manifest[]>([]);
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<unknown>(null);
  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    const controller = new AbortController();
    apiGet(`/dataset-manifests/${selected}`, controller.signal).then(setDetail)
      .catch(() => { if (!controller.signal.aborted) setMessage("清单来源读取失败。"); });
    return () => controller.abort();
  }, [selected]);
  useEffect(() => {
    const controller = new AbortController();
    apiGet<Manifest[]>("/dataset-manifests?limit=200", controller.signal)
      .then(setRows).catch(() => { if (!controller.signal.aborted) setMessage("清单加载失败，请检查后端连接。"); });
    return () => controller.abort();
  }, [revision]);
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      const payload = JSON.parse(content);
      const row = await apiPost<Manifest>("/dataset-manifests", payload);
      setMessage(`清单已登记：${row.id}；样本数：${row.sample_count}`);
      setRevision((value) => value + 1);
    } catch (error) { setMessage(error instanceof SyntaxError ? "请输入合法JSON。" : error instanceof Error ? error.message : "清单登记失败。"); }
    finally { setBusy(false); }
  };
  return <details className="diagnostic-tasks">
    <summary>数据集样本清单</summary>
    <p>登记Full或Lite的确定性样本范围。这里只保存样本ID及SHA-256，不上传题目或答案；登记不代表工具已验证或配置已批准。</p>
    <p>JSON字段：dataset_key、name、version、manifest_key、scope（full/lite）、samples（sample_id、sha256）。Lite另需parent_id引用同版本Full清单。</p>
    <label>样本清单JSON<textarea aria-label="样本清单JSON" rows={8} value={content} onChange={(event) => setContent(event.target.value)} style={{ display: "block", width: "100%" }} /></label>
    <button type="button" disabled={busy || !content.trim()} onClick={() => void save()}>登记样本清单</button>
    <p role="status">{message}</p>
    <p>最近加载的清单（最多200条；完整分页查询可使用API）</p>
    <ul>{rows.map((row) => <li key={row.id}>{row.manifest_key} · {row.scope} · {row.sample_count}个样本<br />ID：{row.id}<br />SHA-256：{row.sha256}<button onClick={() => setSelected(row.id)}>查看清单来源 {row.id.slice(0, 8)}</button></li>)}</ul>
    {detail !== null && <pre data-testid="manifest-provenance" style={{ overflow: "auto", maxHeight: 400 }}>{JSON.stringify(detail, null, 2)}</pre>}
  </details>;
}
