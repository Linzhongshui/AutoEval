import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    // GitCode 回调地址校验不接受 localhost，OAuth 回调经 127.0.0.1:8000 直连后端；
    // 前端页面通过 127.0.0.1:5173 访问，与会话 Cookie 同域，登录后才能保持会话。
    host: "127.0.0.1",
    proxy: {
      "/api/autoeval": loadEnv(mode, ".", "AE_DEV_").AE_DEV_API_ORIGIN || "http://127.0.0.1:8000",
    },
  },
}));
