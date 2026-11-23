import { useEffect, useState } from "react";
import { AlertCircle, ArrowRight, LogIn } from "lucide-react";
import { apiGet } from "../../shared/api";
import type { ProviderOption } from "./useCurrentUser";

const errorMessages: Record<string, string> = {
  canceled: "您已取消授权，未完成登录。",
  invalid_state: "登录请求已失效或校验未通过，请重新尝试。",
  expired: "登录授权已过期，请重新登录。",
  oauth_failed: "登录失败：平台授权或账号信息获取未成功，请重试。",
  suspended: "该账号已被停用，请联系管理员。",
  session_expired: "登录已过期，请重新登录。",
};

export function LoginPage({ error, onEnter }: { error: string | null; onEnter: () => void }) {
  const [providers, setProviders] = useState<ProviderOption[] | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    apiGet<ProviderOption[]>("/auth/providers", controller.signal)
      .then((list) => setProviders(list))
      .catch(() => setProviders([]));
    return () => controller.abort();
  }, []);

  const message = error ? (errorMessages[error] ?? "登录未完成，请重试。") : "";

  return (
    <div className="login-page">
      <div className="login-card" role="main">
        <img className="login-logo" src="/brand/autoeval-logo.svg" alt="AutoEval" />
        <h1>登录 AutoEval</h1>
        <p className="login-sub">使用 GitHub 或 GitCode 账号登录，新账号默认为普通用户。</p>
        {message && (
          <div className="login-error" role="alert">
            <AlertCircle size={16} />
            {message}
          </div>
        )}
        {providers === null ? (
          <p className="login-loading" role="status">正在读取登录方式…</p>
        ) : providers.length === 0 ? (
          <div className="login-local" role="status">
            <p>当前为本地开发模式，无需登录。</p>
            <button className="primary" type="button" onClick={onEnter}>
              <LogIn size={16} />
              进入控制台
            </button>
          </div>
        ) : (
          <div className="login-actions">
            {providers.map((provider) => (
              <a
                key={provider.provider}
                className="login-button"
                href={`/api/autoeval/v1/auth/login/${provider.provider}`}
              >
                {provider.provider === "github" ? <GitHubIcon /> : <GitCodeIcon />}
                <span>使用 {provider.display_name} 登录</span>
                <ArrowRight size={16} />
              </a>
            ))}
          </div>
        )}
        <p className="login-foot">登录即表示同意平台读取该账号的公开资料（用户名、头像）。</p>
      </div>
    </div>
  );
}

function GitHubIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 16 16" aria-hidden="true">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.03 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"
      />
    </svg>
  );
}

function GitCodeIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="18" cy="6" r="2.5" />
      <circle cx="12" cy="18" r="2.5" />
      <path d="M6 8.5v4.5M18 8.5v4.5M8.5 6h7M6 13.5c3.5 0 3.5 3 6 3" />
    </svg>
  );
}