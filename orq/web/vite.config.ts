import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// `npm run dev` fala com o servidor do orq (`orq web --no-open`) na porta padrão.
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: "dist", emptyOutDir: true, assetsDir: "assets", sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:49390" } },
});
