import type { FullConfig } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

type Service = { child: ChildProcess; graceful: boolean; label: string };

export default async function globalSetup(_config: FullConfig): Promise<() => Promise<void>> {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
  const frontend = join(root, "frontend");
  const backendPort = parsePort(process.env.STRATA_E2E_BACKEND_PORT ?? "18100", "backend");
  const frontendPort = parsePort(process.env.STRATA_E2E_FRONTEND_PORT ?? "15173", "frontend");
  if (backendPort === frontendPort) throw new Error("Backend and frontend E2E ports must differ.");

  const temporaryRoot = await mkdtemp(join(tmpdir(), "strata-e2e-"));
  const productData = join(temporaryRoot, "product");
  const sqlData = join(temporaryRoot, "sql");
  assertInside(temporaryRoot, productData, "product");
  assertInside(temporaryRoot, sqlData, "SQL");
  if (resolve(productData) === resolve(sqlData)) throw new Error("Product and SQL storage must be distinct.");

  const python = process.platform === "win32" ? join(root, ".venv", "Scripts", "python.exe") : join(root, ".venv", "bin", "python");
  const vite = join(frontend, "node_modules", "vite", "bin", "vite.js");
  const services: Service[] = [];
  let controlTimer: NodeJS.Timeout | undefined;
  let backendService: Service;

  const startBackend = () => start(
    python, [join(root, "scripts", "e2e_backend.py"), "--port", String(backendPort)], root,
    {
      STRATA_PRODUCT_DATA_DIR: productData,
      STRATA_DATA_DIR: sqlData,
      STRATA_FRONTEND_ORIGIN: `http://127.0.0.1:${frontendPort}`,
      STRATA_SESSION_COOKIE_SECURE: "false",
    }, "backend", true,
  );

  const teardown = async () => {
    if (controlTimer) clearInterval(controlTimer);
    for (const service of [...services].reverse()) await stop(service.child);
    delete process.env.STRATA_E2E_CONTROL_DIR;
    assertSafeTemporaryRoot(temporaryRoot);
    await rm(temporaryRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  };

  try {
    backendService = startBackend();
    services.push(backendService);
    await waitFor(`http://127.0.0.1:${backendPort}/health`, backendService);

    const frontendService = start(process.execPath, [vite, "--host", "127.0.0.1", "--port", String(frontendPort), "--strictPort"], frontend, {
      STRATA_BACKEND_URL: `http://127.0.0.1:${backendPort}`,
    }, "frontend");
    services.push(frontendService);
    await waitFor(`http://127.0.0.1:${frontendPort}/health`, frontendService);
    process.env.STRATA_E2E_CONTROL_DIR = temporaryRoot;
    controlTimer = installRestartControl(temporaryRoot, async () => {
      await stop(backendService.child);
      backendService = startBackend();
      services.push(backendService);
      await waitFor(`http://127.0.0.1:${backendPort}/health`, backendService);
    });
    console.log(`Strata E2E ready at http://127.0.0.1:${frontendPort} with isolated storage ${temporaryRoot}`);
    return teardown;
  } catch (error) {
    await teardown();
    throw error;
  }
}

function start(command: string, args: string[], cwd: string, extraEnv: NodeJS.ProcessEnv, label: string, graceful = false): Service {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...extraEnv }, stdio: [graceful ? "pipe" : "ignore", "pipe", "pipe"], windowsHide: true });
  child.stdout?.on("data", (chunk: Buffer) => process.stdout.write(`[${label}] ${chunk.toString()}`));
  child.stderr?.on("data", (chunk: Buffer) => process.stderr.write(`[${label}] ${chunk.toString()}`));
  return { child, graceful, label };
}

async function waitFor(url: string, service: Service): Promise<void> {
  const deadline = Date.now() + 45_000;
  let lastError = "not ready";
  while (Date.now() < deadline) {
    if (service.child.exitCode !== null) throw new Error(`${service.label} exited with code ${service.child.exitCode}.`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error(`${service.label} health check timed out: ${lastError}`);
}

async function stop(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (child.stdin !== null && child.stdin.writable) {
    child.stdin.write("stop\n");
    const graceful = await Promise.race([
      new Promise<boolean>((resolveWait) => child.once("exit", () => resolveWait(true))),
      new Promise<boolean>((resolveWait) => setTimeout(() => resolveWait(false), 15_000)),
    ]);
    if (graceful) return;
  }
  if (process.platform === "win32" && child.pid !== undefined) {
    const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    await new Promise<void>((resolveWait) => killer.once("exit", () => resolveWait()));
    return;
  }
  child.kill("SIGTERM");
  await Promise.race([
    new Promise<void>((resolveWait) => child.once("exit", () => resolveWait())),
    new Promise<void>((resolveWait) => setTimeout(resolveWait, 5_000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

function installRestartControl(temporaryRoot: string, restart: () => Promise<void>): NodeJS.Timeout {
  const requestPath = join(temporaryRoot, "restart-request.json");
  const responsePath = join(temporaryRoot, "restart-response.json");
  let busy = false;
  return setInterval(() => {
    if (busy) return;
    busy = true;
    void readFile(requestPath, "utf8").then(async (content) => {
      const request = JSON.parse(content) as { nonce?: unknown };
      if (typeof request.nonce !== "string" || request.nonce.length < 8) throw new Error("Invalid E2E restart nonce.");
      try {
        await restart();
        await writeFile(responsePath, JSON.stringify({ nonce: request.nonce, status: "ready" }), "utf8");
      } catch (error) {
        await writeFile(responsePath, JSON.stringify({ nonce: request.nonce, status: "failed", error: error instanceof Error ? error.message : String(error) }), "utf8");
      } finally {
        await unlink(requestPath).catch(() => undefined);
      }
    }).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== "ENOENT") process.stderr.write(`[e2e-control] ${error.message}\n`);
    }).finally(() => { busy = false; });
  }, 100);
}

function parsePort(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1024 || parsed > 65535) throw new Error(`Invalid ${label} E2E port.`);
  return parsed;
}

function assertInside(parent: string, candidate: string, label: string): void {
  const rel = relative(resolve(parent), resolve(candidate));
  if (!rel || rel === ".." || rel.startsWith(`..${sep}`) || isAbsolute(rel)) throw new Error(`${label} storage is not inside the disposable E2E root.`);
}

function assertSafeTemporaryRoot(value: string): void {
  const path = resolve(value);
  const temp = resolve(tmpdir());
  const rel = relative(temp, path);
  if (!path.startsWith(`${temp}${sep}`) || !rel.startsWith("strata-e2e-") || rel.includes(sep)) throw new Error("Refusing to remove an unverified E2E directory.");
}
