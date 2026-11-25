import { version } from "../../package.json";
import { apiGetPage } from "../shared/api";
import { BackendConnection } from "../shared/ui/BackendConnection";
import { ManagementDrawer } from "../shared/ui/ManagementDrawer";
import { DataWorkbench, PublishedLeaderboard } from "../features/reporting/DataWorkbench";
import { DatasetManifests } from "../features/catalog/DatasetManifests";
import { ExecutionBindings } from "../features/catalog/ExecutionBindings";
import { StandardInputs } from "../features/catalog/StandardInputs";
import { Configurations } from "../features/catalog/Configurations";
import { useProfiles } from "../features/catalog/useProfiles";
import { SSHResources } from "../features/resources/SSHResources";
import { TaskPlanning } from "../features/planning/TaskPlanning";
import { EvaluationRuns } from "../features/evaluation/EvaluationRuns";
import { RealReports } from "../features/reporting/RealReports";
import { RealLeaderboard } from "../features/reporting/RealLeaderboard";
import { useEffect, useState } from "react";
import {
  Activity,
  AlertCircle,
  ChartNoAxesColumnIncreasing,
  ChevronRight,
  ClipboardList,
  FileText,
  GraduationCap,
  Home,
  Info,
  PanelsTopLeft,
  Play,
  SlidersHorizontal,
  Database,
  Settings2,
  ShieldAlert,
  Sparkles,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import { Card } from "../shared/ui/Card";
import { Badge } from "../shared/ui/Badge";
import { Note } from "../shared/ui/Note";
import { LoginPage } from "../features/identity/LoginPage";
import { UserArea } from "../features/identity/UserArea";
import { AdminUsers } from "../features/admin/AdminUsers";
import { AdminConfig } from "../features/admin/AdminConfig";
import { useCurrentUser, useGateProviders } from "../features/identity/useCurrentUser";
import "../styles/index.css";

const menus = [
  { id: "home", label: "首页", icon: Home },
  { id: "console", label: "控制台", icon: PanelsTopLeft },
  { id: "config", label: "测评配置", icon: SlidersHorizontal },
  { id: "tasks", label: "任务管理", icon: ClipboardList },
  { id: "reports", label: "报告管理", icon: ChartNoAxesColumnIncreasing },
  { id: "leaderboard", label: "测评榜单", icon: Trophy },
  { id: "data-workbench", label: "数据工作台", icon: Database },
];

// 管理员专属导航：仅角色为 admin 的登录用户可见（受后端 require_admin 双重校验）
const adminMenus = [
  { id: "admin/users", label: "用户管理", icon: Users },
  { id: "admin/config", label: "平台配置", icon: Settings2 },
];
const allMenus = [...menus, ...adminMenus];

export function App() {
  const [page, setPage] = useState(location.hash.slice(1) || "console");
  const [profiles, setProfiles] = useProfiles(page === "config" || page.startsWith("config/"));
  const [workbenchEnabled, setWorkbenchEnabled] = useState(false);
  const [candidateScoresOpen, setCandidateScoresOpen] = useState(false);
  useEffect(() => { if (page !== "leaderboard") setCandidateScoresOpen(false); }, [page]);
  const [poolReturn, setPoolReturn] = useState(false);
  const [poolRevision, setPoolRevision] = useState(0);
  const poolPage = page === "config/ssh-pool" || page === "config/ssh-pool/add";
  const [toast, setToast] = useState("");
  const { auth, refresh, reLoginNotice } = useCurrentUser();
  const loginPage = page === "login" || page.startsWith("login?");
  const loginError = page.startsWith("login?") ? new URLSearchParams(page.slice(6)).get("error") : null;
  const { providers, reload: reloadProviders } = useGateProviders(auth.status === "guest");
  const localMode = auth.status === "signed-in" && auth.user.provider === "local";
  const retryAuth = () => {
    refresh();
    reloadProviders();
  };
  useEffect(() => { if (page !== "leaderboard") setCandidateScoresOpen(false); }, [page]);
  const evaluationPage = page === "tasks" || page.startsWith("run/") || page.startsWith("evaluate?");
  const go = (path: string) => {
    location.hash = path;
    setPage(path);
    window.scrollTo(0, 0);
  };

  useEffect(() => {
    const onHashChange = () => {
      const hash = location.hash.slice(1) || "console";
      if (hash.startsWith("planned-run/")) { location.replace(`#run/${hash.slice(12)}`); return; }
      if (hash.startsWith("evaluate?")) { location.replace("#console"); return; }
      setPage(hash);
    };
    onHashChange();
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  const title = poolPage ? (page.endsWith("/add") ? "添加 SSH 节点" : "SSH 资源池") : page.startsWith("run/") || page.startsWith("planned-run/")
    ? "测评任务详情"
    : page.startsWith("evaluate?")
      ? "新建探索测评"
      : page.startsWith("report/")
          ? "测评报告"
          : page.startsWith("config/")
            ? "配置维护"
            : allMenus.find((menu) => menu.id === page)?.label || "控制台";
  const descriptions: Record<string, string> = {
    home: "从一次测评开始，让模型能力与执行证据清晰可见。",
    console: "选择模型、数据集与执行资源，按当前参数发起测评；可选获取耗时估算和参数建议。",
    "config/ssh-pool": "维护测评使用的 SSH 节点，检查节点连接。",
    "config/ssh-pool/add": "登记节点连接信息与凭据。",
    config: "按模型与数据集分别维护测试参数、清单和执行绑定。",
    tasks: "追踪每一次测评，定位每一个问题。",
    reports: "查看测评报告，追溯历史结果。",
    leaderboard: "按来源与比较条件查看模型成绩。",
    "data-workbench": "管理员评审报告成绩、维护榜单数据及导入官方来源；普通用户只读公布榜单。",
    "admin/users": "查看平台账号、调整角色、停用与恢复账号；所有变更写入审计记录。",
    "admin/config": "维护预算开关、归档清单与 Langfuse 链接等平台级配置，保存后立即生效。",
  };

  if (auth.status === "loading") {
    return <div className="login-shell"><p className="login-loading" role="status">正在校验登录状态…</p></div>;
  }
  if (loginPage) {
    return (
      <div className="login-shell">
        <LoginPage error={loginError} onEnter={() => go("console")} localMode={localMode} providers={providers} onRetry={retryAuth} />
      </div>
    );
  }
  if (auth.status === "error") {
    // 后端确认身份失败（网络/5xx）：不能确认身份就不放行，提供重试而不是放游客进入。
    return (
      <div className="login-shell">
        <div className="login-page">
          <div className="login-card" role="alert">
            <img className="login-logo" src="/brand/autoeval-logo.svg" alt="AutoEval" />
            <h1>无法确认登录状态</h1>
            <div className="login-error">
              <AlertCircle size={16} />
              后端连接异常或服务不可用，无法校验身份，请检查后端服务后重试。
            </div>
            <button className="login-retry" type="button" onClick={refresh}>
              重试
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (auth.status === "guest") {
    // 访客（oauth 模式未登录）一律进入登录页；登录方式读取失败或为空时，
    // 登录页呈现对应错误与重试，后端确认身份之前不放行进入控制台。
    // 仅当后端确认"会话已失效"才提示重新登录，首次访问只显示登录入口。
    return (
      <div className="login-shell">
        <LoginPage error={null} onEnter={() => go("console")} localMode={false} providers={providers} onRetry={retryAuth} notice={reLoginNotice} />
      </div>
    );
  }
  const user = auth.status === "signed-in" ? auth.user : undefined;
  // 管理员及以上（admin / superadmin）可见管理入口；具体操作权力由后端按角色裁决
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo" src="/brand/autoeval-logo.svg" alt="AutoEval" />
        </div>
        <div className="workspace">工作空间：本地单工作空间</div>
        <nav>
          {(isAdmin ? allMenus : menus).filter(menu => menu.id !== "data-workbench" || (workbenchEnabled && isAdmin)).map((menu) => (
            <a
              key={menu.id}
              href={`#${menu.id}`}
              className={
                page === menu.id ||
                ((evaluationPage || page.startsWith("planned-run/")) && menu.id === "tasks") ||
                (page.startsWith("report/") && menu.id === "reports") ||
                (page.startsWith("config/") && menu.id === "config")
                  ? "selected"
                  : ""
              }
            >
              <menu.icon size={22} />
              {menu.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="dot" /> AutoEval <small>v{version}</small>
        </div>
      </aside>
      <main className="main">
        <BackendConnection onWorkbenchEnabled={setWorkbenchEnabled} />
        <div className="breadcrumb">
          {page.startsWith("report/") ? (
            <button onClick={() => go("reports")}>报告管理</button>
          ) : page.startsWith("run/") ? (
            <button onClick={() => go("tasks")}>任务管理</button>
          ) : (
            <span>AutoEval</span>
          )}
          <ChevronRight size={14} />
          <span>{title}</span>
          <Badge>单工作空间</Badge>
          {user && (
            <>
              <span className="breadcrumb-spacer" />
              <UserArea user={user} onLoggedOut={refresh} notify={setToast} />
            </>
          )}
        </div>
        <header className="page-heading">
          <div>
            <h1>{title}</h1>
            <p>{descriptions[page] || descriptions[page.split("/")[0]] || "查看执行概况、测评结果与历史证据。"}</p>
          </div>
        </header>

        {page === "home" && <Overview go={go} />}
        {(page === "console" || (poolPage && poolReturn)) && <div hidden={page !== "console"}>
          <TaskPlanning poolRevision={poolRevision} onManagePool={(add) => {
            setPoolReturn(true);
            go(add ? "config/ssh-pool/add" : "config/ssh-pool");
          }} />
        </div>}
        {poolPage && <SSHResources
          adding={page.endsWith("/add")}
          onAdd={() => go("config/ssh-pool/add")}
          onCancel={() => go("config/ssh-pool")}
          onSaved={() => { setPoolRevision(value => value + 1); go(poolReturn ? "console" : "config/ssh-pool"); }}
          onBack={poolReturn ? () => go("console") : undefined}
        />}
        {page === "config" && <div className="management-toolbar">
          <button onClick={() => { setPoolReturn(false); go("config/ssh-pool"); }}>SSH 资源池</button>
          <ManagementDrawer title="管理样本清单"><DatasetManifests /></ManagementDrawer>
          <ManagementDrawer title="执行规则与绑定"><ExecutionBindings /></ManagementDrawer>
          {import.meta.env.DEV && <ManagementDrawer title="标准仓输入与版本"><StandardInputs /></ManagementDrawer>}
        </div>}
        {(page === "config" || (page.startsWith("config/") && !poolPage)) && (
          <Configurations profiles={profiles} setProfiles={setProfiles} go={go} notify={setToast} />
        )}
        {evaluationPage && (
          <div className="stack evaluation-tasks">
            <EvaluationRuns
              runId={page.startsWith("run/") ? page.slice(4) : undefined}
              initialTarget={
                page.startsWith("evaluate?")
                  ? new URLSearchParams(page.slice(9)).get("target") || ""
                  : ""
              }
              allowSubmit={false}
            />

          </div>
        )}
        {(page === "reports" || page.startsWith("report/")) && (
          <RealReports
            reportId={page.startsWith("report/") ? page.slice(7) : undefined}
            open={(id) => go(`report/${id}`)}
          />
        )}

        {page === "leaderboard" && (<div className="stack"><PublishedLeaderboard /><details onToggle={(event) => setCandidateScoresOpen(event.currentTarget.open)}><summary>平台运行报告候选成绩（未人工评审）</summary>{candidateScoresOpen && <RealLeaderboard open={(id) => go(`report/${id}`)} />}</details></div>)}
        {workbenchEnabled && page === "data-workbench" && isAdmin && <DataWorkbench />}
        {(page.startsWith("admin/") || page === "data-workbench") && user && !isAdmin && (
          <section className="card admin-forbidden" role="alert">
            <div className="admin-forbidden-head">
              <ShieldAlert size={22} />
              <h2>403 · 无权访问</h2>
            </div>
            <p>该页面的评审与维护操作仅管理员可执行。普通用户可使用测评、任务与报告功能，并只读查看榜单；如需权限，请联系管理员调整你的角色。</p>
            <button className="primary" type="button" onClick={() => go("console")}>返回控制台</button>
          </section>
        )}
        {page === "admin/users" && isAdmin && user && <AdminUsers notify={setToast} viewer={user} />}
        {page === "admin/config" && isAdmin && <AdminConfig notify={setToast} />}

        <footer className="page-foot">
          AutoEval · 智能测评平台
          <span>页面数据来自当前后端；未启用能力与缺失指标以页面说明为准</span>
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

type RecentReport = {
  id: string;
  remote_model: string;
  validity: string;
  created_at: string;
  analysis_status: string;
};

function Overview({ go }: { go: (path: string) => void }) {
  const [reports, setReports] = useState<RecentReport[]>([]);
  const [message, setMessage] = useState("正在读取最近报告…");
  useEffect(() => {
    const controller = new AbortController();
    apiGetPage<RecentReport[]>("/reports?summary_only=true&limit=3&offset=0", controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setReports(page.data);
        setMessage(page.data.length ? "" : "暂无已归档报告。");
      })
      .catch(() => {
        if (!controller.signal.aborted) setMessage("最近报告读取失败，请前往报告管理重试。");
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="stack overview">
      <section className="overview-hero">
        <div>
          <span className="overview-eyebrow">AUTOEVAL · GPQA LITE</span>
          <h2>聚焦真实精度测评，贯通执行与证据。</h2>
          <p>
            从已保存的模型服务与配置开始，
            <br />
            追踪任务状态、case 证据、归档报告与独立分析。
          </p>
          <div className="inline">
            <button className="primary" onClick={() => go("console")}>
              <Play size={17} />发起测评
            </button>
            <button onClick={() => go("reports")}>
              查看测评报告<ChevronRight size={16} />
            </button>
          </div>
        </div>
        <div className="hero-workflow">
          <span className="muted">真实测评流程</span>
          {[
            { icon: SlidersHorizontal, name: "接入与配置", sub: "已保存服务 · 冻结配置与清单" },
            { icon: Activity, name: "执行与追踪", sub: "运行状态 · case 执行证据" },
            { icon: Sparkles, name: "结果与洞察", sub: "归档报告 · 基准对比 · 独立分析" },
          ].map((step, index) => (
            <div className="workflow-step" key={step.name}>
              <step.icon size={21} />
              <div>
                <b>{step.name}</b>
                <small>{step.sub}</small>
              </div>
              <span className="muted">0{index + 1}</span>
            </div>
          ))}
        </div>
      </section>
      <div className="spread">
        <h3>当前执行范围</h3>
        <Badge>GPQA Lite · 探索测评</Badge>
      </div>
      <div className="stats">
        {[
          { name: "精度测评", value: "GPQA Lite", icon: GraduationCap },
          { name: "任务追踪", value: "状态与证据", icon: ClipboardList },
          { name: "报告查看", value: "归档与分析", icon: FileText },
          { name: "性能测评", value: "尚未接入", icon: Zap },
        ].map((item) => (
          <Card key={item.name}>
            <div className="stat-icon"><item.icon /></div>
            <div>
              <span className="muted">{item.name}</span>
              <strong>{item.value}</strong>
            </div>
          </Card>
        ))}
      </div>
      <div className="overview-scope">
        <Card title={<span className="inline"><GraduationCap size={21} />已开放的探索链路</span>}>
          <Badge>配置 → 任务 → 报告</Badge>
          <p>当前支持 GPQA 单数据集 Lite、串行、最多 5 个模型请求。每次运行冻结配置、清单与执行参数，探索结果不作为正式 Release 结论。</p>
        </Card>
        <Card title={<span className="inline"><Zap size={21} />尚未开放的能力</span>}>
          <Badge tone="neutral">明确保留未启用状态</Badge>
          <p>MMMU-Pro、AutomationBench、正式 Release 和性能测评尚未形成后端执行闭环，页面不提供示例成绩或虚构排名。</p>
        </Card>
      </div>
      <div className="overview-lower">
        <Card
          title={
            <div className="spread">
              <span>最近测评报告</span>
              <button className="link" onClick={() => go("reports")}>查看全部<ChevronRight size={14} /></button>
            </div>
          }
        >
          <div data-testid="recent-reports">
            {reports.map((report) => (
              <button className="recent-report" key={report.id} onClick={() => go(`report/${report.id}`)}>
                <div className="report-file"><FileText size={22} /></div>
                <div>
                  <b>{report.remote_model}</b>
                  <small>GPQA Lite · {report.validity} · {new Date(report.created_at).toLocaleString("zh-CN")}</small>
                </div>
                <Badge tone={report.analysis_status === "succeeded" ? "green" : report.analysis_status === "failed" ? "orange" : "purple"}>
                  {report.analysis_status}
                </Badge>
                <ChevronRight size={16} />
              </button>
            ))}
            {message && <p role="status" className="empty">{message}</p>}
          </div>
        </Card>
        <Card title="快速入口">
          <div className="quick-grid">
            {menus.filter((menu) => ["config", "tasks", "leaderboard"].includes(menu.id)).map((menu) => (
              <button key={menu.id} onClick={() => go(menu.id)}>
                <menu.icon size={22} />
                <div>
                  <b>{menu.label}</b>
                  <small>{menu.id === "config" ? "维护独立测评参数" : menu.id === "tasks" ? "追踪任务与执行证据" : "按可比条件查看排名"}</small>
                </div>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
        </Card>
      </div>
      <Note><Info size={17} />探索报告不代表全量成绩；只有真实且完整的报告才进入内部可比榜单。未采集的指标保持为空，不使用静态示例补齐。</Note>
    </div>
  );
}
