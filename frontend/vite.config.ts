import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://artemis-api:8000" } },
  test: { environment: "jsdom", exclude: ["**/node_modules/**", "**/dist/**", "**/._*"] },
});
