import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    proxy: {
      "/api/autoeval": loadEnv(mode, ".", "AE_DEV_").AE_DEV_API_ORIGIN || "http://127.0.0.1:8000",
    },
  },
}));
