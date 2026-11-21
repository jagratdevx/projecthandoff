import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: apiProxy,
  },
  // Production bundle served locally: same-origin /api via the proxy, but
  // without Vite's dev module graph — noticeably faster first paint.
  preview: {
    port: 5173,
    proxy: apiProxy,
  },
});
