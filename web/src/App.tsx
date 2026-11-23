import { useCallback, useEffect, useRef, useState } from "react";
import { api, icsUrl } from "./api";
import { CopyField } from "./components/CopyField";
import { DailyView } from "./components/DailyView";
import { LetterView } from "./components/LetterView";
import { LoginDialog } from "./components/LoginDialog";
import { Modal } from "./components/Modal";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar } from "./components/Sidebar";
import { relative } from "./format";
import type { AppConfig, DailySummary, Letter, Status } from "./types";

const routeFromHash = () => window.location.hash.replace(/^#\/?/, "") || "daily";

function jobLabel(status: Status): string {
  const { job } = status;
  if (job.running) return job.phase ?? `${job.kind}…`;
  if (!status.credentials.configured) return "Not connected";
  return `Synced ${relative(status.last_sync_at)}`;
}

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [letters, setLetters] = useState<Letter[]>([]);
  const [daily, setDaily] = useState<DailySummary | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [route, setRoute] = useState(routeFromHash);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"login" | "settings" | "subscribe" | null>(null);
  const wasRunning = useRef(false);
  const promptedLogin = useRef(false);

  const loadData = useCallback(async () => {
    try {
      const [nextLetters, nextDaily, nextConfig] = await Promise.all([api.letters(), api.daily(), api.config()]);
      setLetters(nextLetters);
      setDaily(nextDaily);
      setConfig(nextConfig);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const next = await api.status();
      setStatus(next);
      if (!next.credentials.configured && !promptedLogin.current) {
        promptedLogin.current = true;
        setDialog("login");
      }
      if (wasRunning.current && !next.job.running) {
        loadData();
        if (next.job.last_error) setError(`${next.job.kind} failed: ${next.job.last_error}`);
      }
      wasRunning.current = next.job.running;
      return next;
    } catch (err) {
      setError((err as Error).message);
      return null;
    }
  }, [loadData]);

  useEffect(() => {
    loadData();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const next = await loadStatus();
      timer = setTimeout(tick, next?.job.running ? 1500 : 15000);
    };
    tick();
    return () => clearTimeout(timer);
  }, [loadData, loadStatus]);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(null), 8000);
    return () => clearTimeout(timer);
  }, [error]);

  const navigate = (next: string) => {
    window.location.hash = `/${next}`;
  };

  const startJob = async (action: () => Promise<unknown>) => {
    try {
      await action();
      wasRunning.current = true;
    } catch (err) {
      setError((err as Error).message);
    }
    loadStatus();
  };

  if (!status) {
    return <div className="loading">{error ?? "Loading…"}</div>;
  }

  const letterId = route.startsWith("letters/") ? route.slice("letters/".length) : null;
  const letter = letterId ? letters.find((l) => l.id === letterId) : null;
  const busy = status.job.running;
  const connected = status.credentials.configured;
  const lastErrors = !busy ? status.job.last_result?.errors ?? [] : [];

  return (
    <div className="app">
      <header className="topbar">
        <h1>Eltern-Portal</h1>
        <button
          className={`live ${busy ? "live-busy" : connected ? "live-on" : ""}`}
          onClick={() => setDialog("login")}
          title={connected ? `${status.credentials.username} @ ${status.credentials.tenant}` : "Enter portal login"}
        >
          {jobLabel(status)}
        </button>
        <span className="spacer" />
        {status.next_run && (
          <span className="muted small" title={`Schedule: ${status.schedule_cron}`}>
            Next update {relative(status.next_run)}
          </span>
        )}
        <button onClick={() => startJob(api.sync)} disabled={busy || !connected}>
          Sync now
        </button>
        <button onClick={() => setDialog("settings")} disabled={!config}>
          Settings
        </button>
      </header>

      {!connected && (
        <div className="notice-banner">
          <span>
            Portal login required{status.scheduler_note ? " – scheduled updates are being skipped" : ""}. Credentials are
            kept in memory only and must be entered again after every restart.
          </span>
          <span className="spacer" />
          <button className="primary small" onClick={() => setDialog("login")}>
            Connect
          </button>
        </div>
      )}

      {error && (
        <div className="error-banner" role="alert" onClick={() => setError(null)}>
          {error}
        </div>
      )}

      {lastErrors.length > 0 && !error && (
        <div className="notice-banner" title={lastErrors.join("\n")}>
          <span>
            Last run finished with {lastErrors.length} problem(s): {lastErrors[0]}
          </span>
        </div>
      )}

      <main className="workspace">
        <Sidebar letters={letters} selected={letter ? `letters/${letter.id}` : route} onSelect={navigate} />
        <div className="content">
          {letterId ? (
            letter ? (
              <LetterView
                key={letter.id}
                letter={letter}
                busy={busy}
                onReprocess={() => startJob(() => api.reprocess(letter.id))}
              />
            ) : (
              <div className="empty-state">
                <h2>Letter not found</h2>
                <button onClick={() => navigate("daily")}>Back to daily summary</button>
              </div>
            )
          ) : letters.length === 0 && !busy ? (
            <div className="empty-state">
              <h2>No letters yet</h2>
              <p className="muted">Connect to the Eltern-Portal to download your Elternbriefe.</p>
              <button className="primary" onClick={() => (connected ? startJob(api.sync) : setDialog("login"))}>
                {connected ? "Sync now" : "Connect"}
              </button>
            </div>
          ) : (
            <DailyView
              daily={daily}
              status={status}
              onOpenLetter={(id) => navigate(`letters/${id}`)}
              onSubscribe={() => setDialog("subscribe")}
            />
          )}
        </div>
      </main>

      {dialog === "login" && (
        <LoginDialog
          status={status}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            wasRunning.current = true;
            loadStatus();
          }}
        />
      )}

      {dialog === "settings" && config && (
        <SettingsDialog
          config={config}
          onClose={() => setDialog(null)}
          onSaved={(saved, ollamaChanged) => {
            setConfig(saved);
            setDialog(null);
            if (ollamaChanged && (saved.pdf_ollama.enabled || saved.context_ollama.enabled) && !busy) {
              startJob(api.process);
            } else {
              loadStatus();
            }
          }}
        />
      )}

      {dialog === "subscribe" && config && (
        <Modal title="Calendar feed" onClose={() => setDialog(null)}>
          <p className="muted">
            All extracted appointments and deadlines as an ICS feed. Subscribe to this URL in your calendar app; it stays
            the same across restarts. Anyone who knows the link can read it.
          </p>
          <CopyField value={icsUrl(config.ics_token)} label="Calendar feed URL" />
        </Modal>
      )}
    </div>
  );
}
