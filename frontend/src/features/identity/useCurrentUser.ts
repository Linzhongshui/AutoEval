import { useEffect, useState } from "react";
import { apiGet, ApiError } from "../../shared/api";

export type CurrentUser = {
  id: string;
  provider: string;
  login: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
  role: "admin" | "regular";
};

export type ProviderOption = { provider: string; display_name: string };

export type AuthState =
  | { status: "loading" }
  | { status: "guest" }
  | { status: "signed-in"; user: CurrentUser };

// 读取当前会话用户；401 视为未登录，其他失败（后端不可达等）同样按未登录处理，
// 连接问题由 BackendConnection 横幅提示，避免误判为已登录。
export function useCurrentUser(): { auth: AuthState; refresh: () => void } {
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    apiGet<CurrentUser>("/auth/me", controller.signal)
      .then((user) => {
        if (active) setAuth({ status: "signed-in", user });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          setAuth({ status: "guest" });
        } else {
          setAuth({ status: "guest" });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [attempt]);
  return { auth, refresh: () => setAttempt((value) => value + 1) };
}

export function useGateProviders(guest: boolean): ProviderOption[] | null {
  const [providers, setProviders] = useState<ProviderOption[] | null>(null);
  useEffect(() => {
    if (!guest) return;
    let active = true;
    const controller = new AbortController();
    apiGet<ProviderOption[]>("/auth/providers", controller.signal)
      .then((list) => {
        if (active) setProviders(list);
      })
      .catch(() => {
        if (active) setProviders([]);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [guest]);
  return providers;
}