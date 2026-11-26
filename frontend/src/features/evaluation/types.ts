import type { components } from "../../shared/types/api";
import type { Param } from "../../shared/types/domain";

export type { Param };

export type Config = components["schemas"]["ConfigListItem"];

export type Target = {
  service_name?: string;
  id: string;
  remote_model: string;
  base_url: string;
  model_key: string;
  model_version: string;
  default_config_version_id: string | null;
};

export type Resource = { id: string; binding_key: string; native_tool_root?: string | null };

export type Profile = {
  provenance?: Record<string, { url?: string | null; revision?: string | null; sha256?: string | null }>;
  persistedVersion?: number;
  id: string;
  name: string;
  source: string;
  model?: string;
  modelId?: string;
  official: boolean;
  versions: string[];
  items: string[];
  data?: Record<string, Record<string, Param>>;
};

export type Run = {
  report_id?: string | null;
  id: string;
  state: string;
  remote_model?: string;
  resource_kind?: string;
  created_at: string;
  datasets?: string[];
};

export type RunSnapshot = {
  sha256: string;
  config_version_id: string;
  config_sha256: string;
  target_id: string;
  remote_model: string;
  resource_kind: string;
  sample_count: number;
  dataset_concurrency?: number;
  parameters: Record<string, unknown>;
  manifest_id: string;
  manifest_sha256: string;
  tool?: Record<string, unknown>;
  profile_id?: string;
  max_model_requests?: number;
  execution_origin: string;
};

export type DatasetResult = {
  id: string;
  dataset: string;
  state: string;
  summary?: Record<string, unknown> | null;
  actual_duration_sec?: number | null;
};

export type RunDetail = Omit<Run, "datasets"> & {
  current_round?: number;
  follow_up_enabled?: boolean;
  datasets?: DatasetResult[];
  dataset_report?: { datasets?: DatasetResult[] } | null;
  updated_at?: string;
  cancel_requested_at?: string;
  events?: { seq: number; type: string; created_at: string }[];
  run_mode: string;
  gate_status: string;
  snapshot: RunSnapshot | null;
  execution_unresolved: boolean;
  cleanup: { state: string; attempt_count: number; last_error_code: string | null };
  report: null | { id: string; validity: string; summary: Record<string, unknown> };
};
