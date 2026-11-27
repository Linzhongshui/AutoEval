import { useEffect, useState } from "react";
import { Ban, RotateCcw, Search } from "lucide-react";
import { apiGetPage, apiPatch, ApiError } from "../../shared/api";
import { Badge } from "../../shared/ui/Badge";
import type { CurrentUser } from "../identity/useCurrentUser";

export type AdminUser = {
  id: string;
  provider: string;
  login: string;
  display_name: string;
  email: string | null;
  role: "superadmin" | "admin" | "regular";
  suspended_at: string | null;
  created_at: string | null;
};

const roleLabels = {
  superadmin: "超级管理员",
  admin: "管理员",
  regular: "普通用户",
} as const;

export function AdminUsers({
  notify,
  viewer,
}: {
  notify: (message: string) => void;
  viewer: CurrentUser;
}) {
  // 角色变更（任何方向）仅超级管理员可执行；管理员只能停用/恢复普通用户
  const canManageRoles = viewer.role === "superadmin";
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [rows, setRows] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [message, setMessage] = useState("正在读取用户…");
  const [attempt, setAttempt] = useState(0);
  const [busyId, setBusyId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ offset: "0", limit: "100" });
    if (appliedQuery.trim()) params.set("q", appliedQuery.trim());
    apiGetPage<AdminUser[]>(`/admin/users?${params.toString()}`, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setRows(page.data);
        setTotal(page.total ?? page.data.length);
        setNextOffset(page.next_offset);
        setMessage(page.data.length ? "" : "没有匹配的用户。");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setRows([]);
        setNextOffset(null);
        setMessage(error instanceof ApiError ? `用户列表读取失败：${error.message}` : "用户列表读取失败，请重试。");
      });
    return () => controller.abort();
  }, [appliedQuery, attempt]);

  const loadMore = async () => {
    if (nextOffset === null || loadingMore) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams({ offset: String(nextOffset), limit: "100" });
      if (appliedQuery.trim()) params.set("q", appliedQuery.trim());
      const page = await apiGetPage<AdminUser[]>(`/admin/users?${params.toString()}`);
      setRows((value) => [...value, ...page.data]);
      setNextOffset(page.next_offset);
    } catch (error: unknown) {
      notify(error instanceof ApiError ? `加载更多失败：${error.message}` : "加载更多失败，请重试。");
    } finally {
      setLoadingMore(false);
    }
  };

  const mutate = async (id: string, body: object, okMessage: string, needConfirm?: string) => {
    if (busyId) return;
    if (needConfirm && !window.confirm(needConfirm)) return;
    setBusyId(id);
    try {
      await apiPatch<AdminUser>(`/admin/users/${id}`, body);
      notify(okMessage);
      setAttempt((value) => value + 1);
    } catch (error: unknown) {
      notify(error instanceof ApiError ? error.message : "操作失败，请重试。");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="stack admin-users">
      <div className="admin-toolbar">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setAppliedQuery(query);
          }}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="按登录名 / 昵称 / 邮箱搜索"
            aria-label="搜索用户"
          />
          <button type="submit"><Search size={15} />搜索</button>
        </form>
        <span className="admin-total">共 {total} 位用户</span>
      </div>
      {message && <p role="status" className="empty">{message}</p>}
      {rows.length > 0 && (
        <div className="user-table-wrap">
          <table className="user-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>来源</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>注册时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => {
                const suspended = user.suspended_at !== null;
                const demoting = user.role !== "regular";
                const isSelf = user.id === viewer.id;
                // 角色变更：超管任意；管理员唯一例外是把自己降级为普通用户
                const canChangeRole =
                  canManageRoles || (isSelf && viewer.role === "admin");
                // 停用/恢复：超管可处置任何账号；管理员只能处置普通用户
                const canSuspend = canManageRoles || user.role === "regular";
                const suspendHint = canSuspend
                  ? undefined
                  : "仅超级管理员可以停用管理员或超级管理员";
                return (
                  <tr key={user.id} className={suspended ? "suspended-row" : ""}>
                    <td>
                      <span className="user-name-cell">
                        <span className="user-mini-avatar">{user.display_name.slice(0, 1)}</span>
                        <span>
                          <b>{user.display_name}</b>
                          <small className="user-login-cell">@{user.login}</small>
                        </span>
                      </span>
                    </td>
                    <td>{user.provider}</td>
                    <td>{user.email || "—"}</td>
                    <td>
                      <select
                        value={user.role}
                        disabled={suspended || busyId === user.id || !canChangeRole}
                        title={
                          canManageRoles
                            ? undefined
                            : isSelf && viewer.role === "admin"
                              ? "管理员可以将自己降级为普通用户"
                              : "仅超级管理员可以调整角色"
                        }
                        onChange={(event) => {
                          const next = event.target.value as AdminUser["role"];
                          mutate(
                            user.id,
                            { role: next },
                            `已将 ${user.display_name} 调整为${roleLabels[next]}`,
                            demoting && next === "regular"
                              ? `确认将${roleLabels[user.role]} ${user.display_name} 降级为普通用户？`
                              : undefined,
                          );
                        }}
                        aria-label={`${user.display_name} 的角色`}
                      >
                        <option value="superadmin" disabled={!canManageRoles}>超级管理员</option>
                        <option value="admin" disabled={!canManageRoles}>管理员</option>
                        <option value="regular">普通用户</option>
                      </select>
                    </td>
                    <td>
                      {suspended ? <Badge tone="orange">已停用</Badge> : <Badge tone="green">正常</Badge>}
                    </td>
                    <td className="admin-muted">{user.created_at ? new Date(user.created_at).toLocaleDateString("zh-CN") : "—"}</td>
                    <td>
                      <div className="user-actions">
                        {suspended ? (
                          <button
                            type="button"
                            disabled={busyId === user.id || !canSuspend}
                            title={suspendHint ?? "恢复账号"}
                            onClick={() =>
                              mutate(user.id, { suspended: false }, `已恢复 ${user.display_name} 的账号`, undefined)
                            }
                          >
                            <RotateCcw size={14} />恢复
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="user-action-danger"
                            disabled={busyId === user.id || !canSuspend}
                            title={suspendHint ?? "停用账号"}
                            onClick={() =>
                              mutate(
                                user.id,
                                { suspended: true },
                                `已停用 ${user.display_name}，其所有会话已吊销`,
                                `停用后 ${user.display_name} 将立即退出且无法登录，确认停用？`,
                              )
                            }
                          >
                            <Ban size={14} />停用
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {nextOffset !== null && (
            <div className="admin-more">
              <button type="button" disabled={loadingMore} onClick={loadMore}>
                {loadingMore ? "加载中…" : "加载更多"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}