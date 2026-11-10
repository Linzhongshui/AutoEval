import { useEffect, useState } from "react";

type Attempt = { id: string; dataset_key: string; sample_id: string; attempt_no: number; state: string; error_code: string | null; evidence_available: boolean; evidence_sha256: string | null };

export function CaseHistory({ initialRun = "" }: { initialRun?: string }) {
  const [run, setRun] = useState(initialRun);
  const [sample, setSample] = useState("");
  const [query, setQuery] = useState<{ run: string; sample: string; offset: number } | null>(null);
  const [rows, setRows] = useState<Attempt[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [selected, setSelected] = useState("");
  const [evidence, setEvidence] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (initialRun) { setRun(initialRun); setQuery({ run: initialRun, sample: "", offset: 0 }); }
  }, [initialRun]);
  useEffect(() => {
    if (!query) return;
    const controller = new AbortController();
    setRows([]); setNext(null); setSelected(""); setMessage("正在查询历史…");
    const path = `/api/autoeval/v1/runs/${encodeURIComponent(query.run)}/case-executions?limit=20&offset=${query.offset}&sample_id=${encodeURIComponent(query.sample)}`;
    fetch(query.sample ? path : path.replace(/&sample_id=$/, ""), { signal: controller.signal })
      .then(async (response) => { const body = await response.json(); if (!response.ok) throw new Error(body.error?.message || "历史查询失败"); return body; })
      .then((body) => { setRows(body.data); setNext(body.next_offset); setMessage(body.data.length ? "历史已加载；评分结论请以正式报告为准。" : "该运行暂无匹配的case执行记录。"); })
      .catch((error) => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "历史查询失败"); });
    return () => controller.abort();
  }, [query]);
  useEffect(() => {
    setEvidence(null);
    if (!selected) return;
    const controller = new AbortController();
    fetch(`/api/autoeval/v1/case-executions/${selected}/evidence`, { signal: controller.signal })
      .then(async (response) => { const body = await response.json(); if (!response.ok) throw new Error(body.error?.message || "证据读取失败"); return body.data; })
      .then(setEvidence).catch((error) => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "证据读取失败"); });
    return () => controller.abort();
  }, [selected]);
  return <details className="diagnostic-tasks" open={Boolean(initialRun)}>
    <summary>case历史回溯（真实后端）</summary>
    <p>查询每次执行尝试及已校验的原始证据。重试成功仍保留此前失败；执行状态与评分正确性分开。</p>
    <label>运行ID <input aria-label="回溯运行ID" value={run} onChange={(event) => setRun(event.target.value)} /></label>
    <label>样本ID（可选） <input aria-label="回溯样本ID" value={sample} onChange={(event) => setSample(event.target.value)} /></label>
    <button type="button" disabled={!run.trim()} onClick={() => setQuery({ run: run.trim(), sample: sample.trim(), offset: 0 })}>查询case历史</button>
    <p role="status">{message}</p>
    <ul>{rows.map((row) => <li key={row.id}>{row.dataset_key} / {row.sample_id} · 第{row.attempt_no}次 · {row.state}{row.error_code ? ` · ${row.error_code}` : ""}
      <button type="button" disabled={!row.evidence_available} onClick={() => { setSelected(row.id); setEvidence(null); }}>查看第{row.attempt_no}次证据</button>
      <small> SHA-256：{row.evidence_sha256 || "尚未归档"}</small>
    </li>)}</ul>
    {query && <div><button disabled={query.offset === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - 20) })}>历史上一页</button>
      <button disabled={next === null} onClick={() => { if (next !== null) setQuery({ ...query, offset: next }); }}>历史下一页</button></div>}
    {evidence !== null && <pre data-testid="case-evidence" style={{ overflow: "auto", maxHeight: 400 }}>{JSON.stringify(evidence, null, 2)}</pre>}
  </details>;
}
