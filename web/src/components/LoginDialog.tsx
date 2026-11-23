import { useState } from "react";
import { api } from "../api";
import type { Status } from "../types";
import { Modal } from "./Modal";

const REMEMBER_KEY = "epp.login";

interface Props {
  status: Status;
  onDone: () => void;
  onClose: () => void;
}

function remembered(): { tenant: string; username: string } {
  try {
    return { tenant: "", username: "", ...JSON.parse(localStorage.getItem(REMEMBER_KEY) ?? "{}") };
  } catch {
    return { tenant: "", username: "" };
  }
}

export function LoginDialog({ status, onDone, onClose }: Props) {
  const initial = remembered();
  const [tenant, setTenant] = useState(status.credentials.tenant ?? initial.tenant);
  const [username, setUsername] = useState(status.credentials.username ?? initial.username);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const connected = status.credentials.configured;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.login(tenant.trim(), username.trim(), password);
      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ tenant: tenant.trim(), username: username.trim() }));
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={connected ? "Portal login" : "Connect to the Eltern-Portal"}
      onClose={onClose}
      footer={
        <>
          {connected && (
            <button
              className="danger"
              onClick={async () => {
                await api.logout();
                onDone();
              }}
            >
              Disconnect
            </button>
          )}
          <span className="spacer" />
          <button onClick={onClose}>Cancel</button>
          <button
            className="primary"
            type="submit"
            form="login-form"
            disabled={busy || !tenant.trim() || !username.trim() || !password}
          >
            {busy ? "Checking…" : connected ? "Reconnect" : "Connect"}
          </button>
        </>
      }
    >
      <p className="muted">
        The login is checked against the portal and kept in memory only. After a container restart you need to
        enter it again; scheduled syncs are skipped until then.
      </p>
      <form
        id="login-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <label className="field">
          <span>School (tenant)</span>
          <div className="input-suffix">
            <input
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              placeholder="sub-domain, e.g. myschool"
              autoFocus={!tenant}
              autoCapitalize="off"
              spellCheck={false}
            />
            <span>.eltern-portal.org</span>
          </div>
        </label>
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus={!!tenant && !username}
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            autoFocus={!!tenant && !!username}
          />
        </label>
        {error && <div className="error-text">{error}</div>}
      </form>
    </Modal>
  );
}
