import { useMemo, useState } from "react";
import type { Letter } from "../types";
import { formatDateTime } from "../format";

interface Props {
  letters: Letter[];
  selected: string | null;
  onSelect: (route: string) => void;
}

function matches(letter: Letter, terms: string[]): boolean {
  const text = [letter.title, letter.description_md, letter.analysis?.summary ?? "", ...(letter.analysis?.key_facts ?? [])]
    .join(" ")
    .toLowerCase();
  return terms.every((t) => text.includes(t));
}

export function Sidebar({ letters, selected, onSelect }: Props) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    return terms.length ? letters.filter((l) => matches(l, terms)) : letters;
  }, [letters, query]);

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <button className={`nav-item ${selected === "daily" ? "selected" : ""}`} onClick={() => onSelect("daily")}>
          Daily summary
        </button>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search letters…" />
      </div>
      <div className="sidebar-scroll">
        {filtered.length === 0 && <p className="muted small">{letters.length ? "No matching letters." : "No letters yet."}</p>}
        {filtered.map((letter) => {
          const events = letter.analysis?.events.length ?? 0;
          return (
            <button
              key={letter.id}
              className={`letter-item ${letter.analysis ? "analysed" : ""} ${selected === `letters/${letter.id}` ? "selected" : ""}`}
              onClick={() => onSelect(`letters/${letter.id}`)}
            >
              <span className="letter-title">{letter.title}</span>
              <span className="letter-meta">
                #{letter.number} · {formatDateTime(letter.published_at)}
              </span>
              <span className="chips">
                {letter.attachments.length > 0 && <span className="chip">📎 {letter.attachments.length}</span>}
                {events > 0 && <span className="chip ok">📅 {events}</span>}
                {!letter.acknowledged && <span className="chip warn">unconfirmed</span>}
                {letter.analysis_error && <span className="chip danger">analysis failed</span>}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
