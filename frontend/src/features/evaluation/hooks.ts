import { useEffect, useState } from "react";
import { apiGet, apiGetOptions } from "../../shared/api";
import { REGISTRY_PAGE_SIZE } from "../../shared/constants";
import { eligibleConfig } from "./logic";
import type { Config, Target } from "./types";

/** Paged registry options; a failed page keeps the error visible for retry. */
export function useOptions<T>(path: string) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<T[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setRows([]);
    setNext(null);
    apiGetOptions<T[]>(`${path}?offset=${offset}&limit=${REGISTRY_PAGE_SIZE}`, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) {
          setRows(page.data);
          setNext(page.next_offset);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("选项加载失败，请重试。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, offset, refresh]);
  return {
    rows,
    offset,
    next,
    loading,
    error,
    setOffset,
    retry: () => setRefresh((value) => value + 1),
  };
}

/** Load the selected target's default configuration when it fits the exploration path. */
export function useDefaultConfig(target: Target | null) {
  const [config, setConfig] = useState<Config | null>(null);
  const [loadingDefault, setLoadingDefault] = useState(false);
  const [defaultError, setDefaultError] = useState("");
  const [defaultRefresh, setDefaultRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setConfig(null);
    setDefaultError("");
    setLoadingDefault(false);
    if (!target) return () => controller.abort();
    setLoadingDefault(true);
    apiGet<Target[]>(`/target-bindings?target_id=${target.id}`, controller.signal)
      .then((rows) => {
        if (!rows[0]?.default_config_version_id) {
          throw new Error("该模型尚未绑定默认配置，可显式选择探索配置。");
        }
        return apiGet<Config[]>(
          `/test-configs?config_id=${rows[0].default_config_version_id}`,
          controller.signal,
        );
      })
      .then((rows) => {
        if (controller.signal.aborted) return;
        if (!rows[0] || !eligibleConfig(rows[0])) {
          setDefaultError("模型默认配置不适用于当前GPQA Lite探索，请显式选择其他配置。");
          return;
        }
        setConfig(rows[0]);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setDefaultError(
          error instanceof Error && error.message.startsWith("该模型")
            ? error.message
            : "默认配置读取失败，可重试或显式选择配置。",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDefault(false);
      });
    return () => controller.abort();
  }, [target, defaultRefresh]);
  return {
    config,
    setConfig,
    loadingDefault,
    defaultError,
    setDefaultError,
    reloadDefault: () => setDefaultRefresh((value) => value + 1),
  };
}
