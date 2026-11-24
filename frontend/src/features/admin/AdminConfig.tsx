import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { apiGet, apiPut, ApiError } from "../../shared/api";
import { Card } from "../../shared/ui/Card";
import { Note } from "../../shared/ui/Note";
import { Info } from "lucide-react";

export type AdminConfigView = {
  enforce_task_budget: boolean;
  evaluation_follow_up_enabled: boolean;
  archived_manifest_ids: string[];
  archived_compilation_ids: string[];
  langfuse_browser_url: string | null;
  langfuse_host: string | null;
  langfuse_project_id: string | null;
  billing_execution_config: string | null;
};

function splitIds(text: string): string[] {
  return text.split(/[\s,]+/).filter(Boolean);
}

export function AdminConfig({ notify }: { notify: (message: string) => void }) {
  const [view, setView] = useState<AdminConfigView | null>(null);
  const [message, setMessage] = useState("正在读取平台配置…");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    enforce_task_budget: false,
    evaluation_follow_up_enabled: false,
    archived_manifest_ids: "",
    archived_compilation_ids: "",
    langfuse_browser_url: "",
    langfuse_host: "",
    langfuse_project_id: "",
  });

  useEffect(() => {
    const controller = new AbortController();
    apiGet<AdminConfigView>("/admin/config", controller.signal)
      .then((config) => {
        if (controller.signal.aborted) return;
        setView(config);
        setForm({
          enforce_task_budget: config.enforce_task_budget,
          evaluation_follow_up_enabled: config.evaluation_follow_up_enabled,
          archived_manifest_ids: config.archived_manifest_ids.join("\n"),
          archived_compilation_ids: config.archived_compilation_ids.join("\n"),
          langfuse_browser_url: config.langfuse_browser_url ?? "",
          langfuse_host: config.langfuse_host ?? "",
          langfuse_project_id: config.langfuse_project_id ?? "",
        });
        setMessage("");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(error instanceof ApiError ? `平台配置读取失败：${error.message}` : "平台配置读取失败，仅管理员可访问。");
        }
      });
    return () => controller.abort();
  }, []);

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const saved = await apiPut<AdminConfigView>("/admin/config", {
        updates: {
          enforce_task_budget: form.enforce_task_budget,
          evaluation_follow_up_enabled: form.evaluation_follow_up_enabled,
          archived_manifest_ids: splitIds(form.archived_manifest_ids),
          archived_compilation_ids: splitIds(form.archived_compilation_ids),
          langfuse_browser_url: form.langfuse_browser_url.trim() || null,
          langfuse_host: form.langfuse_host.trim() || null,
          langfuse_project_id: form.langfuse_project_id.trim() || null,
        },
      });
      setView(saved);
      setForm({
        enforce_task_budget: saved.enforce_task_budget,
        evaluation_follow_up_enabled: saved.evaluation_follow_up_enabled,
        archived_manifest_ids: saved.archived_manifest_ids.join("\n"),
        archived_compilation_ids: saved.archived_compilation_ids.join("\n"),
        langfuse_browser_url: saved.langfuse_browser_url ?? "",
        langfuse_host: saved.langfuse_host ?? "",
        langfuse_project_id: saved.langfuse_project_id ?? "",
      });
      notify("平台配置已保存，立即生效。");
    } catch (error: unknown) {
      notify(error instanceof ApiError ? `保存失败：${error.message}` : "保存失败，请重试。");
    } finally {
      setSaving(false);
    }
  };

  const set = (patch: Partial<typeof form>) => setForm((value) => ({ ...value, ...patch }));

  return (
    <div className="stack admin-config">
      {message && <p role="status" className="empty">{message}</p>}
      {view && (
        <>
          <Card title="功能开关">
            <label className="admin-toggle">
              <input
                type="checkbox"
                checked={form.enforce_task_budget}
                onChange={(event) => set({ enforce_task_budget: event.target.checked })}
              />
              <span>
                <b>启用任务预算管控</b>
                <small>
                  开启后禁止直接发起测评与付费探测，统一走带预算的测评任务流
                  {view.billing_execution_config ? `（预算配置：${view.billing_execution_config}）` : "（当前未配置预算执行文件，开启前请先部署 AE_BILLING_EXECUTION_CONFIG）"}。
                </small>
              </span>
            </label>
            <label className="admin-toggle">
              <input
                type="checkbox"
                checked={form.evaluation_follow_up_enabled}
                onChange={(event) => set({ evaluation_follow_up_enabled: event.target.checked })}
              />
              <span>
                <b>启用测评跟进</b>
                <small>控制测评结果跟进链路是否开放。</small>
              </span>
            </label>
          </Card>
          <Card title="归档清单（隐藏指定资源）">
            <p className="muted admin-para">填入 UUID（每行一个或用逗号分隔）后，对应清单/编译将从测评选配中隐藏并拒绝提交。</p>
            <label className="admin-field">
              <span>归档清单 ID（archived_manifest_ids）</span>
              <textarea
                rows={3}
                value={form.archived_manifest_ids}
                onChange={(event) => set({ archived_manifest_ids: event.target.value })}
                placeholder={"00000000-0000-0000-0000-000000000000"}
              />
            </label>
            <label className="admin-field">
              <span>归档编译 ID（archived_compilation_ids）</span>
              <textarea
                rows={3}
                value={form.archived_compilation_ids}
                onChange={(event) => set({ archived_compilation_ids: event.target.value })}
                placeholder={"00000000-0000-0000-0000-000000000000"}
              />
            </label>
          </Card>
          <Card title="Langfuse 集成链接">
            <label className="admin-field">
              <span>浏览器访问地址（langfuse_browser_url）</span>
              <input
                value={form.langfuse_browser_url}
                onChange={(event) => set({ langfuse_browser_url: event.target.value })}
                placeholder="https://langfuse.example.com"
              />
            </label>
            <label className="admin-field">
              <span>服务端地址（langfuse_host）</span>
              <input
                value={form.langfuse_host}
                onChange={(event) => set({ langfuse_host: event.target.value })}
                placeholder="https://langfuse.example.com"
              />
            </label>
            <label className="admin-field">
              <span>项目 ID（langfuse_project_id）</span>
              <input
                value={form.langfuse_project_id}
                onChange={(event) => set({ langfuse_project_id: event.target.value })}
                placeholder="project-id"
              />
            </label>
          </Card>
          <div className="admin-save">
            <button className="primary" type="button" disabled={saving} onClick={save}>
              <Save size={16} />{saving ? "保存中…" : "保存配置"}
            </button>
          </div>
          <Note><Info size={17} />保存后立即在当前后端进程生效并持久化到数据库；多进程部署时其余进程在重启后自动加载。</Note>
        </>
      )}
    </div>
  );
}