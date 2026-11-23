import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../../shared/api";
import type { components } from "../../shared/types/api";

export type CaseTarget = Pick<components["schemas"]["CaseRetryConfirmation"], "dataset_key" | "sample_id">;
type Preview = components["schemas"]["FollowUpPreview"] | components["schemas"]["BatchCasePreview"];

const reasons: Record<string, string> = {
  previous_dispatch_unknown: "旧作业已结束，但无法确认此前是否调用过模型。本次重试可能产生重复费用。",
  using_current_template: "本轮将使用该资源当前的执行配置，历史轮次保留原配置。",
  resource_changed: "当前执行资源与原任务冻结的配置不一致。",
  source_active: "当前轮次还在执行",
  source_not_cancelled: "原任务尚未确认取消",
  cleanup_pending: "原作业资源尚未全部释放",
  samples_unresolved: "无法确认原请求是否已派发，请核对原作业的请求记录和归档证据。",
  budget_expired: "原执行预算已到期",
  budget_exhausted: "原执行预算已用尽",
  budget_unavailable: "原执行预算不可用",
  target_unavailable: "原模型绑定不可用或与冻结快照不一致",
};

export function FollowUpConfirmation({
  runId, target, cases, onClose, onAccepted,
}: {
  runId: string;
  target?: CaseTarget;
  cases?: CaseTarget[];
  onClose: () => void;
  onAccepted: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const key = useRef(crypto.randomUUID());
  const submitting = useRef(false);
  const [preview, setPreview] = useState<Preview>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/evaluation-tasks/${encodeURIComponent(runId)}`;
  const action = cases ? "batch-case-retry" : target ? "case-retry" : "resume";
  const query = target ? `?${new URLSearchParams(target)}` : "";

  useEffect(() => { dialog.current?.showModal(); }, []);
  useEffect(() => {
    const controller = new AbortController();
    const path = `${base}/${action}-preview${query}`;
    const request = cases
      ? apiPost<Preview>(path, { cases }, undefined, controller.signal)
      : apiGet<Preview>(path, controller.signal);
    request
      .then(setPreview)
      .catch(() => { if (!controller.signal.aborted) setError("无法取得执行预览。"); });
    return () => controller.abort();
  }, [base, action, query, cases]);

  async function confirm() {
    if (!preview || preview.blockers.length || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      await apiPost(`${base}/${action}`, {
        ...target, ...(cases && { cases }), source_round: preview.source_round, scope_sha256: preview.scope_sha256,
      }, key.current);
      onAccepted();
    } catch {
      setError("提交未确认。可以重试同一请求，或关闭后刷新预览。");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const lost = preview?.samples.filter(sample => sample.category === "evidence_lost") ?? [];
  const title = cases ? "批量重试" : target ? "重试此 Case" : "续跑测评";
  return <dialog ref={dialog} aria-label={title} className="follow-up-dialog" onCancel={event => {
    event.preventDefault();
    if (!busy) onClose();
  }}>
    <h2>{title}</h2>
    {cases && <details><summary>已选择 {cases.length} 个样本</summary>
      <ul className="retry-case-list">{cases.map(row => <li key={JSON.stringify([row.dataset_key, row.sample_id])}>{row.dataset_key} · {row.sample_id}</li>)}</ul>
    </details>}
    {target && <p>{target.dataset_key} · {target.sample_id}</p>}
    {preview && <>
      {preview.blockers.length ? <p role="status">当前无法{title}。</p> :
        <p>将重新执行 {preview.sample_count} 个样本。{(target || cases) && "新报告将采用本轮结果，历史尝试仍可查看。"}</p>}
      {preview.warnings?.map(reason => <p key={reason}>{reasons[reason] ?? reason}</p>)}
      {!target && !cases && <p>可复用 {preview.samples.filter(sample => sample.category === "reusable").length} 个样本。</p>}
      {!!lost.length && <details><summary>{lost.length} 个样本的归档证据已丢失</summary>
        <ul>{lost.map(sample => <li key={JSON.stringify([sample.dataset_key, sample.sample_id])}>{sample.dataset_key} · {sample.sample_id}</li>)}</ul>
      </details>}
      {!!preview.blockers.length && <ul>{preview.blockers.map(reason => <li key={reason}>{reasons[reason] ?? reason}</li>)}</ul>}
    </>}
    {!preview && !error && <p role="status">正在核对原任务…</p>}
    {error && <p role="alert">{error}</p>}
    <footer className="inline"><button type="button" autoFocus disabled={busy} onClick={onClose}>关闭</button>
    <button type="button" className="primary" disabled={busy || !preview || !!preview.blockers.length} onClick={() => void confirm()}>确认{title}</button></footer>
  </dialog>;
}
