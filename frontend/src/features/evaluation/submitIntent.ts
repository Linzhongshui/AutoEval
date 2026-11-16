import { useRef, useState } from "react";
import { apiPost } from "../../shared/api";
import { runLink } from "./logic";
import type { Config, Resource, Target } from "./types";

type PendingSubmission = { hash: string; key: string };

const pendingStorageKey = "autoeval.pending-exploration.v1";

function readPending(): PendingSubmission | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(pendingStorageKey) || "null");
    return value &&
      typeof value.hash === "string" &&
      value.hash.length < 4096 &&
      typeof value.key === "string" &&
      /^[0-9a-f-]{36}$/.test(value.key)
      ? value
      : null;
  } catch {
    return null;
  }
}

function storePending(value: PendingSubmission | null) {
  // Only UUIDs, mode and bounded request limits are in this hash; never credentials.
  try {
    if (value) sessionStorage.setItem(pendingStorageKey, JSON.stringify(value));
    else sessionStorage.removeItem(pendingStorageKey);
  } catch {
    /* Restricted storage falls back to the in-memory intent. */
  }
}

/**
 * Submission intent survives a refresh so a retry reuses the same idempotency key.
 * A changed payload gets a fresh key; POST is never retried automatically.
 */
export function useExplorationSubmission() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submitting = useRef(false);
  const [initialPending] = useState(readPending);
  const pending = useRef<PendingSubmission | null>(initialPending);

  const submit = async (
    config: Config | null,
    target: Target | null,
    resource: Resource | null,
    resourceKind: string,
  ) => {
    if (submitting.current || !config || !target || !resource) return;
    submitting.current = true;
    setBusy(true);
    setMessage("");
    const payload = {
      config_version_id: config.id,
      target_id: target.id,
      resource_id: resource.id,
      resource_kind: resourceKind,
      run_mode: "exploration",
      max_model_requests: 5,
    };
    const hash = JSON.stringify(payload);
    if (pending.current?.hash !== hash) pending.current = { hash, key: crypto.randomUUID() };
    const submission = pending.current;
    storePending(submission);
    try {
      const row = await apiPost<{ run_id: string }>(
        resourceKind === "aisbench_monitor" ? "/aisbench-monitored/runs" : "/runs",
        payload,
        submission.key,
      );
      pending.current = null;
      storePending(null);
      location.hash = runLink(row.run_id);
      setMessage("已提交；按冻结的Lite清单执行。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交未确认；重试沿用同一提交键。");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  return { busy, setBusy, message, setMessage, submit };
}
