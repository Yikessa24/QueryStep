import { defineConfig } from "vite";

const api = process.env.QUERYSTEP_API_PROXY || "http://127.0.0.1:8000";
export default defineConfig({
  server: { proxy: { "/api": api, "/healthz": api } },
});
