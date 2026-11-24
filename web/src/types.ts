export interface Attachment {
  repo: string;
  name: string;
  file: string;
  size: number;
  sha256: string;
  text_file: string | null;
  text_method: string | null;
  text_error: string | null;
}

export interface CalendarEvent {
  title: string;
  date: string;
  end_date: string | null;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  details: string | null;
}

export interface Analysis {
  summary: string;
  key_facts: string[];
  events: CalendarEvent[];
  model: string;
  analyzed_at: string;
}

export interface Letter {
  id: string;
  kind: "letter" | "notice";
  number: number;
  label: string;
  title: string;
  published_at: string | null;
  classes: string[];
  acknowledged: boolean;
  description_md: string;
  description_sha256: string;
  attachments: Attachment[];
  first_seen_at: string;
  updated_at: string;
  removed: boolean;
  analysis: Analysis | null;
  analysis_error: string | null;
}

export interface SyncResult {
  new: string[];
  updated: string[];
  unchanged: string[];
  removed: string[];
  downloaded_files: number;
  extracted_files: number;
  analyzed_letters: number;
  webhooks_sent: number;
  errors: string[];
  finished_at: string;
}

export interface Status {
  credentials: { configured: boolean; tenant: string | null; username: string | null };
  job: {
    running: boolean;
    kind: string | null;
    phase: string | null;
    finished_at: string | null;
    last_result: SyncResult | null;
    last_error: string | null;
  };
  last_sync_at: string | null;
  letters: number;
  notices: number;
  portal_calendar: { available: boolean; events: number; fetched_at: string | null; error: string | null };
  analysed: number;
  schedule_cron: string;
  next_run: string | null;
  scheduler_note: string | null;
  pdf_ollama: boolean;
  context_ollama: boolean;
}

export interface OllamaEndpoint {
  enabled: boolean;
  host: string;
  port: number;
  model: string;
  mode: "auto" | "always";
}

export interface AppConfig {
  schedule_cron: string;
  webhook_url: string | null;
  pdf_ollama: OllamaEndpoint;
  context_ollama: OllamaEndpoint;
  ics_token: string;
}

export interface LetterEvent {
  uid: string;
  letter_id: string | null;
  letter_number: number | null;
  letter_label: string;
  letter_title: string;
  url: string | null;
  event: CalendarEvent;
  also_in: string[];
}

export interface DailyDay {
  date: string;
  weekday: string;
  events: LetterEvent[];
}

export interface DailySummary {
  focus_label: string;
  focus: DailyDay;
  rest_label: string;
  rest_start: string | null;
  rest_end: string | null;
  rest: DailyDay[];
  next_label: string;
  next_start: string;
  next_end: string;
  next: DailyDay[];
}
