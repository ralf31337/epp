import { formatDate, formatDay } from "../format";
import type { DailyDay, DailySummary, LetterEvent, Status } from "../types";
import { EventItem } from "./EventItem";

interface Props {
  daily: DailySummary | null;
  status: Status;
  onOpenLetter: (id: string) => void;
  onSubscribe: () => void;
}

function openSource(le: LetterEvent, onOpenLetter: (id: string) => void) {
  if (le.letter_id) onOpenLetter(le.letter_id);
  else if (le.url) window.open(le.url, "_blank", "noopener");
}

function DayEvents({ day, onOpenLetter }: { day: DailyDay; onOpenLetter: (id: string) => void }) {
  return (
    <ul className="events">
      {day.events.map((le) => (
        <EventItem
          key={le.uid}
          event={le.event}
          withDate={false}
          source={`${le.letter_label}: ${le.letter_title}${le.also_in.length ? ` (also in ${le.also_in.join(", ")})` : ""}`}
          onClick={le.letter_id || le.url ? () => openSource(le, onOpenLetter) : undefined}
          clickTitle={le.letter_id ? "Open letter" : "Open in Eltern-Portal"}
        />
      ))}
    </ul>
  );
}

interface WeekProps {
  label: string;
  days: DailyDay[];
  start: string | null;
  end: string | null;
  emptyText: string;
  onOpenLetter: (id: string) => void;
}

function WeekSection({ label, days, start, end, emptyText, onOpenLetter }: WeekProps) {
  const busy = days.filter((d) => d.events.length > 0);
  return (
    <section className="card">
      <div className="card-title">
        <strong>{label}</strong>
        {start && end && (
          <span className="muted">
            {formatDate(start)} – {formatDate(end)}
          </span>
        )}
      </div>
      {busy.length ? (
        busy.map((day) => (
          <div className="day-group" key={day.date}>
            <span className="day-label">{formatDay(day.date)}</span>
            <DayEvents day={day} onOpenLetter={onOpenLetter} />
          </div>
        ))
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          {emptyText}
        </p>
      )}
    </section>
  );
}

export function DailyView({ daily, status, onOpenLetter, onSubscribe }: Props) {
  if (!daily) return <div className="loading muted">Loading…</div>;

  return (
    <div className="content-inner">
      <div className="page-head">
        <h2>Daily summary</h2>
        <span className="spacer" />
        <div className="actions">
          <a className="button small" href="api/daily.md" target="_blank" rel="noopener">
            Markdown
          </a>
          <button className="small" onClick={onSubscribe}>
            Subscribe to calendar
          </button>
        </div>
      </div>

      {!status.context_ollama && (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>
            Appointments from letters and notices are extracted by the Ollama analysis step, which is not enabled yet.
            Configure it in Settings to fill the daily summary and the calendar feed.
          </p>
        </div>
      )}

      <section className="card accent">
        <div className="card-title">
          <strong>{daily.focus_label}</strong>
          <span className="muted">{formatDay(daily.focus.date)}</span>
        </div>
        {daily.focus.events.length ? (
          <DayEvents day={daily.focus} onOpenLetter={onOpenLetter} />
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            No appointments.
          </p>
        )}
      </section>

      <WeekSection
        label={daily.rest_label}
        days={daily.rest}
        start={daily.rest_start}
        end={daily.rest_end}
        emptyText={daily.rest.length ? "No appointments." : "This is the last day of the week."}
        onOpenLetter={onOpenLetter}
      />

      <WeekSection
        label={daily.next_label}
        days={daily.next}
        start={daily.next_start}
        end={daily.next_end}
        emptyText="No appointments."
        onOpenLetter={onOpenLetter}
      />
    </div>
  );
}
