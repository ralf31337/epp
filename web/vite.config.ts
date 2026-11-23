import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = "http://localhost:3081";

export default defineConfig({
  // Relative asset URLs so the app also works under a reverse-proxy sub-path.
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/ics": backend,
      "/mcp": backend,
      "/health": backend,
    },
  },
});
