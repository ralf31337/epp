import { useState } from "react";
import { attachmentTextUrl, attachmentUrl } from "../api";
import { formatDateTime, formatSize } from "../format";
import type { Attachment, Letter } from "../types";
import { EventItem } from "./EventItem";
import { Markdown } from "./Markdown";

interface Props {
  letter: Letter;
  busy: boolean;
  onReprocess: () => void;
}

function AttachmentItem({ letterId, att }: { letterId: string; att: Attachment }) {
  const [text, setText] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  const toggle = async () => {
    if (!open && text === null) {
      const res = await fetch(attachmentTextUrl(letterId, att.repo));
      setText(res.ok ? await res.text() : "");
    }
    setOpen(!open);
  };

  return (
    <li className="attachment">
      <div className="attachment-head">
        <span className="attachment-name">{att.name}</span>
        <span className="muted small">{formatSize(att.size)}</span>
        {att.text_method && (
          <span className={`chip ${att.text_method.startsWith("ollama") ? "ok" : ""}`} title="How the text was extracted">
            {att.text_method}
          </span>
        )}
        {att.text_error && (
          <span className="chip danger" title={att.text_error}>
            Ollama failed
          </span>
        )}
        <span className="spacer" />
        {att.text_file && (
          <button className="small" onClick={toggle}>
            {open ? "Hide text" : "Show text"}
          </button>
        )}
        <a className="button small" href={attachmentUrl(letterId, att.repo)} target="_blank" rel="noopener">
          Open
        </a>
        <a className="button small" href={attachmentUrl(letterId, att.repo, true)}>
          Download
        </a>
      </div>
      {open && (
        <div className="attachment-text">
          {text ? <Markdown text={text} /> : <span className="muted small">No text could be extracted.</span>}
        </div>
      )}
    </li>
  );
}

export function LetterView({ letter, busy, onReprocess }: Props) {
  const a = letter.analysis;
  return (
    <div className="content-inner">
      <div className="page-head">
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
          <h2>{letter.title}</h2>
          <span className="letter-meta">
            {letter.label} · {formatDateTime(letter.published_at)}
            {letter.classes.length > 0 && <> · Klasse/n {letter.classes.join(", ")}</>}
            {letter.kind === "notice" ? (
              <span className="chip">Schwarzes Brett</span>
            ) : letter.acknowledged ? (
              <span className="chip ok">receipt confirmed</span>
            ) : (
              <span className="chip warn">unconfirmed</span>
            )}
          </span>
        </div>
        <span className="spacer" />
        <div className="actions">
          <a className="button small" href={`api/letters/${letter.id}/markdown`} target="_blank" rel="noopener">
            Markdown
          </a>
          <button className="small" onClick={onReprocess} disabled={busy} title="Extract attachment text and analyse again">
            Reprocess
          </button>
        </div>
      </div>

      {letter.analysis_error && (
        <div className="card" style={{ borderColor: "#f5caca" }}>
          <span className="error-text">Analysis failed: {letter.analysis_error}</span>
        </div>
      )}

      {a && (
        <section className="card ok">
          <h3>
            Summary <span className="spacer" />
            <span className="muted small">{a.model}</span>
          </h3>
          {a.summary && <p style={{ margin: 0, lineHeight: 1.55 }}>{a.summary}</p>}
          {a.key_facts.length > 0 && (
            <ul className="facts">
              {a.key_facts.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {a && a.events.length > 0 && (
        <section className="card">
          <h3>Appointments</h3>
          <ul className="events">
            {a.events.map((e, i) => (
              <EventItem key={i} event={e} />
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h3>{letter.kind === "notice" ? "Notice" : "Letter"}</h3>
        {letter.description_md ? <Markdown text={letter.description_md} /> : <span className="muted">No text.</span>}
      </section>

      <section className="card">
        <h3>Attachments</h3>
        {letter.attachments.length ? (
          <ul className="attachments">
            {letter.attachments.map((att) => (
              <AttachmentItem key={att.repo} letterId={letter.id} att={att} />
            ))}
          </ul>
        ) : (
          <span className="muted">No attachments.</span>
        )}
      </section>

      <p className="muted small" style={{ margin: 0 }}>
        SHA-256 of the description: <code>{letter.description_sha256}</code>
      </p>
    </div>
  );
}
