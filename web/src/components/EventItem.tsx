import { formatEventWhen } from "../format";
import type { CalendarEvent } from "../types";

interface Props {
  event: CalendarEvent;
  withDate?: boolean;
  source?: string;
  onClick?: () => void;
}

export function EventItem({ event, withDate = true, source, onClick }: Props) {
  const deadline = event.title.toLowerCase().startsWith("frist");
  return (
    <li
      className={`event ${deadline ? "deadline" : ""} ${onClick ? "clickable" : ""}`}
      onClick={onClick}
      title={onClick ? "Open letter" : undefined}
    >
      <span className="event-when">{formatEventWhen(event, withDate)}</span>
      <span className="event-body">
        <span className="event-title">{event.title}</span>
        {(event.location || event.details) && (
          <span className="event-sub">{[event.location, event.details].filter(Boolean).join(" · ")}</span>
        )}
        {source && <span className="event-sub">{source}</span>}
      </span>
    </li>
  );
}
