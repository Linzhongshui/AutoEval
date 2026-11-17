import { useEffect, useState } from "react";
import { apiGet } from "../../shared/api";
import type { Config, Param, Profile } from "../evaluation/types";

export function useProfiles(enabled = true) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    apiGet<Config[]>("/test-configs?limit=200", controller.signal)
      .then((rows) => {
        const grouped = new Map<string, Profile>();
        for (const item of rows) {
          const official = item.kind === "standard";
          const existing = grouped.get(item.config_key);
          if (existing) {
            existing.versions.push(item.version_label);
            existing.data![item.version_label] = item.items as Record<string, Param>;
            existing.provenance![item.version_label] = { url: item.source_url, revision: item.source_revision, sha256: item.source_sha256 };
          } else grouped.set(item.config_key, {
            id: item.config_key,
            name: item.display_name,
            source: official ? "标准仓库" : "后端持久化",
            official,
            persistedVersion: item.version,
            versions: [item.version_label],
            items: Object.keys(item.items),
            data: { [item.version_label]: item.items as Record<string, Param> },
            provenance: { [item.version_label]: { url: item.source_url, revision: item.source_revision, sha256: item.source_sha256 } },
          });
        }
        setProfiles([...grouped.values()]);
      }).catch(() => { if (!controller.signal.aborted) setProfiles([]); });
    return () => controller.abort();
  }, [enabled]);
  return [profiles, setProfiles] as const;
}

