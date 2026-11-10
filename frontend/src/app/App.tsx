import { ReportView, reportDatasets } from "./ReportView";
import { BackendConnection } from "../components/BackendConnection";
import { DatasetManifests } from "../components/DatasetManifests";
import { ExecutionBindings } from "../components/ExecutionBindings";
import {
  Configurations,
  EvaluationConsole,
  DatasetExecution,
  useProfiles,
} from "./Workflow";
import { useState, useEffect } from "react";
import {
  Home,
  GraduationCap,
  Zap,
  SlidersHorizontal,
  ClipboardList,
  ChartNoAxesColumnIncreasing,
  Trophy,
  Info,
  CheckCircle2,
  Play,
  Search,
  Layers,
  Activity,
  ExternalLink,
  Sparkles,
  FileText,
  ChevronRight,
  CircleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import "./app.css";
const datasets = ["GPQA", "MMMU-Pro", "AutomationBench"];
const menus = [
  { id: "home", label: "首页", icon: Layers },
  { id: "console", label: "控制台", icon: Home },
  { id: "config", label: "测评配置", icon: SlidersHorizontal },
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
  const [profiles, setProfiles] = useProfiles();
  const [page, setPage] = useState(location.hash.slice(1) || "console");
  const [reportId, setReportId] = useState("RPT-023");
  const [toast, setToast] = useState("");
  const go = (p: string, id?: string) => {
    if (id) setReportId(id);
    location.hash = p;
    setPage(p);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    const fn = () => setPage(location.hash.slice(1) || "console");
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
      : page.startsWith("config/")
        ? "配置维护"
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
                (page === "detail" && m.id === "reports") ||
                (page.startsWith("config/") && m.id === "config")
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
        <BackendConnection />
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
        {page === "console" && (
          <EvaluationConsole
            profiles={profiles}
            setProfiles={setProfiles}
            notify={setToast}
          />
        )}
        {page === "config" && <DatasetManifests />}
        {page === "config" && <ExecutionBindings />}
        {page === "config" && (
          <Configurations
            profiles={profiles}
            setProfiles={setProfiles}
            go={go}
            notify={setToast}
          />
        )}
        {page.startsWith("config/") && (
          <Configurations
            profiles={profiles}
            setProfiles={setProfiles}
            go={go}
            notify={setToast}
          />
        )}
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
  const [owner, setOwner] = useState("仅看我");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("全部状态");
  const [model, setModel] = useState("全部模型");
  const [version, setVersion] = useState("全部版本");
  const filtered = taskRows.filter(
    (r) =>
      (owner === "仅看我"
        ? Number(r.name.slice(-3)) % 2 === 1
        : Number(r.name.slice(-3)) % 2 === 0) &&
      r.name.toLowerCase().includes(search.toLowerCase()) &&
      (status === "全部状态" || r.state === status) &&
      (model === "全部模型" || r.model === model) &&
      (version === "全部版本" || r.version === version),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const activePage = Math.min(currentPage, pageCount);
  useEffect(() => setCurrentPage(1), [search, status, model, version, owner]);
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
          label="人员"
          options={["仅看我", "其他人员"]}
          value={owner}
          onChange={setOwner}
        />
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
          label="出口版本"
          options={["全部版本", "RC", "Release"]}
          value={version}
          onChange={setVersion}
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
                      <DatasetSummary items={r.datasets} />
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
  const row = taskRows.find((r) => r.name === task);
  if (!row)
    return (
      <Card>
        <p>未找到任务</p>
        <button onClick={() => go("tasks")}>返回任务列表</button>
      </Card>
    );
  return (
    <div className="stack">
      <button className="link back" onClick={() => go("tasks")}>
        返回任务列表
      </button>
      <DatasetExecution
        task={task}
        model={row.model}
        version={row.version}
        state={row.state}
        items={row.datasets}
      />
      <button className="link" onClick={() => go("detail", "RPT-023")}>
        查看关联报告
      </button>
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
            options={["全部数据集", ...reportDatasets.map((d) => d.name)]}
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
                      <DatasetSummary
                        items={reportDatasets.map((d) => d.name)}
                        preferred={dataset}
                      />
                      <small>完整 6 / 部分 1 / 失败 1 · 示例</small>
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
  const report = reports.find((r) => r.id === id) || reports[3];
  return (
    <ReportView
      key={id}
      id={id}
      model={report.model}
      modelId={report.modelId}
      version={report.version}
      analysis={report.status}
      go={go}
      notify={notify}
    />
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
        仅展示同数据集、同配置口径的有效结果。榜单应来自受审批任务；审批人、准入条件及驳回流程待确认，当前排名仅为示例。
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
          <span className="overview-eyebrow">AUTOEVAL · DEMO</span>
          <h2>聚焦精度测评，体验完整流程。</h2>
          <p>
            AutoEval 演示 Demo，当前聚焦精度测评流程，
            <br />
            从配置、执行追踪到报告查看；性能测评仅作界面示意。
          </p>
          <div className="inline">
            <button className="primary" onClick={() => go("console")}>
              <Play size={17} />
              体验精度测评
            </button>
            <button onClick={() => go("reports")}>
              查看示例报告
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
        <div className="hero-workflow">
          <span className="muted">精度测评演示流程</span>
          {[
            {
              icon: SlidersHorizontal,
              name: "接入与配置",
              sub: "选择模型 · 独立数据集参数",
            },
            {
              icon: Activity,
              name: "执行与追踪",
              sub: "任务进度 · 数据集 case 日志",
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
        <h3>本期演示范围</h3>
        <Badge>精度流程演示 · 性能仅示意</Badge>
      </div>
      <div className="stats">
        {[
          { name: "精度测评", value: "流程演示", icon: GraduationCap },
          { name: "任务追踪", value: "流程演示", icon: ClipboardList },
          { name: "报告查看", value: "示例展示", icon: FileText },
          { name: "性能测评", value: "仅作示意", icon: Zap },
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
      <div className="overview-scope">
        <Card
          title={
            <span className="inline">
              <GraduationCap size={21} />
              精度测评 · 本期演示重点
            </span>
          }
        >
          <Badge>配置 → 任务 → 报告</Badge>
          <p>
            围绕 GPQA、MMMU-Pro 与
            AutomationBench，演示数据集配置、任务追踪和结果查看流程。页面数值为示例。
          </p>
        </Card>
        <Card
          title={
            <span className="inline">
              <Zap size={21} />
              性能测评 · 仅作示意
            </span>
          }
        >
          <Badge tone="neutral">尚未接入性能执行</Badge>
          <p>
            吞吐量、延迟、性能图表和榜单仅用于展示界面设计，不提供真实性能测试，不作为模型性能结论。
          </p>
        </Card>
      </div>
      <div className="overview-lower">
        <Card
          title={
            <div className="spread">
              <span>示例测评报告</span>
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
        演示说明：本期仅围绕精度测评打通演示流程。性能测评尚未接入，吞吐、延迟及性能排名仅为示意，不代表实测能力；当前前端预览中的任务与报告均为示例数据。
      </Notice>
    </div>
  );
}
