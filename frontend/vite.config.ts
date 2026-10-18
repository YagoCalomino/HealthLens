import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // loadEnv reads .env / .env.local / .env.{mode} from cwd; process.env alone
  // does NOT see .env files — Vite only injects them into the browser bundle,
  // not into the Node process that evaluates vite.config.ts.
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_BASE_URL;

  // Vitest runs the dev-server proxy code path too, but unit tests never hit
  // the backend through this proxy — only vite / vite build / vite preview do.
  if (!apiTarget && !process.env.VITEST) {
    throw new Error("VITE_API_BASE_URL must be set. See .env.example.");
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiTarget ?? "http://localhost:8000",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
