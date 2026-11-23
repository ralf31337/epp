import type { CalendarEvent } from "./types";

const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const weekdayFmt = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "2-digit", month: "2-digit" });

/** Parses "YYYY-MM-DD" as a local calendar day. */
export function localDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export const formatDate = (iso: string) => dateFmt.format(localDate(iso));
export const formatDay = (iso: string) => weekdayFmt.format(localDate(iso));
export const formatDateTime = (iso: string | null) => (iso ? dateTimeFmt.format(new Date(iso)) : "–");

export function formatEventWhen(e: CalendarEvent, withDate = true): string {
  let when = withDate ? formatDate(e.date) : "";
  if (e.end_date) when += `${withDate ? " – " : "bis "}${formatDate(e.end_date)}`;
  if (e.start_time) when += `${when ? ", " : ""}${e.start_time}${e.end_time ? `–${e.end_time}` : ""} Uhr`;
  return when || "ganztägig";
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function relative(iso: string | null): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Math.abs(diff) < 60) return "just now";
  const future = diff < 0;
  const abs = Math.abs(diff);
  const text =
    abs < 3600 ? `${Math.round(abs / 60)} min` : abs < 86400 ? `${Math.round(abs / 3600)} h` : `${Math.round(abs / 86400)} d`;
  return future ? `in ${text}` : `${text} ago`;
}
