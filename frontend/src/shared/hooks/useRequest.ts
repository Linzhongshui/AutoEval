import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../api";

type Options = {
  /** Skip the request entirely (for optional selections). */
  enabled?: boolean;
  /** Re-run the request when this key changes; the previous request is aborted. */
  queryKey?: string;
};

type State<T> = {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => void;
};

const inFlight = new Map<string, Promise<unknown>>();

/**
 * Shared GET state: identical query keys reuse an in-flight request, parameter
 * changes abort the old request, and stale responses never overwrite newer data.
 * Errors keep the previously loaded value so the page can stay usable.
 */
export function useRequest<T>(path: string, options: Options = {}): State<T> {
  const { enabled = true, queryKey } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const current = ++generation.current;
    const controller = new AbortController();
    setLoading(true);
    void (async () => {
      try {
        let pending = inFlight.get(path);
        if (!pending) {
          pending = apiGet<T>(path, controller.signal);
          inFlight.set(path, pending);
          pending
            .catch(() => undefined)
            .finally(() => {
              if (inFlight.get(path) === pending) inFlight.delete(path);
            });
        }
        const value = (await pending) as T;
        if (current !== generation.current || controller.signal.aborted) return;
        setData(value);
        setError("");
      } catch (exception) {
        if (current !== generation.current || controller.signal.aborted) return;
        setError(exception instanceof Error ? exception.message : "请求失败");
      } finally {
        if (current === generation.current) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [path, enabled, queryKey, refresh]);

  const reload = useCallback(() => setRefresh((value) => value + 1), []);
  return { data, loading, error, reload };
}
