import { useEffect, useState } from "react";
import { apiPost } from "../../shared/api";
import type { components } from "../../shared/types/api";
import type { Param } from "../../shared/types/domain";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { ModelRegistry } from "../catalog/ModelRegistry";
import { SearchableSelect } from "../../shared/ui/SearchableSelect";
import { ServiceBindings } from "../resources/ServiceBindings";
import { SSHResources } from "../resources/SSHResources";
import { SubmissionReview } from "./SubmissionReview";
import { Note } from "../../shared/ui/Note";
import { ConfigurationDrawer } from "../../shared/ui/ConfigurationDrawer";
import { DATASET_NAMES, DATASET_TYPES } from "../catalog/datasets";
import { DatasetTree } from "../catalog/datasetTree";
import { ParameterCards } from "../catalog/parameterCards";
import { useDefaultConfig, useOptions } from "./hooks";
import { eligibleConfig, eligibleTarget, withSelected } from "./logic";
import { useExplorationSubmission } from "./submitIntent";
import type { Config, Profile, Resource, Target } from "./types";

export function EvaluationConsole({ profiles, setProfiles, notify }: {
  profiles: Profile[];
  setProfiles: (p: Profile[]) => void;
  notify: (s: string) => void;
}) {
  const configs = useOptions<Config>("/test-configs");
  const targets = useOptions<Target>("/target-bindings");
  const docker = useOptions<Resource>("/resources");
  const ssh = useOptions<Resource>("/ssh-resources");
  const monitored = useOptions<Resource>("/aisbench-monitored/resources");
  const [target, setTarget] = useState<Target | null>(null);
  const [resource, setResource] = useState<Resource | null>(null);
  const [resourceKind, setResourceKind] = useState("docker_local");
  const resources = resourceKind === "aisbench_monitor" ? monitored : resourceKind === "customer_ssh" ? ssh : docker;
  const { config, setConfig, loadingDefault, defaultError, setDefaultError, reloadDefault } = useDefaultConfig(target);
  const { busy, message, submit } = useExplorationSubmission();
  const [configKind, setConfigKind] = useState("标准配置");
  const [datasetSearch, setDatasetSearch] = useState("");
  const [view, setView] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [draftParams, setDraftParams] = useState<Record<string, Param>>({});
  const [newConfigName, setNewConfigName] = useState("");
  const [newVersionName, setNewVersionName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) setConfigKind(config.kind === "custom" ? "自定义配置" : "标准配置");
  }, [config]);

  const targetRows = withSelected(targets.rows.filter(eligibleTarget), target);
  const configRows = withSelected(
    configs.rows.filter(eligibleConfig).filter((row) => configKind === "自定义配置" ? row.kind === "custom" : row.kind === "standard"),
    config,
  );
  const resourceRows = withSelected(
    resources.rows.filter((row) => resourceKind !== "customer_ssh" || row.native_tool_root),
    resource,
  );
  const visibleDatasets = DATASET_NAMES.filter((d) => d.toLowerCase().includes(datasetSearch.toLowerCase()));
  const viewParams = view ? (config?.items as Record<string, Param> | undefined)?.[view] : undefined;
  const openEditor = () => {
    if (!config || config.kind !== "custom") return;
    setDraftParams(structuredClone(config.items) as Record<string, Param>);
    setNewConfigName("");
    setNewVersionName("");
    setDrawer(true);
  };

  return (
    <div className="console-grid console-workflow">
      <div className="console-configuration">
        <section className="console-step">
          <div className="console-section-heading"><h3 className="console-step-title">模型接入</h3><div className="management-toolbar"><ManagementDrawer title="管理模型服务" onDismiss={targets.retry}><ServiceBindings /></ManagementDrawer><ManagementDrawer title="管理执行资源" onDismiss={resources.retry}><SSHResources /></ManagementDrawer></div></div>
          <div className="tabs">
            <button className="active">API接入</button>
            <button disabled title="当前探索路径不支持 IP/Port 拉起">IP/Port 拉起</button>
          </div>
          <div className="stack">
            <label>模型服务
              <SearchableSelect aria-label="控制台模型服务" value={target?.id || ""} disabled={busy || targets.loading} onChange={(e) => setTarget(targetRows.find((row) => row.id === e.target.value) || null)}>
                <option value="">请选择官方 DeepSeek 服务</option>
                {targetRows.map((row) => <option key={row.id} value={row.id}>{row.model_key} / {row.model_version} · {row.remote_model} · {row.id.slice(0, 8)}</option>)}
              </SearchableSelect>
            </label>
            <label>资源接入方式
              <select aria-label="控制台资源接入方式" value={resourceKind} disabled={busy} onChange={(e) => { setResourceKind(e.target.value); setResource(null); }}>
                <option value="docker_local">本机Docker</option>
                <option value="customer_ssh">客户SSH服务器</option><option value="aisbench_monitor">远程 AISBench（运行监控）</option>
              </select>
            </label>
            <label>执行资源
              <SearchableSelect aria-label="控制台执行资源" value={resource?.id || ""} disabled={busy || resources.loading} onChange={(e) => setResource(resourceRows.find((row) => row.id === e.target.value) || null)}>
                <option value="">请选择已保存资源</option>
                {resourceRows.map((row) => <option key={row.id} value={row.id}>{row.binding_key}</option>)}
              </SearchableSelect>
            </label>
          </div>
        </section>
        <section className="console-step stack">
          <div className="console-section-heading"><h3 className="console-step-title">测评配置</h3>          <ManagementDrawer title="模型与默认配置" onDismiss={() => { targets.retry(); configs.retry(); }}><ModelRegistry onApply={(_id, _values, configKey, versionLabel) => {
            const match = configs.rows.find((row) => row.config_key === configKey && row.version_label === versionLabel && eligibleConfig(row));
            if (match) setConfig(match);
            else notify("默认配置已读取；请选择已保存服务，按不可变配置版本ID加载探索参数。");
          }} /></ManagementDrawer>
</div>
          <div className="console-config-fields">
            <fieldset className="console-config-type">
              <legend>配置类型</legend>
              <div className="console-config-segments">
                {["标准配置", "自定义配置"].map((item) => (
                  <label key={item} className={configKind === item ? "selected" : ""}>
                    <input
                      type="radio"
                      name="console-config-type"
                      checked={configKind === item}
                      onChange={() => { setConfigKind(item); setConfig(null); setDefaultError(""); }}
                    />{item}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="evaluation-version-field">
              <span>配置版本</span>
              <SearchableSelect aria-label="控制台测评配置" value={config?.id || ""} disabled={busy || loadingDefault} onChange={(e) => {
                setConfig(configRows.find((row) => row.id === e.target.value) || null);
                setDefaultError("");
              }}>
                <option value="">请选择已绑定 Profile 的 GPQA Lite 配置</option>
                {configRows.map((row) => <option key={row.id} value={row.id}>{row.display_name} · {row.version_label}</option>)}
              </SearchableSelect>
            </label>
          </div>
          {loadingDefault && <p role="status">正在按配置版本ID读取模型默认配置…</p>}
          {defaultError && <p role="status">{defaultError}</p>}
          <div className="console-config-actions"><button disabled={busy || !target || loadingDefault} onClick={reloadDefault}>加载模型默认配置</button>{configKind === "自定义配置" && <button disabled={config?.kind !== "custom"} onClick={openEditor}>编辑配置</button>}</div>
          {[configs, targets, resources].some((source) => source.error) && (
            <p role="alert">选项加载失败。<button onClick={() => { configs.retry(); targets.retry(); resources.retry(); }}>重试选项加载</button></p>
          )}
          <Note>配置须为单 GPQA 数据集、Lite 且已绑定 Profile；提交时后台再次校验，未绑定的配置不会出现在选项中。</Note>

        </section>
        <section className="console-step">
          <h3 className="console-step-title">测评数据集</h3>
          <div className="dataset-selection-toolbar">
            <input aria-label="搜索可选数据集" placeholder="搜索数据集" value={datasetSearch} onChange={(e) => setDatasetSearch(e.target.value)} />
            <span>已选 {config ? 1 : 0} 个</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>选择</th><th>数据集类型</th><th>数据集</th><th>数据范围</th><th>操作</th></tr></thead>
              <tbody>
                {visibleDatasets.map((d) => (
                  <tr key={d}>
                    <td><input type="checkbox" aria-label={`选择 ${d}`} checked={d === "GPQA" && Boolean(config)} disabled readOnly /></td>
                    <td>{DATASET_TYPES.find((item) => item.items.includes(d))?.label}</td>
                    <td>{d}</td>
                    <td>{d === "GPQA" ? (config?.items.GPQA as Param | undefined)?.scope || "需选择配置" : "当前路径未开放"}</td>
                    <td><div className="inline">
                      {d === "GPQA" && <><button className="link" disabled={!config} onClick={() => setView(d)}>查看参数</button>
                      <button className="link" disabled={d !== "GPQA" || config?.kind !== "custom"} onClick={openEditor}>编辑参数</button></>}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!visibleDatasets.length && <div className="empty">没有匹配的数据集</div>}
          <Note>当前仅开放 GPQA Lite 单数据集串行探索；MMMU-Pro、AutomationBench、全量及并行执行均不可提交。</Note>
        </section>
      </div>
      <section className="card stack summary">
        <h2>任务摘要</h2>
        <h3>{target ? `${target.model_key} / ${target.model_version}` : "未选择模型服务"}</h3>
        <span>模型标识：{target?.model_key || "未选择"}</span>
        <span>配置：{config ? `${config.display_name} · ${config.version_label}` : "未选择"}</span>
        <dl className="planning-checklist" aria-label="提交前检查">
          <div><dt>模型服务</dt><dd>{target ? "已选择" : "待选择"}</dd></div>
          <div><dt>执行资源</dt><dd>{resource ? "已选择" : "待选择"}</dd></div>
          <div><dt>数据集配置</dt><dd>{config ? "GPQA Lite · 已配置" : "待配置"}</dd></div>
        </dl>
        <fieldset className="run-mode-options">
          <legend>运行方式</legend>
          <div className="run-mode-choices">
            <label className="is-selected"><input type="radio" name="evaluation-run-mode" value="串行" checked readOnly /><span>串行</span></label>
            <label><input type="radio" name="evaluation-run-mode" value="并行" disabled readOnly /><span>并行</span></label>
          </div>
          <p className="run-mode-description">单数据集串行执行；并行与 Release 发布流程不在当前探索路径内。</p>
        </fieldset>
        <section className="summary-scope">
          <div className="spread"><h3>测评范围</h3><strong>{config ? 1 : 0} 个数据集</strong></div>
          <p>Lite {config ? 1 : 0} · 最多 5 次模型请求</p>
          <details>
            <summary>展开选择明细</summary>
            <div className="summary-dataset-list">
              {config ? <div><div className="spread"><b>GPQA</b><span>{(config.items as Record<string, Param>).GPQA.scope}</span></div><small>预计耗时：暂无可靠估算</small></div> : <p>尚未选择配置</p>}
            </div>
          </details>
        </section>
        <div className="total-duration" role="status" aria-live="polite">
          <div className="total-duration-heading"><span>测评预计总耗时</span><span className="badge">串行 · {config ? 1 : 0} 个数据集</span></div>
          <strong>暂无可靠估算</strong>
          <p>不含排队及报告分析耗时。</p>
        </div>
        <div className="console-submit-status" role="status">
          {message || (!target ? "请选择已保存的 DeepSeek 服务。" : !config ? "请选择符合探索条件的配置。" : !resource ? "请选择执行资源。" : "提交将创建真实测评任务，可能产生模型调用费用。")}
        </div>
        <SubmissionReview config={loadingDefault ? null : config} target={target} resource={resource} resourceKind={resourceKind} busy={busy} submit={() => void submit(config, target, resource, resourceKind)} />
      </section>
      {view && viewParams && (
        <div className="dataset-overlay" onClick={() => setView(null)}>
          <section className="dataset-dialog readable-config-dialog" role="dialog" aria-modal="true" aria-label={`${view} 数据集参数`} onClick={(e) => e.stopPropagation()}>
            <div className="spread">
              <div><h3>{view} 数据集参数</h3><p className="muted">来自已保存配置版本，仅供查看。</p></div>
              <span className="badge neutral">只读</span>
            </div>
            <div className="readable-config-scroll">
              <dl className="readable-config-list">
                {[
                  ["测评范围", viewParams.scope, "使用配置绑定的 Lite 清单。"],
                  ["回答长度上限", `${viewParams.output.toLocaleString()} Token`, "限制每次回答的生成长度。"],
                  ["同时处理数量", `${viewParams.concurrency} 个请求`, "后台将按探索路径再次校验。"],
                  ["回答随机性", viewParams.temperature, "生成参数来自所选配置版本。"],
                  ["候选内容范围", viewParams.top_p, "生成参数来自所选配置版本。"],
                ].map(([label, value, help]) => <div key={label}><dt>{label}</dt><dd><strong>{value}</strong><p>{help}</p></dd></div>)}
              </dl>
              <details className="raw-config-details"><summary>查看原始配置（JSON）</summary><pre className="snapshot">{JSON.stringify(viewParams, null, 2)}</pre></details>
            </div>
            <div className="readable-config-footer"><button autoFocus onClick={() => setView(null)}>关闭</button></div>
          </section>
        </div>
      )}
      {drawer && config?.kind === "custom" && (
        <ConfigurationDrawer>
          <h2>自定义配置</h2>
          <div className="workflow-grid">
            <aside className="workflow-datasets"><DatasetTree items={["GPQA"]} selected={["GPQA"]} active="GPQA" /></aside>
            <ParameterCards items={["GPQA"]} active="GPQA" params={draftParams} onChange={setDraftParams} />
          </div>
          <div className="config-save-panel">
            <h3>保存为新配置</h3>
            <div className="config-save-fields">
              <label><span>配置名称 *</span><input aria-label="新配置名称" required value={newConfigName} onChange={(e) => setNewConfigName(e.target.value)} placeholder="例如：GPQA Lite 专项验证" /></label>
              <label><span>版本名称 *</span><input aria-label="新配置版本名称" required value={newVersionName} onChange={(e) => setNewVersionName(e.target.value)} placeholder="例如：初版" /></label>
            </div>
            <p className="config-save-help">测评只能引用后端已保存的配置版本；保存会保留当前 Profile 绑定，符合探索条件的新版本将自动选用。</p>
          </div>
          <div className="actions">
            <button onClick={() => setDrawer(false)}>取消</button>
            <button
              disabled={saving || !newConfigName.trim() || !newVersionName.trim() || !draftParams.GPQA}
              className="primary"
              onClick={async () => {
                if (saving || !config) return;
                const name = newConfigName.trim();
                const version = newVersionName.trim();
                const key = `custom-${crypto.randomUUID()}`;
                const items = { GPQA: draftParams.GPQA };
                setSaving(true);
                try {
                  const row = await apiPost<components["schemas"]["CreatedConfig"]>("/test-configs", {
                    config_key: key,
                    display_name: name,
                    version_label: version,
                    expected_version: 0,
                    items,
                    profile_bindings: { GPQA: config.profile_bindings.GPQA },
                  });
                  const saved: Config = {
                    id: row.id,
                    config_key: key,
                    display_name: name,
                    version: row.version,
                    version_label: version,
                    kind: "custom",
                    content_hash: row.content_hash,
                    approval_status: "not_required",
                    source_url: null,
                    source_revision: null,
                    source_sha256: null,
                    approved_by: null,
                    items,
                    profile_bindings: config.profile_bindings,
                  };
                  setProfiles([...profiles, {
                    id: key,
                    name,
                    source: "后端持久化",
                    official: false,
                    persistedVersion: row.version,
                    versions: [version],
                    items: ["GPQA"],
                    data: { [version]: structuredClone(items) },
                  }]);
                  configs.retry();
                  if (eligibleConfig(saved)) {
                    setConfig(saved);
                    notify("新配置已保存到后端并自动选用。");
                  } else {
                    setConfig(null);
                    notify("新配置已保存，但不符合 GPQA Lite 探索条件，未自动选用。");
                  }
                  setDrawer(false);
                } catch (error) {
                  notify(error instanceof Error ? error.message : "配置未保存");
                } finally { setSaving(false); }
              }}
            >保存新配置并返回</button>
          </div>
        </ConfigurationDrawer>
      )}
    </div>
  );
}
