import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the app on :5173 and proxies /api (requests and event streams) to the
// FastAPI server (`python -m agent.web`, WEB_PORT, default 8000). FastAPI refuses a foreign
// Host or Origin, so the proxy presents the request as coming from FastAPI's own address.
const apiPort = process.env.WEB_PORT ?? "8000";
const api = `http://127.0.0.1:${apiPort}`;
const devPort = 5173;

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: devPort,
    strictPort: true,
    proxy: {
      "/api": {
        target: api,
        changeOrigin: true, // Host: 127.0.0.1:<WEB_PORT>
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            // Only the dev server's own pages become FastAPI's origin; any other origin stays foreign.
            const origin = req.headers.origin;
            if (origin === `http://127.0.0.1:${devPort}` || origin === `http://localhost:${devPort}`) {
              proxyReq.setHeader("origin", api);
            }
          });
        },
      },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
