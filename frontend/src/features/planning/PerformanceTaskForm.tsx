import { useEffect, useRef, useState } from "react";
import { Activity, ArrowUpRight, Check, CircleCheck, Network, Server, ShieldCheck, SlidersHorizontal } from "lucide-react";
import "./PerformanceTaskForm.css";
import { ManagementDrawer } from "../../shared/ui/ManagementDrawer";
import { ModelServices } from "../resources/ModelServices";
import { serviceLabel } from "../resources/serviceKind";
import { apiGet, apiPost } from "../../shared/api";
import { useOptions } from "../evaluation/hooks";
import type { Resource, Target } from "../evaluation/types";

type Props = { poolRevision: number; onManagePool: (add?: boolean) => void };
type Check = {
  id: string; state: string;
  result?: { execution_ready?: boolean; preflight_valid_until?: string; reason?: string;
    blocking_reasons?: string[]; dataset_checks?: { blocking_reasons: string[] }[] };
};

function NumberField({ label, value, set, max, min = 1 }: {
  label: string; value: string; set: (s: string) => void; max: number; min?: number;
}) {
  return <label className="pf-field"><span>{label}</span>
    <input type="number" min={min} max={max} required value={value} onChange={event => set(event.target.value)} />
  </label>;
}

export function PerformanceTaskForm({ poolRevision, onManagePool }: Props) {
  const targets = useOptions<Target>("/target-bindings");
  const nodes = useOptions<Resource>("/ssh-resources");
  const retry = useRef(nodes.retry);
  retry.current = nodes.retry;
  useEffect(() => { if (poolRevision) retry.current(); }, [poolRevision]);
  const [kind, setKind] = useState("inference");
  const [target, setTarget] = useState("");
  const [managingServices, setManagingServices] = useState(false);
  function useService(id: string) {
    setTarget(id);
    setManagingServices(false);
    targets.retry();
  }
  const [resource, setResource] = useState("");
  const [input, setInput] = useState("512");
  const [output, setOutput] = useState("128");
  const [requests, setRequests] = useState("4");
  const [parallel, setParallel] = useState("1");
  const [sessions, setSessions] = useState("1");
  const [variant, setVariant] = useState("256k");
  const [mode, setMode] = useState("smoke");
  const [seconds, setSeconds] = useState("60");
  const [traces, setTraces] = useState("1");
  const [check, setCheck] = useState<Check | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [verifiedBody, setVerifiedBody] = useState("");
  const pending = useRef<{ body: string; key: string } | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const levels = sessions.trim().split(/[,，\s]+/).map(Number);
  const validLevels = levels.every(n => Number.isInteger(n) && n >= 1 && n <= 256)
    && new Set(levels).size === levels.length;
  const perLevel = Number(seconds);
  const validDuration = Number.isInteger(perLevel) && perLevel >= (mode === "benchmark" ? 900 : 1)
    && perLevel <= 86400;
  const measurementSeconds = perLevel * levels.length;
  const body = JSON.stringify({ target_id: target, resource_id: resource, resource_kind: "customer_ssh",
    performance: kind === "inference"
      ? { kind, input_tokens: Number(input), max_output_tokens: Number(output), requests: Number(requests), concurrency: Number(parallel) }
      : { kind, variant, run_mode: mode, duration: Number(seconds), concurrency: levels.length === 1 ? levels[0] : levels,
        ...(mode === "smoke" && traces ? { trace_limit: Number(traces) } : {}) } });
  const currentBody = useRef(body);
  currentBody.current = body;
  useEffect(() => { setCheck(null); setVerifiedBody(""); setMessage(""); }, [body]);
  const checking = !!check && ["running", "pending"].includes(check.state);
  useEffect(() => {
    if (!check || !checking) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      apiGet<Check>(`/planning/probes/${check.id}`, controller.signal)
        .then(value => { if (!controller.signal.aborted) setCheck(value); })
        .catch(() => { if (!controller.signal.aborted) { setMessage("无法读取预检进度，请重新检查。"); setCheck(null); } });
    }, 1000);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [check, checking]);
  const until = check?.result?.preflight_valid_until;
  useEffect(() => {
    if (!until) return;
    const timer = window.setTimeout(() => { setVerifiedBody(""); setCheck(null); setMessage("预检已过期，请重新检查。"); }, Math.max(0, Date.parse(until) - Date.now()));
    return () => clearTimeout(timer);
  }, [until]);
  const ready = verifiedBody === body && check?.state === "completed" && check.result?.execution_ready;
  async function act(submit: boolean) {
    if (busy || !form.current?.reportValidity() || (submit && !ready)) return;
    if (kind === "agentx" && !validLevels) {
      setMessage("请输入 1 至 256 之间的不同并发数，多个档位用逗号分隔。"); return;
    }
    setBusy(true); setMessage("");
    try {
      if (submit) {
        if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() };
        const result = await apiPost<{ run_id: string }>("/evaluation-tasks", JSON.parse(body), pending.current.key);
        location.hash = `#run/${result.run_id}`;
      } else {
        setCheck(null); setVerifiedBody("");
        const result = await apiPost<Check>("/planning/resources/preflight", JSON.parse(body));
        if (body === currentBody.current) { setVerifiedBody(body); setCheck(result); }
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : "请求失败，请重试。"); }
    finally { setBusy(false); }
  }
  const status = checking ? "正在检查执行环境…" : ready ? "环境检查通过"
    : check ? ["环境检查未通过", check.result?.reason, ...(check.result?.blocking_reasons || []),
        ...(check.result?.dataset_checks || []).flatMap(row => row.blocking_reasons)].filter(Boolean).join(" · ")
    : !target || !resource ? "选择模型服务和 SSH 节点后可进行预检" : "请先完成环境预检";
  return <form ref={form} className="card perf-form" onSubmit={event => { if (event.target === event.currentTarget) { event.preventDefault(); void act(true); } }}>
    <fieldset className="pf-methods">
      <legend>性能任务配置</legend>
      <div className="pf-method-options" role="radiogroup" aria-label="测评方式">
        {[
          { id: "inference", name: "普通推理", description: "按输入长度与并发数测量推理性能", Icon: Activity },
          { id: "agentx", name: "AgentX 轨迹回放", description: "使用 Weka 语料回放多轮会话", Icon: Network },
        ].map(({ id, name, description, Icon }) => <label key={id} className="pf-method">
          <input type="radio" name="performance-method" aria-label={name} checked={kind === id} onChange={() => setKind(id)} />
          <Icon className="pf-method-icon" size={22} aria-hidden="true" />
          <span><b>{name}</b><small>{description}</small></span>
          <span className="pf-choice" aria-hidden="true">{kind === id && <Check size={12} />}</span>
        </label>)}
      </div>
    </fieldset>
    <div className="pf-body">
      <section className="pf-resources">
        <h3><Server size={17} />执行资源</h3>
        <div className="pf-fields">
          <div className="pf-node"><div className="pf-node-label"><label htmlFor="perf-model-service">模型服务</label>
            <ManagementDrawer title="管理模型服务" open={managingServices} onOpenChange={setManagingServices} onDismiss={targets.retry}><ModelServices onUse={useService} /></ManagementDrawer></div>
            <select id="perf-model-service" aria-label="模型服务" required value={target} onChange={e => setTarget(e.target.value)}>
            <option value="">选择模型服务</option>{targets.rows.map(t => <option key={t.id} value={t.id}>{t.service_name || t.remote_model} · {serviceLabel(t.service_kind)}</option>)}</select></div>
          <div className="pf-node">
            <div className="pf-node-label"><label htmlFor="perf-ssh-node">SSH 执行节点</label>
              <button type="button" className="link" aria-label="管理 SSH 资源池" onClick={() => onManagePool()}>管理资源池 <ArrowUpRight size={13} /></button></div>
            <select id="perf-ssh-node" required value={resource} onChange={e => setResource(e.target.value)}>
              <option value="">选择 SSH 节点</option>{nodes.rows.map(n => <option key={n.id} value={n.id}>{n.binding_key}</option>)}</select>
          </div>
        </div>
        {(nodes.error || targets.error) && <p role="alert">{nodes.error || targets.error}</p>}
      </section>
      <section className="pf-load">
        <h3><SlidersHorizontal size={17} />负载参数</h3>
        <div className="pf-fields">
    {kind === "inference" ? <>
      <NumberField label="目标输入长度（token）" value={input} set={setInput} max={1048576} />
      <NumberField label="最大输出长度（token）" value={output} set={setOutput} max={1048576} />
      <NumberField label="并发数" value={parallel} set={setParallel} max={256} />
      <NumberField label="请求数" value={requests} set={setRequests} max={100000} />
    </> : <>
      <label className="pf-field">Weka 语料<select aria-label="Weka 语料" value={variant} onChange={e => setVariant(e.target.value)}><option>256k</option><option>full</option></select></label>
      <label className="pf-field">运行模式<select aria-label="运行模式" value={mode} onChange={e => { setMode(e.target.value); setSeconds(e.target.value === "smoke" ? "60" : "900"); }}><option value="smoke">smoke · 链路验证</option><option value="benchmark">benchmark · 正式测评</option></select></label>
      <label className="pf-field">会话并发档位<input required value={sessions} placeholder="例如 1,4,8" onChange={e => setSessions(e.target.value)} /></label>
      <NumberField label="每档测量时长（秒）" value={seconds} set={setSeconds} min={mode === "benchmark" ? 900 : 1} max={86400} />
      {mode === "smoke" && <label className="pf-field">Trace 数量上限（可选）<input type="number" min="1" value={traces} onChange={e => setTraces(e.target.value)} /></label>}
    </>}
    </div>
    {kind === "agentx" && <div className="pf-scope" aria-live="polite">
      <p>{mode === "benchmark"
        ? "当前使用本地 Weka 语料。有效的 benchmark 结果仅供内部对比（internal_only）。"
        : "smoke 用于验证回放链路，报告的可比范围为 smoke。"}</p>
      {validLevels && validDuration && <p>
        {levels.length} 档 × 每档 {perLevel} 秒，配置的测量时长合计 {measurementSeconds % 60 === 0
          ? `${measurementSeconds / 60} 分钟` : `${measurementSeconds} 秒`}。预热、档间冷却和归档另计。
      </p>}
    </div>}
      </section>
    </div>
    <div className="pf-footer">
      <div className="pf-feedback">
        <p role="status" className={ready ? "pf-ready" : undefined}>{ready ? <CircleCheck size={17} /> : <ShieldCheck size={17} />}{status}</p>
        {message && <p role="alert">{message}</p>}
      </div>
      <div className="pf-actions">
        <button type="button" disabled={busy || checking} onClick={() => void act(false)}>环境预检</button>
        <button type="submit" className="primary" disabled={busy || !ready}>提交性能测评</button>
      </div>
    </div>
  </form>;
}
