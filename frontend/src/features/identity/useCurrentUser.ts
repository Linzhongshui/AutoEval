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
  | { status: "error" }
  | { status: "signed-in"; user: CurrentUser };

export type ProvidersState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; list: ProviderOption[] };

// 读取当前会话用户。只有 401 才算明确的“未登录”（访客）；
// 网络失败或 5xx 视为身份无法确认（error），由登录守卫拦截并提示，
// 绝不当作访客放行——访客只有在后端确认（local 模式返回本地操作员、
// OAuth 模式校验会话成功）之后才能进入应用。
export function useCurrentUser(): { auth: AuthState; refresh: () => void } {
  const [auth, setAuth] = useState<AuthState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setAuth({ status: "loading" });
    apiGet<CurrentUser>("/auth/me", controller.signal)
      .then((user) => {
        if (active) setAuth({ status: "signed-in", user });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          setAuth({ status: "guest" });
        } else {
          setAuth({ status: "error" });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [attempt]);
  return { auth, refresh: () => setAttempt((value) => value + 1) };
}

// 读取可用登录方式。请求失败（failed）与空列表（ready + []）是两种不同状态：
// 前者提示连接/配置异常，后者提示 OAuth 凭据未配置，二者都不能进入应用。
export function useGateProviders(guest: boolean): { providers: ProvidersState; reload: () => void } {
  const [providers, setProviders] = useState<ProvidersState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!guest) return;
    let active = true;
    const controller = new AbortController();
    setProviders({ status: "loading" });
    apiGet<ProviderOption[]>("/auth/providers", controller.signal)
      .then((list) => {
        if (active) setProviders({ status: "ready", list });
      })
      .catch(() => {
        if (active) setProviders({ status: "failed" });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [guest, attempt]);
  return { providers, reload: () => setAttempt((value) => value + 1) };
}