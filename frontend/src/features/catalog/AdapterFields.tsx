const fieldHelp: Record<string, [string, string]> = {
  output: ["输出长度上限", "旧版探索测评的输出 token 上限，与完整工具配置独立保存。"],
  concurrency: ["并发数量", "旧版探索路径同时处理的请求数量。"],
  scope: ["数据范围", "全量或 Lite；Lite 需要绑定确定性的样本清单。"],
  tool: ["测评工具", "执行测评的工具标识，按标准仓原值传递。"],
  subcommand: ["测评方式", "工具子命令：llm_accuracy 为模型精度测评，harbor_agent 为 Agent 测评。"],
  params: ["测评参数", "传给适配器的参数对象，保持标准仓嵌套结构。"],
  agent_name: ["智能体名称", "执行任务所采用的 Agent 实现名称。"],
  agent_kwargs: ["智能体设置", "传入 Agent 实现的附加配置。"],
  reasoning_effort: ["推理强度", "模型或 Agent 使用的推理强度选项，具体含义由对应实现定义。"],
  llm_kwargs: ["模型生成设置", "Agent 调用语言模型时使用的生成参数。"],
  generation_kwargs: ["生成设置", "常规模型测评的生成参数，按对应服务能力校验。"],
  max_tokens: ["输出长度上限", "每次调用允许生成的最大 token 数。"],
  max_out_len: ["输出长度上限", "适配器传给测评工具的最大输出 token 数。"],
  temperature: ["采样温度", "影响生成随机性的参数；有效范围由实际模型服务决定。"],
  top_p: ["核采样概率", "按累计概率选择候选 token 的采样阈值。"],
  model_info: ["模型能力与计价", "提供给工具的上下文、输出及成本元数据，不代表平台已验证。"],
  max_input_tokens: ["输入容量上限", "工具配置声明的最大输入 token 数。"],
  max_output_tokens: ["输出容量上限", "工具配置声明的最大输出 token 数。"],
  input_cost_per_token: ["输入单价", "工具使用的每输入 token 成本；币种及计价依据须以来源约定为准。"],
  output_cost_per_token: ["输出单价", "工具使用的每输出 token 成本；值为零不代表模型服务免费。"],
  path: ["数据或任务路径", "执行环境中的数据、任务或模型路径，含义依工具子命令而定。"],
  dataset_abbr: ["数据集标识", "工具内部用于识别数据集的简称，不能替代数据版本。"],
  datasets: ["数据集配置", "工具的数据集配置别名列表，数组按整体保存。"],
  model_type: ["模型接口类型", "AISBench 模型配置别名，决定服务请求和响应的处理方式。"],
  n_attempts: ["任务尝试次数", "每个任务配置的尝试次数，不等于平台故障重试次数。"],
  environment_type: ["任务环境", "Agent 任务使用的执行环境类型。"],
  batch_size: ["批处理数量", "测评工具同时处理的样本批量，具体并行行为以工具实现为准。"],
  max_num_workers: ["工作进程数", "测评工具允许的工作进程数量。"],
};
function FieldTitle({ name }: { name: string }) {
  const [label, help] = fieldHelp[name] || [name, "标准仓原始字段，语义以对应工具及该版本配置说明为准。"];
  return <span className="adapter-field-title"><span>{label}</span><small title={name}>{name}</small><span className="adapter-help" tabIndex={0} role="note" aria-label={`${label}：${help}`}><i aria-hidden="true">i</i><span className="adapter-tooltip" role="tooltip">{help}</span></span></span>;
}

type JsonObject = Record<string, unknown>;

export function AdapterFields({ value, onChange, readonly = false }: {
  value: JsonObject; onChange?: (value: JsonObject) => void; readonly?: boolean;
}) {
  return <div className="adapter-fields">{Object.entries(value).filter(([, item]) => item !== undefined).map(([key, item]) => {
    const update = (next: unknown) => onChange?.({ ...value, [key]: next });
    if (item !== null && typeof item === "object" && !Array.isArray(item)) return <section className="adapter-group" key={key}><h4><FieldTitle name={key} /></h4><AdapterFields value={item as JsonObject} onChange={(next) => update(next)} readonly={readonly} /></section>;
    return <label key={key}><FieldTitle name={key} />{key === "scope" ? <select disabled={readonly} value={String(item)} onChange={(event) => update(event.target.value)}><option>全量</option><option>Lite</option></select> : Array.isArray(item) ? <textarea disabled={readonly} defaultValue={JSON.stringify(item)} onChange={(event) => { try { const next: unknown = JSON.parse(event.target.value); if (!Array.isArray(next)) throw Error(); event.target.setCustomValidity(""); update(next); } catch { event.target.setCustomValidity("请输入合法 JSON 数组"); } }} /> : typeof item === "boolean" ? <select disabled={readonly} value={String(item)} onChange={(event) => update(event.target.value === "true")}><option>true</option><option>false</option></select> : <input disabled={readonly} type={typeof item === "number" ? "number" : "text"} value={item == null ? "" : String(item)} onChange={(event) => update(typeof item === "number" ? Number(event.target.value) : event.target.value)} />}</label>;
  })}</div>;
}
