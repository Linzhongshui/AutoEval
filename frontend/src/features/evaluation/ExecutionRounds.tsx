import { useEffect, useState } from "react";
import { apiGet } from "../../shared/api";

type Round = {
  number: number;
  operation: string;
  state: string | null;
  cancel_requested_at?: string | null;
  cancelled_at?: string | null;
  report_id: string | null;
  target?: { dataset_key?: string; sample_id?: string; cases?: {dataset_key: string; sample_id: string}[] };
  shards?: { id: string; dataset: string; state: string; summary?: { cleanup_pending?: boolean } }[];
};

const operations: Record<string, string> = {
  initial: "首次执行", resume: "续跑测评", case_retry: "单 Case 重试",
};
const states: Record<string, string> = {
  queued: "排队中", running: "执行中", completed: "已完成", cancelled: "已取消",
  cancelling: "取消确认中", failed: "执行失败", pending: "待执行", succeeded: "已执行",
  unresolved: "待核对", submitting: "提交中", aggregating: "汇总与清理",
};

function ShardLog({ runId, number, shardId }: { runId: string; number: number; shardId: string }) {
  const [content, setContent] = useState<string>();
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  async function read() {
    setError(false);
    setBusy(true);
    try {
      const query = new URLSearchParams({ round_number: String(number), shard_id: shardId });
      const log = await apiGet<{ content: string }>(`/runs/${encodeURIComponent(runId)}/monitor/log?${query}`);
      setContent(log.content);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <button type="button" disabled={busy} onClick={() => void read()}>查看分片日志</button>
    {error && <p role="alert">分片日志尚未归档或无法校验。</p>}
    {content !== undefined && <pre className="snapshot">{content || "日志为空"}</pre>}
  </>;
}

export function ExecutionRounds({ runId, state }: { runId: string; state: string }) {
  const [open, setOpen] = useState(false);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setError(false);
    setRounds([]);
    apiGet<{ rounds: Round[] }>(`/evaluation-tasks/${encodeURIComponent(runId)}/rounds`, controller.signal)
      .then(result => setRounds(result.rounds))
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [runId, state, open]);

  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>执行轮次</summary>
    {error && <p role="alert">无法读取执行轮次。</p>}
    {!error && !rounds.length && <p role="status">正在读取执行轮次…</p>}
    <ol>{rounds.map(round => <li key={round.number}>
      <strong>第 {round.number} 轮 · {round.target?.cases ? "批量重试" : operations[round.operation] ?? round.operation}</strong>
      {round.state && <span> · {states[round.state] ?? round.state}</span>}
      {round.target?.cases && <details><summary>重试 {round.target.cases.length} 个样本</summary>
        <ul className="retry-case-list">{round.target.cases.map(row => <li key={JSON.stringify([row.dataset_key, row.sample_id])}>{row.dataset_key} · {row.sample_id}</li>)}</ul>
      </details>}
      {round.target?.sample_id && <p>{round.target.dataset_key} · {round.target.sample_id}</p>}
      {round.cancel_requested_at && <p>请求取消于 {new Date(round.cancel_requested_at).toLocaleString()}</p>}
      {round.cancelled_at && <p>确认取消于 {new Date(round.cancelled_at).toLocaleString()}</p>}
      {!!round.shards?.length && <ul>{round.shards.map(shard => <li key={shard.id}>
        {shard.dataset} · {states[shard.state] ?? shard.state}
        {shard.summary?.cleanup_pending && " · 等待远端确认资源清理"}
        {["succeeded", "failed", "cancelled"].includes(shard.state)
          && <ShardLog runId={runId} number={round.number} shardId={shard.id} />}
      </li>)}</ul>}
      {round.report_id && <a href={`#report/${round.report_id}`}>查看本轮报告</a>}
    </li>)}</ol>
  </details>;
}
