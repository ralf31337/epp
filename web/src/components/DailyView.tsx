import { formatDate, formatDay } from "../format";
import type { DailyDay, DailySummary, Status } from "../types";
import { EventItem } from "./EventItem";

interface Props {
  daily: DailySummary | null;
  status: Status;
  onOpenLetter: (id: string) => void;
  onSubscribe: () => void;
}

function DayEvents({ day, onOpenLetter }: { day: DailyDay; onOpenLetter: (id: string) => void }) {
  return (
    <ul className="events">
      {day.events.map((le) => (
        <EventItem
          key={le.uid}
          event={le.event}
          withDate={false}
          source={`Letter #${le.letter_number}: ${le.letter_title}${
            le.also_in.length ? ` (also in ${le.also_in.map((n) => `#${n}`).join(", ")})` : ""
          }`}
          onClick={() => onOpenLetter(le.letter_id)}
        />
      ))}
    </ul>
  );
}

export function DailyView({ daily, status, onOpenLetter, onSubscribe }: Props) {
  if (!daily) return <div className="loading muted">Loading…</div>;
  const restDays = daily.rest.filter((d) => d.events.length > 0);

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
            Appointments are extracted by the Ollama analysis step, which is not enabled yet. Configure it in
            Settings to fill the daily summary and the calendar feed.
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

      <section className="card">
        <div className="card-title">
          <strong>{daily.rest_label}</strong>
          {daily.rest_start && daily.rest_end && (
            <span className="muted">
              {formatDate(daily.rest_start)} – {formatDate(daily.rest_end)}
            </span>
          )}
        </div>
        {restDays.length ? (
          restDays.map((day) => (
            <div className="day-group" key={day.date}>
              <span className="day-label">{formatDay(day.date)}</span>
              <DayEvents day={day} onOpenLetter={onOpenLetter} />
            </div>
          ))
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            {daily.rest.length ? "No appointments." : "This is the last day of the week."}
          </p>
        )}
      </section>
    </div>
  );
}
