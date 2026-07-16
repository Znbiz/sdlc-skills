import fs from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const BACKEND_URL = process.env.ARCH_DOCS_BACKEND_URL ?? "http://localhost:8000";

function readBackendAuthSecret(): string | undefined {
  if (process.env.AUTH_SECRET) return process.env.AUTH_SECRET;
  try {
    const envPath = path.resolve(__dirname, "../arch-docs/.env");
    const content = fs.readFileSync(envPath, "utf-8");
    const match = content.match(/^AUTH_SECRET=(.*)$/m);
    return match?.[1]?.trim();
  } catch {
    return undefined;
  }
}

// Локальный dev-proxy играет ту же роль, что nginx в проде: инжектирует backend Bearer-токен
// на сервере (не в браузере), чтобы SPA не нуждалась в собственном runtime-секрете.
const backendAuthSecret = readBackendAuthSecret();

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND_URL,
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          if (!backendAuthSecret) return;
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("Authorization", `Bearer ${backendAuthSecret}`);
          });
        },
      },
    },
  },
  preview: {
    host: true,
    port: 4173,
  },
});
