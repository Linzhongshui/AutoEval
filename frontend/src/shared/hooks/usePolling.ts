import { useEffect, useRef } from "react";

type Options = {
  /** Disable polling without unmounting the caller (e.g. terminal states). */
  enabled?: boolean;
  /** Polling interval in milliseconds, applied after the previous call settles. */
  intervalMs: number;
};

/**
 * Polling that schedules the next call only after the previous one finishes, so
 * slow responses never overlap. Polling pauses while the document is hidden and
 * refreshes once when it becomes visible again.
 */
export function usePolling(task: () => void | Promise<void>, options: Options) {
  const { enabled = true, intervalMs } = options;
  const taskRef = useRef(task);
  taskRef.current = task;

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const run = async () => {
      if (stopped) return;
      if (document.hidden) {
        timer = setTimeout(run, intervalMs);
        return;
      }
      try {
        await taskRef.current();
      } finally {
        if (!stopped) timer = setTimeout(run, intervalMs);
      }
    };

    const onVisibility = () => {
      if (!document.hidden && !stopped) {
        if (timer) clearTimeout(timer);
        void run();
      }
    };

    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, intervalMs]);
}
