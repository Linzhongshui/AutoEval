import { LogOut } from "lucide-react";
import { apiPost, ApiError } from "../../shared/api";
import type { CurrentUser } from "./useCurrentUser";

export function UserArea({
  user,
  onLoggedOut,
  notify,
}: {
  user: CurrentUser;
  onLoggedOut: () => void;
  notify: (message: string) => void;
}) {
  const isLocal = user.provider === "local";
  const signOut = async () => {
    try {
      await apiPost<{ ok: boolean }>("/auth/logout");
      onLoggedOut();
    } catch (error: unknown) {
      notify(error instanceof ApiError ? `退出失败：${error.message}` : "退出失败，请重试。");
    }
  };
  return (
    <div className="user-area">
      {user.avatar_url ? (
        <img className="user-avatar" src={user.avatar_url} alt="" />
      ) : (
        <span className="user-avatar user-avatar-fallback">{user.display_name.slice(0, 1)}</span>
      )}
      <span className="user-name" title={user.login}>{user.display_name}</span>
      {user.role === "superadmin" && <span className="user-role">超级管理员</span>}
      {user.role === "admin" && <span className="user-role">管理员</span>}
      {!isLocal && (
        <button type="button" className="user-logout" onClick={signOut} title="退出登录">
          <LogOut size={15} />
          退出
        </button>
      )}
    </div>
  );
}