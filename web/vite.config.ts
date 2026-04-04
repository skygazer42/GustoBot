import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [vue()],
    server: {
      port: Number(env.VITE_PORT || 5174),
      host: true,
      proxy: {
        "/api": {
          target: env.VITE_API_BASE_URL || "http://localhost:8000",
          changeOrigin: true
        },
        "/uploads": {
          target: env.VITE_API_BASE_URL || "http://localhost:8000",
          changeOrigin: true
        }
      }
    }
  };
});
