import { defineConfig } from "vite";
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

interface RuntimeManifest {
  readonly assets: Readonly<Record<string, { readonly path: string }>>;
}

function copyRuntimeAssets() {
  const repositoryRoot = resolve(import.meta.dirname, "..");
  const manifestPath = resolve(repositoryRoot, "assets/manifest.json");
  return {
    name: "copy-runtime-assets",
    closeBundle() {
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as RuntimeManifest;
      const output = resolve(import.meta.dirname, "dist");
      copyFileSync(manifestPath, resolve(output, "manifest.json"));
      for (const entry of Object.values(manifest.assets)) {
        const destination = resolve(output, entry.path);
        mkdirSync(dirname(destination), { recursive: true });
        copyFileSync(resolve(repositoryRoot, entry.path), destination);
      }
    },
  };
}

export default defineConfig({
  base: "/",
  publicDir: false,
  plugins: [copyRuntimeAssets()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
  },
});
