# Eltern-Portal Parser (epp)

Self-hosted companion for [Eltern-Portal](https://www.eltern-portal.org/) schools. It logs in to your
school's portal, downloads all *Elternbriefe* (parent letters) including their PDFs, and turns them into
something you can actually work with:

- **Markdown archive** of every letter (headline, description, attachments, extracted PDF text), kept on a
  local volume. A SHA-256 of each description detects changed letters and triggers a re-download.
- **Summaries and appointments** extracted by a local LLM via [Ollama](https://ollama.com): the essential
  facts of each letter plus all dates, deadlines and events.
- **Daily summary** with two sections: *today* and *rest of the week*. On Saturday and Sunday it shows
  Monday and the coming week instead.
- **ICS calendar feed** with all extracted appointments, to subscribe to from any calendar app. The URL
  contains a random token that stays stable across restarts.
- **Web app** to browse and search letters, read summaries and configure everything.
- **REST API** (OpenAPI docs at `/docs`) and an **MCP server** (`/mcp`) so AI assistants can query your
  letters.
- **Scheduled updates** via a cron expression (default `30 6,18 * * *`, i.e. 06:30 and 18:30) and an
  optional **webhook** that fires when a new letter appears.

Everything runs in a single Docker container. No data leaves your network except the requests to your
school's portal and to the Ollama host you configure.

> [!CAUTION]
> **Host this on your local network only. Never expose it to the public internet.**
>
> The web app, API, MCP server and ICS feed have **no authentication**. Anyone who can reach the port can:
>
> - read all letters about your children, their classes and school events,
> - use the logged-in portal session (trigger syncs, download attachments),
> - change the settings, including the webhook URL that receives every new letter.
>
> Downloading an attachment counts as **confirming receipt** of the letter in Eltern-Portal
> ("Durch den Download wird der Empfang des Elternbriefes bestätigt"). The app downloads all
> attachments automatically, so letters will show up as received.
>
> If you need access from outside your home (for example, to subscribe to the calendar on your phone),
> use a VPN such as WireGuard or Tailscale. Do not use port forwarding. If you put it behind a reverse
> proxy anyway, the proxy has to enforce authentication (basic auth, SSO). Also keep Ollama itself
> private: it has no authentication either.

## How credentials are handled

Tenant (the school's sub-domain, e.g. `myschool` for `myschool.eltern-portal.org`), username and password
are **not** part of the image, the compose file or any `.env` file. After every start of the container you
enter them once in the web app. They are kept in memory only, so after a restart or reboot the app shows
the login dialog again. Scheduled syncs are skipped until you log in.

## Installation

Requirements: a Linux host (or a Mac with Docker Desktop or Colima) with Docker and the Docker Compose
plugin, and an Ollama instance (see [Ollama setup](#ollama-setup)).

### Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/ralf31337/epp/main/install.sh | bash
```

The script asks for:

| Question | Default |
| --- | --- |
| Installation directory | `/opt/epp` when run as root, otherwise `~/epp` |
| Web app port | `3081` |
| Ollama host and port | `172.17.0.1` and `11434` |
| Public URL behind a reverse proxy | empty (auto-detect) |

It then creates `<dir>/data`, which holds all Markdown files, PDFs and settings. It also writes
`<dir>/.env` and `<dir>/docker-compose.yml`, pulls the image, starts the container and sets the Ollama
endpoint in the app. The container runs as the user who ran the script, so the files in `data/` belong
to you.

Options go after `bash -s --`. With `-y` the script asks nothing and uses the defaults for everything
not given:

```bash
curl -fsSL https://raw.githubusercontent.com/ralf31337/epp/main/install.sh \
  | sudo bash -s -- -y --dir /opt/epp --port 3081 --ollama-host 172.17.0.1 --ollama-port 11434
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-d`, `--dir DIR` | `/opt/epp` (root), `~/epp` | Installation directory |
| `-p`, `--port PORT` | `3081` | Port on the host |
| `--ollama-host HOST` | `172.17.0.1` | Ollama host for PDF parsing and analysis |
| `--ollama-port PORT` | `11434` | Ollama port |
| `--public-url URL` | empty | Public URL behind a reverse proxy |
| `--version X.Y` | `latest` | Version to install (`latest`, `edge`, or for example `0.2`) |
| `--name NAME` | `epp` | Container and Compose project name |
| `--timezone TZ` | `Europe/Berlin` | Time zone |
| `-y`, `--yes` | off | Don't ask, use defaults and given options |

Running the script again updates an existing installation in place and keeps the data. From a clone of
the repository you can also run `./install.sh` directly with the same options.

Manage the service from the installation directory:

```bash
cd ~/epp
docker compose logs -f
docker compose pull && docker compose up -d   # update
docker compose down
```

### Using the repository's compose file

For a quick test you can use the compose file in the repository, which stores the data in a named volume:

```bash
docker compose up -d    # pulls ghcr.io/ralf31337/epp, or builds it locally with --build
```

### First start

1. Open `http://<host>:3081/`.
2. Enter the school sub-domain, your Eltern-Portal email address and password. The first sync starts
   right away. It imports all existing letters without firing the webhook.
3. Open **Settings**:
   - **PDF parsing**: enable it, choose a vision model and the mode. *Auto* uses the PDF's text layer
     and sends only scanned pages to the vision model. *Always* sends every page to it.
   - **Analysis**: enable it and choose a text model for summaries and appointments.
   - **Schedule**: a cron expression, validated with a preview of the next runs.
   - **Webhook**: optional URL, with a test button.
   - **Calendar / MCP**: copy the ICS feed URL and the MCP endpoint.

### Configuration

Deployment settings are environment variables. Everything else is configured in the web app and stored
in `data/config.json`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `EPP_PORT` | `3081` | Host port (compose) |
| `EPP_TIMEZONE` | `Europe/Berlin` | Time zone for schedule, daily summary and calendar |
| `EPP_PUBLIC_URL` | empty | Fixed public URL, e.g. `https://example.org/epp` |
| `EPP_IMAGE` | `ghcr.io/ralf31337/epp` | Image to run |

### Behind a reverse proxy

All links (ICS events, attachment links in Markdown, MCP results, webhook payloads) are built from the URL
the client used. Serving under a sub-path such as `/epp/` works too. The proxy must send
`X-Forwarded-Proto` and `X-Forwarded-Host` (or the standard `Forwarded` header). If it strips a path
prefix, it must also send `X-Forwarded-Prefix`. nginx example:

```nginx
location /epp/ {
    proxy_pass http://127.0.0.1:3081/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /epp;
    auth_basic "epp";                       # see the warning above
    auth_basic_user_file /etc/nginx/epp.htpasswd;
}
```

Set `EPP_PUBLIC_URL` if you want fixed links. Scheduled background jobs, such as the webhook, have no
request to derive the URL from. Without `EPP_PUBLIC_URL` they use the address of the last request the
app received.

## Ollama setup

Ollama is optional. Without it you still get the letters, PDFs and the Markdown archive, but no PDF text
from scanned documents, no summaries, no appointments and therefore an empty calendar.

The app uses two endpoints, which can point to the same or different Ollama servers:

- **PDF parsing** uses a vision model to read scanned PDF pages and images.
- **Analysis** uses a text model to write a German summary, key facts and the appointments as JSON.

### Preconditions

1. **Ollama must be reachable from inside the container.** By default Ollama listens on `127.0.0.1` only,
   which a container cannot reach. Make it listen on the Docker bridge (or all interfaces) on the Linux
   host:

   ```bash
   sudo systemctl edit ollama
   ```

   ```ini
   [Service]
   Environment="OLLAMA_HOST=0.0.0.0:11434"
   ```

   ```bash
   sudo systemctl restart ollama
   ```

   `172.17.0.1` is the host's address on the default Docker bridge (`docker0`), hence the default in
   `install.sh`. If Ollama runs on another machine, use that machine's address instead. On Docker Desktop
   or Colima, use `host.docker.internal`.

2. **The firewall must allow traffic from the Docker networks to port 11434, and nothing else.** Compose
   creates its own bridge network (usually `172.18.0.0/16` or higher), not just `172.17.0.0/16`. Example
   for ufw:

   ```bash
   sudo ufw allow from 172.16.0.0/12 to any port 11434 proto tcp
   ```

   Do not open 11434 to your LAN or the internet unless you mean to. Ollama has no authentication.

3. **Pull suitable models.** These were tested with German school letters:

   ```bash
   ollama pull qwen3-vl     # PDF parsing (vision)
   ollama pull qwen3:30b    # analysis (summary, appointments)
   ```

   - **Vision model:** it must read German text from scans reliably. `llava` hallucinated content in
     tests and is not recommended. Qwen3-VL always "thinks" before answering, which is slow: expect about
     1–3.5 minutes per scanned page on mid-range hardware. In *Auto* mode only pages with less than 200
     characters of embedded text go to the vision model, so most digitally created PDFs never need it.
   - **Text model:** it must produce valid JSON and follow German instructions. Smaller models work but
     miss more appointments and invent times more often. Times that don't appear in the source text are
     discarded anyway.

4. **Size the hardware for the context.** Each request uses `num_ctx` 16384 and up to 8192 output tokens.
   With `qwen3:30b` (about 19 GB at Q4) plus the KV cache, plan for roughly 24 GB of VRAM or unified
   memory; `qwen3-vl` (8B) needs about 8 GB more. If both models don't fit at once, Ollama swaps between
   them. That works, but each switch is slow. Useful server settings:

   - `OLLAMA_MAX_LOADED_MODELS=2` keeps both models loaded if memory allows.
   - `OLLAMA_KEEP_ALIVE=30m` avoids reloading between the steps of one sync.
   - `OLLAMA_NUM_PARALLEL=1` is enough, because the app processes one letter at a time.

   A single request may take up to 15 minutes before the app gives up. Responses cut off at the token
   limit are treated as errors and retried on the next run.

5. **Verify from inside the container:**

   ```bash
   docker exec epp python -c "import urllib.request; print(urllib.request.urlopen('http://172.17.0.1:11434/api/tags').read()[:300])"
   ```

   You can also use **Settings → Test & load models** in the web app. If the model list loads, the
   connection works.

Results are cached: extracted text is keyed by file hash and method, analysis by prompt version, model
and input. Changing a model or mode only reprocesses what is affected. **Reprocess** on a letter forces it.

## API, MCP and webhook

- **REST API:** interactive documentation at `http://<host>:3081/docs`. The main endpoints are:
  - `/api/letters` (`?q=` to search), `/api/letters/{id}`, `/api/letters/{id}/markdown`,
    `/api/letters.md`
  - `/api/daily` and `/api/daily.md`
  - `/api/events?from=&to=`
  - `/api/sync`, `/api/status`
- **MCP:** a Streamable HTTP endpoint at `http://<host>:3081/mcp` with the tools `list_letters`,
  `get_letter`, `search_letters`, `get_daily_summary`, `list_events`, `get_status` and `trigger_sync`.
  It's stateless and only accepts `POST`; a plain `GET` (e.g. opening it in a browser) returns `405`.
  Quick test:

  ```bash
  curl -X POST http://<host>:3081/mcp -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```
- **ICS:** `http://<host>:3081/ics/<token>.ics`. Copy the URL from the web app.
- **Webhook:** a `POST` with JSON `{"event": "letter.created", "sent_at": ..., "data": {...}}`. `data`
  contains the letter's title, date, classes, summary, key facts, events, Markdown and links to the
  letter and its attachments. Failed deliveries are retried on the next sync. The settings page can send
  a `test` event.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
EPP_DATA_DIR=./data .venv/bin/epp serve          # API on :3081
cd web && npm ci && npm run dev                   # web app with proxy to :3081
```

Pushes to `main` build a multi-arch image (`linux/amd64`, `linux/arm64`) and publish it to GHCR via
GitHub Actions (`.github/workflows/docker.yml`).
