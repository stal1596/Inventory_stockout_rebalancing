import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The API pays a ~50s warm-up on first boot, so give proxied calls room
    // rather than surfacing a gateway timeout that looks like a bug.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, timeout: 120000 },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
