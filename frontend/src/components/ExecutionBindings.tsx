import { SearchableSelect } from "./SearchableSelect";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../services/api";

type Config = { id: string; config_key: string; display_name: string; version: number; version_label: string; kind: string; items: Record<string, unknown>; profile_bindings: Record<string, string> };
type Profile = { id: string; profile_key: string; version: string; dataset_name: string };

export function ExecutionBindings() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [configs, setConfigs] = useState<Config[]>([]);
  const [selected, setSelected] = useState("");
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [profileJson, setProfileJson] = useState("");
  const [version, setVersion] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [spec, setSpec] = useState<unknown>(null);
  const config = configs.find((row) => row.id === selected);
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([apiGet<Profile[]>("/profiles?limit=200", controller.signal), apiGet<Config[]>("/test-configs?limit=200", controller.signal)])
      .then(([p, c]) => { setProfiles(p); setConfigs(c.filter((row) => row.kind === "custom")); })
      .catch(() => { if (!controller.signal.aborted) setMessage("执行绑定数据加载失败。"); });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    setSpec(null);
    if (!selected) return;
    const controller = new AbortController();
    apiGet(`/test-configs/${selected}/execution-spec`, controller.signal).then(setSpec).catch(() => {
      if (!controller.signal.aborted) setMessage("执行规格读取失败。");
    });
    return () => controller.abort();
  }, [selected, revision]);
  const register = async () => {
    setBusy(true); setMessage("");
    try {
      await apiPost("/profiles", JSON.parse(profileJson));
      setRevision((value) => value + 1); setMessage("Profile已登记；工具与评分规则仍需实际验证。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Profile登记失败。"); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!config) return;
    setBusy(true); setMessage("");
    try {
      const expected = Math.max(...configs.filter((row) => row.config_key === config.config_key).map((row) => row.version));
      await apiPost("/test-configs", { config_key: config.config_key, display_name: config.display_name,
        version_label: version.trim(), expected_version: expected, items: config.items, profile_bindings: bindings });
      setRevision((value) => value + 1); setMessage("已创建绑定后的新配置版本；原版本保留。请重新选择新版本查看执行规格。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "绑定保存失败。"); }
    finally { setBusy(false); }
  };
  return <section className="configuration-management stack">
    <h3>执行规则与配置绑定</h3>
    <p>Profile固定清单、工具提交版本与评分规则摘要。登记契约不代表已完成原生工具验证，不会开放正式执行。</p>
    <section className="configuration-block"><h3>登记执行规则（Profile）</h3>
      <p>JSON包含profile_key、version、dataset_name、full_manifest_id、可选lite_manifest_id和tool。tool包含family、source_url、revision、scorer_reference、scorer_sha256、parallelism_owner；填写已核实的实际输入。</p>
      <textarea aria-label="Profile契约JSON" rows={8} value={profileJson} onChange={(event) => setProfileJson(event.target.value)} style={{ width: "100%" }} />
      <button disabled={busy || !profileJson.trim()} onClick={() => void register()}>登记Profile契约</button>
    </section>
    <h3>绑定配置版本</h3><label>待绑定配置版本 <SearchableSelect aria-label="待绑定配置版本" value={selected} onChange={(event) => {
      setSelected(event.target.value); setBindings(configs.find((row) => row.id === event.target.value)?.profile_bindings || {});
    }}><option value="">请选择配置版本</option>{configs.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}</SearchableSelect></label>
    {config && Object.keys(config.items).map((dataset) => <label key={dataset}>{dataset} Profile <SearchableSelect aria-label={`${dataset}执行Profile`} value={bindings[dataset] || ""} onChange={(event) => setBindings({ ...bindings, [dataset]: event.target.value })}>
      <option value="">请选择匹配的Profile</option>{profiles.filter((row) => row.dataset_name === dataset).map((row) => <option key={row.id} value={row.id}>{row.profile_key} · {row.version}</option>)}
    </SearchableSelect></label>)}
    <label>绑定后版本名称 <input aria-label="绑定后版本名称" value={version} onChange={(event) => setVersion(event.target.value)} /></label>
    <button disabled={busy || !config || !version.trim() || Object.keys(config.items).some((name) => !bindings[name])} onClick={() => void save()}>保存执行绑定新版本</button>
    <p role="status">{message}</p>
    {spec !== null && <details><summary>查看冻结执行规格与阻塞原因</summary><pre style={{ overflow: "auto" }}>{JSON.stringify(spec, null, 2)}</pre></details>}
    <p>本面板最多加载200条配置/契约；列表不完整时请使用API分页，完整分页交互待完善。</p>
  </section>;
}
