import type { AppConfig, DailySummary, Letter, Status } from "./types";

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data) ?? `Request failed (${res.status}).`);
  return data as T;
}

function errorMessage(data: unknown): string | null {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ");
  }
  return null;
}

export type ConfigUpdate = Omit<AppConfig, "ics_token">;

export const api = {
  status: () => request<Status>("GET", "api/status"),
  login: (tenant: string, username: string, password: string) =>
    request("POST", "api/credentials", { tenant, username, password }),
  logout: () => request("DELETE", "api/credentials"),

  letters: () => request<Letter[]>("GET", "api/letters"),
  daily: () => request<DailySummary>("GET", "api/daily"),

  sync: () => request("POST", "api/sync"),
  process: () => request("POST", "api/process"),
  reprocess: (id: string) => request("POST", `api/letters/${id}/reprocess`),

  config: () => request<AppConfig>("GET", "api/config"),
  saveConfig: (config: ConfigUpdate) => request<AppConfig>("PUT", "api/config", config),
  cronPreview: (expr: string) =>
    request<{ expr: string; timezone: string; next_runs: string[] }>(
      "GET",
      `api/config/cron-preview?expr=${encodeURIComponent(expr)}`,
    ),
  testWebhook: (url: string) => request("POST", "api/config/webhook-test", { url }),
  ollamaModels: (host: string, port: number) =>
    request<{ base_url: string; models: string[] }>(
      "GET",
      `api/ollama/models?host=${encodeURIComponent(host)}&port=${port}`,
    ),
};

export const attachmentUrl = (letterId: string, repo: string, download = false) =>
  `api/letters/${letterId}/attachments/${repo}${download ? "?download=true" : ""}`;

export const attachmentTextUrl = (letterId: string, repo: string) =>
  `api/letters/${letterId}/attachments/${repo}/text`;

/** Absolute URL for a path relative to the app, correct behind reverse proxies and sub-paths. */
export const absoluteUrl = (path: string) => new URL(path, document.baseURI).toString();

export const icsUrl = (token: string) => absoluteUrl(`ics/${token}.ics`);
export const mcpUrl = () => absoluteUrl("mcp");
