import { useState, useEffect } from "react";
import {
  Home,
  SlidersHorizontal,
  ClipboardList,
  ChartNoAxesColumnIncreasing,
  Trophy,
  Info,
  CheckCircle2,
  Clock3,
  Play,
  Search,
  Layers,
  Activity,
  ArrowLeft,
  ExternalLink,
  Sparkles,
  FileText,
  ChevronRight,
  Zap,
  GraduationCap,
  Image,
  CircleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import "./app.css";
const datasets = ["GPQA", "MMMU-Pro", "AutomationBench"];
const descriptions = [
  "高难度研究生水平的科学问答评测集。",
  "面向多模态理解的综合评测集（图文、表格、图表等）。",
  "面向通用自动化与工具使用能力的 Agent 评测集（公开任务）。",
];
const menus = [
  { id: "home", label: "首页", icon: Layers },
  { id: "console", label: "控制台", icon: Home },
  { id: "config", label: "测试配置", icon: SlidersHorizontal },
  { id: "tasks", label: "任务管理", icon: ClipboardList },
  { id: "reports", label: "报告管理", icon: ChartNoAxesColumnIncreasing },
  { id: "leaderboard", label: "测评榜单", icon: Trophy },
];

function DatasetSummary({
  items,
  preferred,
}: {
  items: string[];
  preferred?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ordered =
    preferred && items.includes(preferred)
      ? [preferred, ...items.filter((d) => d !== preferred)]
      : items;
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);
  const filtered = ordered.filter((d) =>
    d.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="dataset-summary">
      {ordered.slice(0, 2).map((d, i) => (
        <span
          key={d}
          title={d}
          className={`badge dataset-tag ${i === 1 ? "dataset-second" : ""}`}
        >
          {d}
        </span>
      ))}
      {items.length > 2 && (
        <button
          className="dataset-more"
          aria-label={`查看全部 ${items.length} 个数据集`}
          aria-haspopup="dialog"
          onClick={() => {
            setQuery("");
            setOpen(true);
          }}
        >
          <span className="dataset-desktop-count">+{items.length - 2}</span>
          <span className="dataset-mobile-count">+{items.length - 1}</span>
        </button>
      )}
      {items.length === 2 && (
        <button
          className="dataset-more dataset-mobile-more"
          aria-label="查看全部 2 个数据集"
          onClick={() => {
            setQuery("");
            setOpen(true);
          }}
        >
          +1
        </button>
      )}
      {open &&
        createPortal(
          <div className="dataset-overlay" onClick={() => setOpen(false)}>
            <section
              className="dataset-dialog"
              role="dialog"
              aria-modal="true"
              aria-label="完整数据集列表"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="spread">
                <h3>
                  测评数据集 <Badge>共 {items.length} 个</Badge>
                </h3>
                <button autoFocus onClick={() => setOpen(false)}>
                  关闭
                </button>
              </div>
              <label className="search">
                <Search size={16} />
                <input
                  aria-label="搜索数据集"
                  placeholder="搜索数据集名称"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <ul>
                {filtered.map((d) => (
                  <li key={d}>
                    {d}
                    {d === preferred && <Badge>当前筛选</Badge>}
                  </li>
                ))}
              </ul>
              {!filtered.length && (
                <div className="empty">未找到匹配的数据集</div>
              )}
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}

function Card({
  title,
  children,
  className = "",
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}
function Badge({
  children,
  tone = "purple",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function Select({
  label,
  options,
  value,
  onChange,
}: {
  label?: string;
  options: string[];
  value?: string;
  onChange?: (v: string) => void;
}) {
  return (
    <label className="select-field">
      {label && <span>{label}</span>}
      <select
        aria-label={label || options[0]}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
      >
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </label>
  );
}
function Tabs({
  items,
  value,
  onChange,
}: {
  items: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="tabs">
      {items.map((i) => (
        <button
          key={i}
          className={value === i ? "active" : ""}
          onClick={() => onChange(i)}
        >
          {i}
        </button>
      ))}
    </div>
  );
}
function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Info size={17} />
      {children}
    </div>
  );
}
const reports = [26, 25, 24, 23, 22, 21].map((n, i) => ({
  id: `RPT-0${n}`,
  task: `EVAL-0${n}`,
  model: i === 2 || i === 4 ? "Demo Vision B" : "Demo Vision A",
  modelId: i === 2 || i === 4 ? "demo-vlm-002" : "demo-vlm-001",
  version: i % 3 === 0 ? "RC" : "Release",
  status: i === 0 ? "分析中" : i === 2 ? "分析失败" : "分析成功",
  date: `2026-11-${i < 2 ? "09" : i < 4 ? "08" : "07"} ${["14:30", "11:20", "17:40", "10:15", "16:50", "10:30"][i]}`,
}));
export function App() {
  const [page, setPage] = useState(location.hash.slice(1) || "home");
  const [reportId, setReportId] = useState("RPT-023");
  const [toast, setToast] = useState("");
  const go = (p: string, id?: string) => {
    if (id) setReportId(id);
    location.hash = p;
    setPage(p);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    const fn = () => setPage(location.hash.slice(1) || "home");
    window.addEventListener("hashchange", fn);
    return () => window.removeEventListener("hashchange", fn);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(t);
  }, [toast]);
  const title = page.startsWith("task/")
    ? "任务详情"
    : page === "detail"
      ? "测评报告"
      : menus.find((m) => m.id === page)?.label || "控制台";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img
            className="brand-logo"
            src="/brand/autoeval-logo.svg"
            alt="AutoEval"
          />
        </div>
        <div className="workspace">工作空间：示例评测空间</div>
        <nav>
          {menus.map((m) => (
            <a
              key={m.id}
              href={`#${m.id}`}
              className={
                page === m.id ||
                (page.startsWith("task/") && m.id === "tasks") ||
                (page === "detail" && m.id === "reports")
                  ? "selected"
                  : ""
              }
            >
              <m.icon size={22} />
              {m.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="dot" /> AutoEval Demo{" "}
          <small>前端静态预览 · v0.1</small>
        </div>
      </aside>
      <main className="main">
        <div className="breadcrumb">
          {page === "detail" ? (
            <button onClick={() => go("reports")}>报告管理</button>
          ) : (
            <span>AutoEval</span>
          )}
          <ChevronRight size={14} />
          {page === "detail" ? reportId : title}
          <Badge>示例数据</Badge>
        </div>
        <header className="page-heading">
          <div>
            <h1>{title}</h1>
            <p>
              {
                (
                  {
                    home: "从一次测评开始，让模型能力清晰可见。",
                    console: "配置模型，开启新一轮测评。",
                    config: "按模型与数据集分别维护测试参数。",
                    tasks: "追踪每一次测评，定位每一个问题。",
                    reports: "查看各模型每次测评报告，追溯历史结果。",
                    leaderboard: "在一致测试条件下比较模型表现。",
                    detail: "查看测评结果、基准对比与自动分析示例。",
                  } as Record<string, string>
                )[page]
              }
            </p>
          </div>
          {page === "detail" && (
            <button className="primary" onClick={() => go("tasks")}>
              <ExternalLink size={16} />
              查看任务
            </button>
          )}
        </header>
        {page === "home" && <Overview go={go} />}
        {page === "console" && <Console go={go} notify={setToast} />}
        {page === "config" && <Config go={go} notify={setToast} />}
        {
          <div hidden={page !== "tasks"}>
            <Tasks go={go} />
          </div>
        }
        {page.startsWith("task/") && (
          <TaskDetail key={page} task={page.slice(5)} go={go} />
        )}
        <div hidden={page !== "reports"}>
          <Reports go={go} />
        </div>{" "}
        {page === "detail" && (
          <Detail id={reportId} go={go} notify={setToast} />
        )}{" "}
        {page === "leaderboard" && <Leaderboard go={go} />}
        <footer className="page-foot">
          AutoEval · 智能测评平台
          <span>所有数据均为静态示例，不代表真实测评结果</span>
        </footer>
      </main>
      {toast && (
        <div role="status" className="toast">
          <Info size={18} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Console({
  go,
  notify,
}: {
  go: (p: string) => void;
  notify: (s: string) => void;
}) {
  const [model, setModel] = useState("demo-vlm-001");
  const [access, setAccess] = useState("API接入");
  const [mode, setMode] = useState("Lite");
  const [custom, setCustom] = useState(false);
  const [selected, setSelected] = useState(datasets);
  return (
    <div className="console-grid">
      <div className="stack">
        <Card title="模型接入">
          <Tabs
            items={["API接入", "IP/Port拉起"]}
            value={access}
            onChange={setAccess}
          />
          {access === "API接入" ? (
            <div className="form-grid">
              <label>模型ID（modelId）</label>
              <Select
                options={["demo-vlm-001", "demo-vlm-002"]}
                value={model}
                onChange={setModel}
              />
              <label>模型名称</label>
              <input
                value={
                  model.endsWith("001") ? "Demo Vision A" : "Demo Vision B"
                }
                readOnly
              />
              <label>API 地址</label>
              <div className="inline">
                <input defaultValue="https://api.example.com/v1/******" />
                <Badge tone="neutral">未连接 · 静态示例</Badge>
              </div>
              <label>接口类型 / API Key</label>
              <div className="inline">
                <Select options={["OpenAI Compatible"]} />
                <input
                  type="password"
                  placeholder="请输入 API Key"
                  autoComplete="off"
                />
                <button
                  onClick={() => notify("静态预览：暂未接入真实连接测试。")}
                >
                  测试连接
                </button>
              </div>
            </div>
          ) : (
            <div className="stack inset">
              <Notice>仅演示入口，不会启动真实模型服务。</Notice>
              <div className="inline">
                <input aria-label="IP 地址" placeholder="IP 地址" />
                <input aria-label="端口" placeholder="端口" />
                <button
                  onClick={() => notify("演示反馈：本页面未启动真实服务。")}
                >
                  演示拉起
                </button>
              </div>
            </div>
          )}
        </Card>
        <Card title="最新测试配置">
          <div className="form-grid">
            <label>配置版本</label>
            <div className="inline">
              <strong>v1.3</strong>
              <Badge>{model.endsWith("001") ? "RC" : "Release"}</Badge>
              <Badge tone="green">当前模型唯一最新配置</Badge>
            </div>
            <label>配置模式</label>
            <div className="inline">
              <label>
                <input
                  type="radio"
                  checked={!custom}
                  onChange={() => setCustom(false)}
                />{" "}
                默认配置
              </label>
              <label>
                <input
                  type="radio"
                  checked={custom}
                  onChange={() => setCustom(true)}
                />{" "}
                自定义配置
              </label>
            </div>
          </div>
          {custom && (
            <Notice>本次任务临时配置，静态预览不保存或覆盖模型配置。</Notice>
          )}
          <div className="card-bottom">
            <span>各数据集使用独立测试参数</span>
            <button className="link" onClick={() => go("config")}>
              查看 / 编辑测试配置
            </button>
          </div>
        </Card>
        <Card title="测评数据集">
          <div className="inline mode-row">
            <b>测评模式</b>
            <Tabs items={["全量", "Lite"]} value={mode} onChange={setMode} />
            <span className="muted">Lite 子集范围与样本量待配置。</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="全选数据集"
                      checked={selected.length === 3}
                      onChange={(e) =>
                        setSelected(e.target.checked ? datasets : [])
                      }
                    />
                  </th>
                  <th>数据集名称</th>
                  <th>类型标签</th>
                  <th>样本量</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d, i) => (
                  <tr key={d}>
                    <td>
                      <input
                        aria-label={`选择 ${d}`}
                        type="checkbox"
                        checked={selected.includes(d)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, d]
                              : selected.filter((x) => x !== d),
                          )
                        }
                      />
                    </td>
                    <td>
                      <b>{d}</b> {mode === "Lite" && <Badge>Lite</Badge>}
                    </td>
                    <td>
                      <Badge tone={i === 0 ? "blue" : "purple"}>
                        {["科学问答", "多模态", "Agent"][i]}
                      </Badge>
                    </td>
                    <td>待配置</td>
                    <td className="description">{descriptions[i]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Notice>参数按模型及数据集分别维护，所有配置和耗时均为示例。</Notice>
      </div>
      <Card title="任务摘要" className="summary">
        <div className="summary-section">
          <span>测评模型</span>
          <h3>{model.endsWith("001") ? "Demo Vision A" : "Demo Vision B"}</h3>
          <p>modelId：{model}</p>
        </div>
        <div className="summary-section">
          <span>测试配置</span>
          <h3>
            v1.3 <Badge>{model.endsWith("001") ? "RC" : "Release"}</Badge>
          </h3>
        </div>
        <div className="summary-section">
          <span>测评数据集（{selected.length} 个）</span>
          {selected.map((d) => (
            <div className="dataset-check" key={d}>
              <CheckCircle2 size={18} />
              {d}
              {mode === "Lite" && <Badge>Lite</Badge>}
            </div>
          ))}
        </div>
        {["测评预计耗时", "分析预计耗时"].map((t, i) => (
          <div className="estimate" key={t}>
            {i ? <ChartNoAxesColumnIncreasing /> : <Clock3 />}
            <div>
              {t}
              <strong>{i ? "2–4分钟" : "25–40分钟"}</strong>
            </div>
            <Badge>估算示例</Badge>
          </div>
        ))}
        <button
          className="primary launch"
          disabled={!selected.length}
          onClick={() =>
            notify("静态预览：尚未接入测评执行服务，不会创建真实任务。")
          }
        >
          <Play size={18} />
          发起测评
        </button>
        <small className="muted">当前仅展示界面，未连接模型或执行服务。</small>
      </Card>
    </div>
  );
}
function Config({
  go,
  notify,
}: {
  go: (p: string) => void;
  notify: (s: string) => void;
}) {
  const [dataset, setDataset] = useState("GPQA");
  const [model, setModel] = useState("demo-vlm-001");
  const initial = () =>
    Object.fromEntries(
      datasets.map((d, i) => [d, ["2048", String(60 - i * 20), "0.6", "0.95"]]),
    );
  const [values, setValues] = useState(initial);
  const [dirty, setDirty] = useState(false);
  return (
    <div className="stack">
      <Card title="测试模型">
        <div className="model-row">
          <div className="form-grid">
            <label>模型名称</label>
            <Select
              options={["demo-vlm-001", "demo-vlm-002"]}
              value={model}
              onChange={(v) => {
                setModel(v);
                setValues(initial());
                setDirty(false);
              }}
            />
            <label>模型ID（modelId）</label>
            <input readOnly value={model} />
          </div>
          <div>
            <small>最新配置</small>
            <h3>
              v1.3 <Badge>{model.endsWith("001") ? "RC" : "Release"}</Badge>
            </h3>
          </div>
          <div>
            <small>配置状态</small>
            <h3 className={dirty ? "orange-text" : "green-text"}>
              {dirty ? "未保存" : "已保存 · 示例"}
            </h3>
          </div>
        </div>
      </Card>
      <div className="config-grid">
        <Card>
          <h2>
            {dataset} <Badge>当前编辑</Badge>
          </h2>
          <Notice>每个数据集使用独立参数，请从右侧分类目录选择数据集。</Notice>
          <Card title="生成参数" className="inner-card">
            <div className="params">
              {["最大输出长度", "并发数", "temperature", "top_p"].map(
                (l, i) => (
                  <label key={l}>
                    {l}
                    <input
                      type="number"
                      min="0"
                      step={i > 1 ? "0.05" : "1"}
                      value={values[dataset][i]}
                      onChange={(e) => {
                        setValues({
                          ...values,
                          [dataset]: values[dataset].map((v, j) =>
                            j === i ? e.target.value : v,
                          ),
                        });
                        setDirty(true);
                      }}
                    />
                  </label>
                ),
              )}
            </div>
          </Card>
          <Card title="数据范围" className="inner-card">
            <div className="inline">
              <div>
                评测范围
                <p>
                  <Badge>全量 / Lite 由控制台选择</Badge>
                </p>
              </div>
              <div>
                Lite 子集
                <p>
                  <input disabled value="待配置" readOnly />
                </p>
              </div>
              <span className="muted">Lite 样本清单与数量待确认。</span>
            </div>
          </Card>
          {dataset === "AutomationBench" && (
            <Notice>
              公开任务集；领域、工具集与最大步数待固定适配器版本后配置。
            </Notice>
          )}
        </Card>
        <Card title="数据集配置" className="dataset-directory">
          <p>
            模型：<span className="purple-text">{model}</span>
          </p>
          <div className="dataset-groups" aria-label="按类型选择数据集">
            {[
              { type: "科学问答", items: ["GPQA"] },
              { type: "多模态理解", items: ["MMMU-Pro"] },
              { type: "Agent 工作流", items: ["AutomationBench"] },
            ].map((group) => (
              <details className="dataset-group" key={group.type} open>
                <summary>
                  {group.type}
                  <Badge tone="neutral">{group.items.length}</Badge>
                </summary>
                <div className="dataset-branches">
                  {group.items.map((d) => (
                    <button
                      key={d}
                      className={d === dataset ? "active" : ""}
                      aria-pressed={d === dataset}
                      onClick={() => setDataset(d)}
                    >
                      <span>{d}</span>
                      {d === dataset && <Badge>当前编辑</Badge>}
                    </button>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </Card>
      </div>
      <div className="actions">
        <span className="muted">
          保存仅影响后续任务，历史任务保留配置快照。参数数值仅为示例。
        </span>
        <button className="link" onClick={() => go("console")}>
          返回控制台
        </button>
        <button
          onClick={() => {
            setValues(initial());
            setDirty(false);
          }}
        >
          重置更改
        </button>
        <button
          className="primary"
          onClick={() =>
            notify("静态预览：参数更改仅在当前页面保留，尚未保存至服务端。")
          }
        >
          保存测试配置
        </button>
      </div>
    </div>
  );
}
const taskRows = Array.from({ length: 24 }, (_, i) => ({
  name: `EVAL-${String(25 - i).padStart(3, "0")}`,
  model: i % 2 ? "Demo Vision B" : "Demo Vision A",
  version: i % 2 ? "RC" : "Release",
  state: i < 2 ? "执行中" : i === 3 || i === 8 ? "部分成功" : "成功",
  progress: i === 0 ? "12%" : "68%",
  datasets: i < 5 ? datasets : i % 2 ? datasets.slice(0, 2) : datasets.slice(1),
  date: `2026-11-${String(9 - Math.floor(i / 6)).padStart(2, "0")} ${String(14 - Math.floor((i % 6) / 2)).padStart(2, "0")}:${i % 2 ? "15" : "10"}`,
}));
function Tasks({ go }: { go: (p: string, id?: string) => void }) {
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 5;
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("全部状态");
  const [model, setModel] = useState("全部模型");
  const [dataset, setDataset] = useState("全部数据集");
  const filtered = taskRows.filter(
    (r) =>
      r.name.toLowerCase().includes(search.toLowerCase()) &&
      (status === "全部状态" || r.state === status) &&
      (model === "全部模型" || r.model === model) &&
      (dataset === "全部数据集" || r.datasets.includes(dataset)),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const activePage = Math.min(currentPage, pageCount);
  useEffect(() => setCurrentPage(1), [search, status, model, dataset]);
  return (
    <div className="stack">
      <div className="stats">
        {["全部任务", "执行中", "已完成", "执行异常"].map((s, i) => (
          <Card key={s}>
            <div className={`stat-icon tone-${i}`}>
              {i === 0 ? (
                <Layers />
              ) : i === 1 ? (
                <Play />
              ) : i === 2 ? (
                <CheckCircle2 />
              ) : (
                <CircleAlert />
              )}
            </div>
            <div>
              {s}
              <strong>{[24, 2, 20, 2][i]}</strong>
            </div>
          </Card>
        ))}
      </div>
      <div className="filters">
        <Select
          label="模型"
          options={["全部模型", "Demo Vision A", "Demo Vision B"]}
          value={model}
          onChange={setModel}
        />
        <Select
          label="状态"
          options={["全部状态", "执行中", "成功", "部分成功"]}
          value={status}
          onChange={setStatus}
        />
        <Select
          label="数据集"
          options={["全部数据集", ...datasets]}
          value={dataset}
          onChange={setDataset}
        />
        <label className="search">
          <Search size={18} />
          <input
            placeholder="搜索任务名称（如 EVAL-024）"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <Card className="table-card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  "任务名称",
                  "模型",
                  "出口 / 配置版本",
                  "数据集",
                  "状态",
                  "创建时间",
                  "操作",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered
                .slice((activePage - 1) * pageSize, activePage * pageSize)
                .map((r) => (
                  <tr key={r.name}>
                    <td>
                      <button
                        className="link strong"
                        onClick={() => go(`task/${r.name}`)}
                      >
                        {r.name}
                      </button>
                    </td>
                    <td>{r.model}</td>
                    <td>
                      {r.version} <Badge tone="neutral">v1.3</Badge>
                    </td>
                    <td>
                      <DatasetSummary items={r.datasets} preferred={dataset} />
                    </td>
                    <td>
                      <Badge
                        tone={
                          r.state === "成功"
                            ? "green"
                            : r.state === "部分成功"
                              ? "orange"
                              : "purple"
                        }
                      >
                        {r.state} {r.state === "执行中" ? r.progress : ""}
                      </Badge>
                    </td>
                    <td>{r.date}</td>
                    <td>
                      <button
                        className="link"
                        onClick={() => go(`task/${r.name}`)}
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!filtered.length && <div className="empty">没有符合条件的任务</div>}
        </div>
      </Card>
      <div className="pagination" aria-label="任务列表分页">
        <span>
          共 {filtered.length} 条 · 每页 {pageSize} 条
        </span>
        <button
          disabled={activePage === 1}
          onClick={() => setCurrentPage(activePage - 1)}
        >
          上一页
        </button>
        {Array.from({ length: pageCount }, (_, i) => (
          <button
            key={i}
            aria-current={activePage === i + 1 ? "page" : undefined}
            className={activePage === i + 1 ? "primary" : ""}
            onClick={() => setCurrentPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
        <button
          disabled={activePage === pageCount}
          onClick={() => setCurrentPage(activePage + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
function TaskDetail({
  task,
  go,
}: {
  task: string;
  go: (p: string, id?: string) => void;
}) {
  const [tab, setTab] = useState("执行进度");
  const row = taskRows.find((r) => r.name === task);
  if (!row)
    return (
      <Card>
        <p>未找到该任务</p>
        <button onClick={() => go("tasks")}>返回任务列表</button>
      </Card>
    );
  return (
    <div className="stack">
      <button className="link back" onClick={() => go("tasks")}>
        <ArrowLeft size={16} />
        返回任务列表
      </button>
      <Card
        title={
          <div className="spread">
            <span>{task} 执行详情</span>
            <small>
              模型：{row.model}　 |　 出口版本：{row.version}　 |　 配置：v1.3
            </small>
          </div>
        }
      >
        <Tabs
          items={["执行进度", "日志", "关键轨迹", "配置快照"]}
          value={tab}
          onChange={setTab}
        />
        {tab === "执行进度" ? (
          <div className="task-columns">
            <Card title="按数据集执行状态" className="inner-card">
              {datasets.map((d, i) => (
                <div className="progress-row" key={d}>
                  <b>{d}</b>
                  <span>{["完成", "执行中 68%", "待执行"][i]}</span>
                  <progress max="100" value={[100, 68, 0][i]} />
                  <span>{[100, 68, 0][i]}%</span>
                </div>
              ))}
            </Card>
            <Logs />
          </div>
        ) : tab === "日志" ? (
          <Logs />
        ) : tab === "配置快照" ? (
          <pre className="snapshot">
            {JSON.stringify(
              {
                modelId:
                  row.model === "Demo Vision A"
                    ? "demo-vlm-001"
                    : "demo-vlm-002",
                version: "v1.3",
                exportVersion: row.version,
                mode: "Lite",
                datasets,
                credentials: "已脱敏",
                snapshot: "静态示例",
              },
              null,
              2,
            )}
          </pre>
        ) : (
          <div className="trace">
            <Badge>样本 #018 · 示例</Badge>
            <h3>工具调用参数校验未通过</h3>
            <p>输入：查询工作流并创建一条待办记录。</p>
            <p>响应：调用 create_task，缺少必填参数 title。</p>
            <Notice>断言未通过属于有效测评结果，不等于执行失败。</Notice>
          </div>
        )}
        <div className="card-bottom">
          <span className="muted">日志与进度为固定示例，不会实时执行。</span>
          <button className="link" onClick={() => go("detail", "RPT-023")}>
            查看关联报告
          </button>
        </div>
      </Card>
    </div>
  );
}
function Logs() {
  return (
    <div className="logs">
      <div>
        <span className="dot" /> 执行日志（静态示例）
      </div>
      <pre>{`[14:10:03]  任务 EVAL-024 启动，初始化执行环境…\n[14:10:05]  加载模型：Demo Vision A（出口版本 RC）\n[14:10:08]  解析评测配置，数据集：GPQA、MMMU-Pro、AutomationBench\n[14:10:12]  开始执行数据集 GPQA…\n[14:12:37]  数据集 GPQA 执行完成，结果已记录。\n[14:12:39]  开始执行数据集 MMMU-Pro…\n[14:20:18]  MMMU-Pro 执行中：已完成 68%…`}</pre>
    </div>
  );
}
function Reports({ go }: { go: (p: string, id?: string) => void }) {
  const [model, setModel] = useState("全部模型");
  const [version, setVersion] = useState("全部出口版本");
  const [dataset, setDataset] = useState("全部数据集");
  const [status, setStatus] = useState("全部分析状态");
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 5;
  useEffect(() => setCurrentPage(1), [model, version, dataset, status, search]);
  const filtered = reports.filter(
    (r) =>
      (model === "全部模型" || r.model === model) &&
      (version === "全部出口版本" || r.version === version) &&
      (status === "全部分析状态" || r.status === status) &&
      `${r.id} ${r.task}`.toLowerCase().includes(search.toLowerCase()),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const activePage = Math.min(currentPage, pageCount);
  return (
    <div className="stack">
      <Card>
        <div className="filters">
          <Select
            label="模型"
            options={["全部模型", "Demo Vision A", "Demo Vision B"]}
            value={model}
            onChange={setModel}
          />
          <Select
            label="出口版本"
            options={["全部出口版本", "RC", "Release"]}
            value={version}
            onChange={setVersion}
          />
          <Select
            label="数据集"
            options={["全部数据集", ...datasets]}
            value={dataset}
            onChange={setDataset}
          />
          <Select
            label="分析状态"
            options={["全部分析状态", "分析中", "分析成功", "分析失败"]}
            value={status}
            onChange={setStatus}
          />
          <label className="search">
            <Search size={18} />
            <input
              placeholder="搜索报告或任务"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
      </Card>
      <Card
        title={
          <div className="inline">
            全部报告 <Badge>{filtered.length}</Badge>
            <small>每次测评独立保留报告。</small>
          </div>
        }
      >
        <div className="table-wrap">
          <table className="reports-table">
            <thead>
              <tr>
                {[
                  "报告名称",
                  "模型与 modelId",
                  "出口版本",
                  "测评数据集 / 结果覆盖",
                  "生成时间",
                  "分析状态",
                  "操作",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered
                .slice((activePage - 1) * pageSize, activePage * pageSize)
                .map((r) => (
                  <tr key={r.id}>
                    <td>
                      <button
                        className="link strong underline"
                        onClick={() => go("detail", r.id)}
                      >
                        {r.id}
                      </button>
                      <small>任务：{r.task}</small>
                    </td>
                    <td>
                      <b>{r.model}</b>
                      <small>
                        modelId：{r.modelId} <Badge tone="neutral">v1.3</Badge>
                      </small>
                    </td>
                    <td>{r.version}</td>
                    <td>
                      <DatasetSummary items={datasets} preferred={dataset} />
                      <small>有效覆盖 3 / 3 · 示例</small>
                    </td>
                    <td>{r.date}</td>
                    <td>
                      <Badge
                        tone={
                          r.status === "分析成功"
                            ? "green"
                            : r.status === "分析失败"
                              ? "orange"
                              : "purple"
                        }
                      >
                        {r.status}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="link"
                        onClick={() => go("detail", r.id)}
                      >
                        查看报告
                      </button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!filtered.length && <div className="empty">没有符合条件的报告</div>}
        </div>
        <div className="card-bottom">
          <span>
            <Info size={16} /> 分析中或分析失败时，仍可查看原始测评结果。
          </span>
        </div>
      </Card>
      <div className="pagination" aria-label="报告列表分页">
        <span>
          共 {filtered.length} 条 · 每页 {pageSize} 条
        </span>
        <button
          disabled={activePage === 1}
          onClick={() => setCurrentPage(activePage - 1)}
        >
          上一页
        </button>
        {Array.from({ length: pageCount }, (_, i) => (
          <button
            key={i}
            aria-current={activePage === i + 1 ? "page" : undefined}
            className={activePage === i + 1 ? "primary" : ""}
            onClick={() => setCurrentPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
        <button
          disabled={activePage === pageCount}
          onClick={() => setCurrentPage(activePage + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
function Detail({
  id,
  go,
  notify,
}: {
  id: string;
  go: (p: string, id?: string) => void;
  notify: (s: string) => void;
}) {
  const [tab, setTab] = useState("基准对比");
  const r = reports.find((r) => r.id === id) || reports[3];
  return (
    <div className="stack">
      <button className="link back" onClick={() => go("reports")}>
        <ArrowLeft size={16} />
        返回报告列表
      </button>
      <Card>
        <div className="inline metadata">
          模型：<b>{r.model}</b>
          <span>│</span>modelId：{r.modelId}
          <span>│</span>出口版本：{r.version}
          <span>│</span>配置：<b>v1.3</b>
          <Badge>有效覆盖 3/3 · 示例</Badge>
        </div>
      </Card>
      <div className="stats metric-stats">
        {["GPQA", "MMMU-Pro", "Agent任务成功率", "输出吞吐"].map((s, i) => (
          <Card key={s}>
            <div className="stat-icon">
              {i === 0 ? (
                <GraduationCap />
              ) : i === 1 ? (
                <Image />
              ) : i === 2 ? (
                <Layers />
              ) : (
                <Zap />
              )}
            </div>
            <div>
              {s} <Info size={13} />
              <strong>{["72.4%", "61.8%", "48.0%", "126 tok/s"][i]}</strong>
            </div>
          </Card>
        ))}
      </div>
      <div className="report-grid">
        <Card>
          <Tabs
            items={["精度结果", "性能结果", "Agent结果", "基准对比"]}
            value={tab}
            onChange={setTab}
          />
          <h2 className="section-heading">
            {tab === "基准对比" ? "基准对比结果" : tab}
          </h2>
          {tab === "基准对比" || tab === "精度结果" ? (
            <>
              <div className="chart-legend">
                <span className="legend purple" />
                实测值（示例）
                {tab === "基准对比" && (
                  <>
                    <span className="legend gray" />
                    JSON基准（示例）
                  </>
                )}
              </div>
              <div className="bar-chart">
                <div className="y-axis">
                  100%<span>80%</span>
                  <span>60%</span>
                  <span>40%</span>
                  <span>20%</span>
                  <span>0%</span>
                </div>
                <div className="chart-plot">
                  {datasets.map((d, i) => (
                    <div className="bar-group" key={d}>
                      <div className="bars">
                        <div style={{ height: `${[72.4, 61.8, 48][i]}%` }}>
                          <b>{[72.4, 61.8, 48][i]}%</b>
                        </div>
                        {tab === "基准对比" && (
                          <div
                            className="baseline"
                            style={{ height: `${[68.1, 58.9, 41.6][i]}%` }}
                          >
                            <b>{[68.1, 58.9, 41.6][i]}%</b>
                          </div>
                        )}
                      </div>
                      <span>{d}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>评测指标</th>
                      <th>实测值（示例）</th>
                      <th>JSON基准</th>
                      <th>差异</th>
                    </tr>
                  </thead>
                  <tbody>
                    {datasets.map((d, i) => (
                      <tr key={d}>
                        <td>
                          <b>{d}</b>
                        </td>
                        <td>
                          <b>{[72.4, 61.8, 48][i]}%</b>
                        </td>
                        <td>{[68.1, 58.9, 41.6][i]}%</td>
                        <td className="green-text">
                          +{[4.3, 2.9, 6.4][i]} pct
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted chart-note">
                基准版本：baseline-demo-v1 / 仅示例　 |　 单位：准确率 /
                任务成功率（%）
              </p>
            </>
          ) : tab === "性能结果" ? (
            <>
              <Notice>
                以下为界面展示数据，不代表目标数据集已支持这些性能指标。
              </Notice>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>指标</th>
                      <th>示例值</th>
                      <th>口径</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["输出吞吐", "126 tok/s", "总输出 Token / 执行耗时"],
                      ["首 Token 延迟", "182 ms", "P50 · 示例"],
                      ["端到端延迟", "1,240 ms", "P50 · 示例"],
                    ].map((row) => (
                      <tr key={row[0]}>
                        {row.map((c) => (
                          <td key={c}>{c}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">
                并发 60 / 输入 2048 / 输出 2048，仅为示例条件。
              </p>
            </>
          ) : (
            <>
              <Notice>公开任务集结果，不等同于官方私有榜单。</Notice>
              <div className="agent-result">
                <strong>48.0%</strong>
                <p>严格任务成功率 · 示例</p>
                <Badge tone="orange">失败案例：工具调用参数缺失</Badge>
              </div>
              <button
                className="link"
                onClick={() =>
                  notify(
                    "样本 #018：create_task 缺少 title 字段，断言未通过。静态示例。",
                  )
                }
              >
                查看失败样本 #018
              </button>
            </>
          )}
        </Card>
        <Card
          title={
            <div className="spread">
              <span className="inline">
                <Sparkles size={24} />
                AutoEval Agent 自动分析
              </span>
              <Badge
                tone={
                  r.status === "分析成功"
                    ? "green"
                    : r.status === "分析失败"
                      ? "orange"
                      : "purple"
                }
              >
                {r.status}
              </Badge>
            </div>
          }
          className="analysis"
        >
          <p className="muted">覆盖情况：3/3　 |　 分析耗时：2分18秒（示例）</p>
          {r.status !== "分析成功" ? (
            <div className="stack">
              <Notice>
                {r.status === "分析中"
                  ? "分析中，原始测评结果可正常查看。"
                  : "分析失败：分析服务请求超时（示例）。原始报告已保留。"}
              </Notice>
              {r.status === "分析失败" && (
                <button
                  onClick={() =>
                    notify("静态预览：未调用分析服务，不会触发真实重试。")
                  }
                >
                  重试分析
                </button>
              )}
            </div>
          ) : (
            [
              [
                "主要差距集中于多模态推理。",
                "MMMU-Pro 相比基准提升有限（+2.9 pct），复杂图文理解与推理仍有提升空间。",
              ],
              [
                "工具调用任务存在参数错误。",
                "部分任务因工具调用参数格式或字段值不符合要求而未通过断言。",
              ],
              [
                "建议检查失败样本与生成配置。",
                "优先分析 MMMU-Pro 与 Agent 的失败样本，并检查温度、最大输出长度与工具参数模板。",
              ],
            ].map((a, i) => (
              <article key={a[0]}>
                <span className="analysis-number">{i + 1}</span>
                <div>
                  <h3>{a[0]}</h3>
                  <p>{a[1]}</p>
                  <span className="muted">证据：</span>
                  <button
                    onClick={() =>
                      notify(
                        "样本 #018：工具调用缺少必填参数。此内容为静态示例。",
                      )
                    }
                  >
                    <FileText size={14} />
                    样本#018
                  </button>
                  <button
                    onClick={() =>
                      notify(
                        "轨迹 #042：输入 → 工具调用 → 参数校验失败。静态示例。",
                      )
                    }
                  >
                    <Activity size={14} />
                    轨迹#042
                  </button>
                </div>
              </article>
            ))
          )}
          <div className="card-bottom">
            <small>上述分析及证据均为静态示例。</small>
          </div>
        </Card>
      </div>
    </div>
  );
}
function Leaderboard({ go }: { go: (p: string, id?: string) => void }) {
  const [tab, setTab] = useState("精度榜单");
  const [dataset, setDataset] = useState("MMMU-Pro");
  const [metric, setMetric] = useState("accuracy");
  const [config, setConfig] = useState("v1.3");
  const [scope, setScope] = useState("相同子集");
  const vals =
    tab === "精度榜单"
      ? [68.2, 65.4, 61.8, 60.9, 58.7, 56.1]
      : metric === "延迟（ms）"
        ? [182, 204, 220, 256, 280, 310]
        : [158, 145, 126, 118, 105, 98];
  return (
    <div className="stack">
      <Tabs
        items={["精度榜单", "性能榜单"]}
        value={tab}
        onChange={(t) => {
          setTab(t);
          setMetric(t === "精度榜单" ? "accuracy" : "吞吐（tok/s）");
        }}
      />
      <Card>
        <div className="filters">
          <Select
            label="数据集"
            options={datasets}
            value={dataset}
            onChange={setDataset}
          />
          <Select
            label="指标"
            options={
              tab === "精度榜单"
                ? ["accuracy"]
                : ["吞吐（tok/s）", "延迟（ms）"]
            }
            value={metric}
            onChange={setMetric}
          />
          <Select
            label="配置版本"
            options={["v1.3", "v1.2"]}
            value={config}
            onChange={setConfig}
          />
          <Select
            label="样本范围"
            options={["相同子集", "完整覆盖"]}
            value={scope}
            onChange={setScope}
          />
        </div>
      </Card>
      <Notice>
        仅展示同数据集、同配置口径的有效结果。当前所有排名均为示例。
      </Notice>
      <Card className="table-card">
        <div className="table-wrap">
          <table className="leader-table">
            <thead>
              <tr>
                {[
                  "排名",
                  "模型",
                  "出口版本",
                  tab === "精度榜单" ? "精度" : "性能指标",
                  "基准差异",
                  "测评时间",
                  "报告",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {vals.map((v, i) => (
                <tr key={i}>
                  <td>
                    <span className={`rank rank-${i}`}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                  </td>
                  <td>
                    <b>Demo Vision {String.fromCharCode(65 + i)}</b>
                  </td>
                  <td>
                    Release <small>v2.{6 - i}.0</small>
                  </td>
                  <td>
                    <div className="inline score">
                      <b>
                        {v}
                        {tab === "精度榜单"
                          ? "%"
                          : metric === "延迟（ms）"
                            ? " ms"
                            : " tok/s"}
                      </b>
                      <progress
                        max={
                          tab === "精度榜单"
                            ? 100
                            : metric === "延迟（ms）"
                              ? 400
                              : 200
                        }
                        value={v}
                      />
                    </div>
                  </td>
                  <td className={i < 2 ? "green-text" : ""}>
                    {["+3.1", "+0.3", "-3.3", "-4.2", "-6.4", "-9.0"][i]}
                    {tab === "精度榜单" ? "pp" : "%"}
                  </td>
                  <td>2026-11-09 10:{24 + i * 3}</td>
                  <td>
                    <button
                      className="outline"
                      onClick={() => go("detail", `RPT-0${25 - i}`)}
                    >
                      查看报告
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="task-columns">
        <Card
          title={
            <span className="inline">
              <Layers size={22} />
              对比条件
            </span>
          }
        >
          <p>数据集：{dataset}</p>
          <p>配置：{config}</p>
          <p>覆盖范围：{scope}（示例）</p>
        </Card>
        <Card
          title={
            <span className="inline">
              <Info size={22} />
              指标说明
            </span>
          }
        >
          <p>accuracy：准确率，表示模型在评测样本上的正确率，越高越好。</p>
          <p>性能榜单：吞吐越高越好；延迟越低越好。按可比测试条件分别排名。</p>
        </Card>
      </div>
    </div>
  );
}

function Overview({ go }: { go: (p: string, id?: string) => void }) {
  return (
    <div className="stack overview">
      <section className="overview-hero">
        <div>
          <span className="overview-eyebrow">AUTOMATED EVALUATION</span>
          <h2>从模型接入，到洞察每一次表现。</h2>
          <p>
            统一管理模型测评、追踪执行过程，
            <br />
            在同一工作空间查看结果、分析差距与比较表现。
          </p>
          <div className="inline">
            <button className="primary" onClick={() => go("console")}>
              <Play size={17} />
              开始测评
            </button>
            <button onClick={() => go("reports")}>
              浏览测评报告
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
        <div className="hero-workflow">
          <span className="muted">测评工作流</span>
          {[
            {
              icon: SlidersHorizontal,
              name: "接入与配置",
              sub: "选择模型 · 独立数据集参数",
            },
            {
              icon: Activity,
              name: "执行与追踪",
              sub: "任务进度 · 日志与关键轨迹",
            },
            {
              icon: Sparkles,
              name: "结果与洞察",
              sub: "测评报告 · 基准对比 · 自动分析",
            },
          ].map((s, i) => (
            <div className="workflow-step" key={s.name}>
              <s.icon size={21} />
              <div>
                <b>{s.name}</b>
                <small>{s.sub}</small>
              </div>
              <span className="muted">0{i + 1}</span>
            </div>
          ))}
        </div>
      </section>
      <div className="spread">
        <h3>工作空间概览</h3>
        <Badge>静态示例</Badge>
      </div>
      <div className="stats">
        {[
          { name: "接入模型", value: "2", icon: Layers },
          { name: "测评任务", value: "24", icon: ClipboardList },
          { name: "执行中", value: "2", icon: Activity },
          { name: "测评报告", value: String(reports.length), icon: FileText },
        ].map((s) => (
          <Card key={s.name}>
            <div className="stat-icon">
              <s.icon />
            </div>
            <div>
              <span className="muted">{s.name}</span>
              <strong>{s.value}</strong>
            </div>
          </Card>
        ))}
      </div>
      <div className="overview-lower">
        <Card
          title={
            <div className="spread">
              <span>最近报告</span>
              <button className="link" onClick={() => go("reports")}>
                查看全部
                <ChevronRight size={14} />
              </button>
            </div>
          }
        >
          {reports.slice(0, 3).map((r) => (
            <button
              className="recent-report"
              key={r.id}
              onClick={() => go("detail", r.id)}
            >
              <div className="report-file">
                <FileText size={22} />
              </div>
              <div>
                <b>{r.model}</b>
                <small>
                  {r.id} · {r.version} · {r.date}
                </small>
              </div>
              <Badge
                tone={
                  r.status === "分析成功"
                    ? "green"
                    : r.status === "分析失败"
                      ? "orange"
                      : "purple"
                }
              >
                {r.status}
              </Badge>
              <ChevronRight size={16} />
            </button>
          ))}
        </Card>
        <Card title="快速入口">
          <div className="quick-grid">
            {menus
              .filter((m) => ["config", "tasks", "leaderboard"].includes(m.id))
              .map((m) => (
                <button key={m.id} onClick={() => go(m.id)}>
                  <m.icon size={22} />
                  <div>
                    <b>{m.label}</b>
                    <small>
                      {m.id === "config"
                        ? "维护独立测评参数"
                        : m.id === "tasks"
                          ? "追踪任务与执行轨迹"
                          : "按可比条件查看排名"}
                    </small>
                  </div>
                  <ChevronRight size={15} />
                </button>
              ))}
          </div>
        </Card>
      </div>
      <Notice>
        当前为前端静态预览。配置、任务、报告与分析均为示例，不会调用模型或执行真实测评。
      </Notice>
    </div>
  );
}
