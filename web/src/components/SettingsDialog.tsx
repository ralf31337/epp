import { useEffect, useState } from "react";
import { api, icsUrl, mcpUrl } from "../api";
import { formatDateTime } from "../format";
import type { AppConfig, OllamaEndpoint } from "../types";
import { CopyField } from "./CopyField";
import { Modal } from "./Modal";

const DEFAULT_CRON = "30 6,18 * * *";

interface Props {
  config: AppConfig;
  onSaved: (config: AppConfig, ollamaChanged: boolean) => void;
  onClose: () => void;
}

function OllamaSection({
  title,
  hint,
  value,
  onChange,
  showMode = false,
}: {
  title: string;
  hint: string;
  value: OllamaEndpoint;
  onChange: (v: OllamaEndpoint) => void;
  showMode?: boolean;
}) {
  const [models, setModels] = useState<string[] | null>(null);
  const [state, setState] = useState<{ ok?: string; error?: string; busy?: boolean }>({});

  const load = async () => {
    setState({ busy: true });
    try {
      const res = await api.ollamaModels(value.host, value.port);
      setModels(res.models);
      setState({ ok: `Connected to ${res.base_url}: ${res.models.length} model(s)` });
    } catch (err) {
      setModels(null);
      setState({ error: (err as Error).message });
    }
  };

  return (
    <section className="settings-section">
      <h4>
        <label className="check">
          <input type="checkbox" checked={value.enabled} onChange={(e) => onChange({ ...value, enabled: e.target.checked })} />
          {title}
        </label>
      </h4>
      <p className="muted small">{hint}</p>
      <div className="field-row">
        <label className="field">
          <span>Host</span>
          <input value={value.host} onChange={(e) => onChange({ ...value, host: e.target.value })} placeholder="host.docker.internal" />
        </label>
        <label className="field port">
          <span>Port</span>
          <input
            type="number"
            min={1}
            max={65535}
            value={value.port}
            onChange={(e) => onChange({ ...value, port: Number(e.target.value) })}
          />
        </label>
        <button onClick={load} disabled={state.busy || !value.host}>
          {state.busy ? "Checking…" : "Test & load models"}
        </button>
      </div>
      <label className="field">
        <span>Model</span>
        {models && models.length > 0 ? (
          <select value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })}>
            {!models.includes(value.model) && <option value={value.model}>{value.model || "Select a model…"}</option>}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <input value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} placeholder="e.g. qwen2.5vl:7b" />
        )}
      </label>
      {showMode && (
        <label className="field">
          <span>Pages sent to the model</span>
          <select value={value.mode} onChange={(e) => onChange({ ...value, mode: e.target.value as OllamaEndpoint["mode"] })}>
            <option value="auto">Only scanned pages and images (PDF text layer otherwise) – fast</option>
            <option value="always">Every page – best structure, slow (about 1 min per page)</option>
          </select>
        </label>
      )}
      {state.ok && <div className="ok-text">{state.ok}</div>}
      {state.error && <div className="error-text">{state.error}</div>}
      {value.enabled && !value.model && <div className="error-text">Choose a model to enable this step.</div>}
    </section>
  );
}

export function SettingsDialog({ config, onSaved, onClose }: Props) {
  const [cron, setCron] = useState(config.schedule_cron);
  const [cronInfo, setCronInfo] = useState<{ runs?: string[]; tz?: string; error?: string }>({});
  const [webhook, setWebhook] = useState(config.webhook_url ?? "");
  const [webhookState, setWebhookState] = useState<{ ok?: boolean; error?: string; busy?: boolean }>({});
  const [pdf, setPdf] = useState(config.pdf_ollama);
  const [context, setContext] = useState(config.context_ollama);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      api
        .cronPreview(cron)
        .then((r) => current && setCronInfo({ runs: r.next_runs, tz: r.timezone }))
        .catch((err) => current && setCronInfo({ error: (err as Error).message }));
    }, 300);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [cron]);

  const testWebhook = async () => {
    setWebhookState({ busy: true });
    try {
      await api.testWebhook(webhook.trim());
      setWebhookState({ ok: true });
    } catch (err) {
      setWebhookState({ error: (err as Error).message });
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.saveConfig({
        schedule_cron: cron,
        webhook_url: webhook.trim() || null,
        pdf_ollama: pdf,
        context_ollama: context,
      });
      const changed =
        JSON.stringify([config.pdf_ollama, config.context_ollama]) !== JSON.stringify([saved.pdf_ollama, saved.context_ollama]);
      onSaved(saved, changed);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Settings"
      wide
      onClose={onClose}
      footer={
        <>
          {error && <span className="error-text">{error}</span>}
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={saving || !!cronInfo.error}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <section className="settings-section">
        <h4>Update schedule</h4>
        <label className="field">
          <span>Cron expression (minute hour day month weekday)</span>
          <div className="feed-row">
            <input
              className={cronInfo.error ? "invalid" : ""}
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              spellCheck={false}
              style={{ fontFamily: "ui-monospace, Menlo, monospace", color: "inherit", fontSize: 13 }}
            />
            {cron !== DEFAULT_CRON && <button onClick={() => setCron(DEFAULT_CRON)}>Default (6:30 &amp; 18:30)</button>}
          </div>
        </label>
        {cronInfo.error ? (
          <div className="error-text">{cronInfo.error}</div>
        ) : (
          cronInfo.runs && (
            <div className="muted small">
              Next runs ({cronInfo.tz}): {cronInfo.runs.slice(0, 3).map(formatDateTime).join(" · ")}
            </div>
          )
        )}
      </section>

      <section className="settings-section">
        <h4>Webhook for new letters</h4>
        <p className="muted small">
          Receives a JSON POST (<code>event: "letter.created"</code>) with title, summary, appointments and Markdown
          whenever a new letter appears. Not sent for the initial import.
        </p>
        <div className="feed-row">
          <input
            value={webhook}
            onChange={(e) => {
              setWebhook(e.target.value);
              setWebhookState({});
            }}
            placeholder="https://example.org/hooks/elternbrief"
            style={{ color: "inherit", fontSize: 13 }}
          />
          <button onClick={testWebhook} disabled={!webhook.trim() || webhookState.busy}>
            {webhookState.busy ? "Sending…" : webhookState.ok ? "Sent ✓" : "Send test"}
          </button>
        </div>
        {webhookState.error && <div className="error-text">{webhookState.error}</div>}
      </section>

      <OllamaSection
        title="PDF parsing with Ollama"
        hint="Transcribes PDF pages and image attachments with a vision model (e.g. qwen3-vl, qwen2.5vl, granite3.2-vision). Without it, only the PDF text layer is used."
        value={pdf}
        onChange={setPdf}
        showMode
      />
      <OllamaSection
        title="Summary & appointments with Ollama"
        hint="Creates a short summary with the essential facts and extracts dates/appointments for the daily summary and the calendar feed."
        value={context}
        onChange={setContext}
      />

      <section className="settings-section">
        <h4>Calendar feed (ICS)</h4>
        <p className="muted small">Subscribe in Outlook, Google or Apple Calendar. The link is stable across restarts.</p>
        <CopyField value={icsUrl(config.ics_token)} label="Calendar feed URL" />
      </section>

      <section className="settings-section">
        <h4>Integrations</h4>
        <span className="muted small">MCP server (streamable HTTP, no auth)</span>
        <CopyField value={mcpUrl()} label="MCP URL" />
        <span className="muted small">
          REST API: <a href="docs" target="_blank" rel="noopener">OpenAPI docs</a>
        </span>
      </section>
    </Modal>
  );
}
