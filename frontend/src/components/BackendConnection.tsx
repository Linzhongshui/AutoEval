import { useEffect, useState } from "react";
import { apiGet, type BackendCapabilities } from "../services/api";

export function BackendConnection() {
  const [state, setState] = useState("正在检查后端连接…");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    setState("正在检查后端连接…");
    apiGet<BackendCapabilities>("/system/capabilities", controller.signal)
      .then((data) => { if (active) setState(data.evaluation_enabled
        ? "后端已连接；页面业务接入状态请以当前功能提示为准"
        : "后端已连接；正式测评尚未启用，已接入功能以各区提示为准，其余为示例数据"); })
      .catch(() => {
        if (active) setState("后端未连接或请求超时；当前页面为示例数据");
      });
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [retry]);
  return <div className="backend-connection" role="status">
    <span>{state}</span>
    <button type="button" onClick={() => setRetry((value) => value + 1)}>重新检查</button>
  </div>;
}
