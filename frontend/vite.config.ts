import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backendTarget = process.env.STRATA_BACKEND_URL ?? "http://127.0.0.1:8000";
const frontendOrigin = process.env.STRATA_FRONTEND_ORIGIN;

function headerValues(rawHeaders: readonly string[], name: string): string[] {
  const values: string[] = [];
  for (let index = 0; index < rawHeaders.length; index += 2) {
    if (rawHeaders[index]?.toLowerCase() === name) values.push(rawHeaders[index + 1] ?? "");
  }
  return values;
}

function effectivePort(url: URL): string {
  return url.port || (url.protocol === "https:" ? "443" : "80");
}

export function devTunnelOriginOverride(
  rawHeaders: readonly string[],
  method: string | undefined,
  path: string | undefined,
  localPort: number | undefined,
  trustedOrigin: string | undefined,
): string | undefined {
  if (!method || !["POST", "PATCH", "DELETE"].includes(method.toUpperCase()) || !path?.startsWith("/api/")) return undefined;
  if (!trustedOrigin || localPort === undefined) return undefined;

  let trusted: URL;
  let incoming: URL;
  let referer: URL;
  try {
    trusted = new URL(trustedOrigin);
    const origins = headerValues(rawHeaders, "origin");
    const referers = headerValues(rawHeaders, "referer");
    if (origins.length !== 1 || referers.length !== 1) return undefined;
    incoming = new URL(origins[0]);
    referer = new URL(referers[0]);
  } catch {
    return undefined;
  }

  const hosts = headerValues(rawHeaders, "host");
  const forwardedHosts = headerValues(rawHeaders, "x-forwarded-host");
  const forwardedProtocols = headerValues(rawHeaders, "x-forwarded-proto");
  const fetchSites = headerValues(rawHeaders, "sec-fetch-site");
  const normalizedTrustedOrigin = trustedOrigin.replace(/\/+$/, "");

  if (
    trusted.protocol !== "https:" ||
    !trusted.hostname.endsWith(".devtunnels.ms") ||
    normalizedTrustedOrigin !== trusted.origin ||
    hosts.length !== 1 || hosts[0].toLowerCase() !== `localhost:${localPort}` ||
    forwardedHosts.length !== 1 || forwardedHosts[0].toLowerCase() !== trusted.host.toLowerCase() ||
    forwardedProtocols.length !== 1 || forwardedProtocols[0].toLowerCase() !== "https" ||
    fetchSites.length !== 1 || fetchSites[0].toLowerCase() !== "same-origin" ||
    incoming.protocol !== "http:" || incoming.hostname !== "localhost" || effectivePort(incoming) !== String(localPort) ||
    referer.origin !== trusted.origin
  ) return undefined;

  return trusted.origin;
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/health": { target: backendTarget, changeOrigin: false },
      // Preserve the browser-facing host for backend same-origin checks.
      "/api": {
        target: backendTarget,
        changeOrigin: false,
        configure(proxy) {
          proxy.on("proxyReq", (proxyRequest, request) => {
            const replacement = devTunnelOriginOverride(
              request.rawHeaders,
              request.method,
              request.url,
              request.socket.localPort,
              frontendOrigin,
            );
            if (replacement) proxyRequest.setHeader("origin", replacement);
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}", "vite.config.test.ts"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
