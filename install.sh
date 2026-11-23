#!/usr/bin/env bash
# Installs the Eltern-Portal parser as a Docker Compose service.
#
#   curl -fsSL https://raw.githubusercontent.com/ralf31337/epp/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/ralf31337/epp/main/install.sh | bash -s -- --dir /opt/epp -y
#
# Portal tenant, username and password are not asked here: enter them in the web app after
# every start (they are kept in memory only).
set -euo pipefail

# Everything runs inside main so bash has read the whole script before anything executes; when piped
# from curl, a command reading stdin would otherwise swallow the rest of the script.
main() {
if [[ "$(id -u)" == 0 ]]; then DIR="/opt/epp"; else DIR="${HOME}/epp"; fi
PORT="3081"
IMAGE="ghcr.io/ralf31337/epp"
VERSION="latest"
NAME="epp"
OLLAMA_HOST="172.17.0.1"
OLLAMA_PORT="11434"
PUBLIC_URL=""
TIMEZONE="Europe/Berlin"
ASSUME_YES=0
GIVEN=" "

usage() {
  cat <<EOF
Usage: install.sh [options]
       curl -fsSL https://raw.githubusercontent.com/ralf31337/epp/main/install.sh | bash -s -- [options]

  -d, --dir DIR          Installation directory (default: ${DIR})
  -p, --port PORT        Host port of the web app (default: ${PORT})
      --ollama-host HOST Ollama host for PDF parsing and analysis (default: ${OLLAMA_HOST})
      --ollama-port PORT Ollama port (default: ${OLLAMA_PORT})
      --public-url URL   Public URL behind a reverse proxy, e.g. https://example.org/epp (optional)
      --version X.Y      Version to install: latest, edge or e.g. 0.2 (default: ${VERSION})
      --image IMAGE      Docker image without tag (default: ${IMAGE})
      --name NAME        Container name (default: ${NAME})
      --timezone TZ      Time zone for schedule and calendar (default: ${TIMEZONE})
  -y, --yes              Do not ask, use defaults and given options
  -h, --help             Show this help
EOF
}

die() { echo "Error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dir) DIR="${2:?}"; GIVEN+="dir "; shift 2 ;;
    -p|--port) PORT="${2:?}"; GIVEN+="port "; shift 2 ;;
    --ollama-host) OLLAMA_HOST="${2:?}"; GIVEN+="ollama-host "; shift 2 ;;
    --ollama-port) OLLAMA_PORT="${2:?}"; GIVEN+="ollama-port "; shift 2 ;;
    --public-url) PUBLIC_URL="${2?}"; GIVEN+="public-url "; shift 2 ;;
    --version) VERSION="${2:?}"; shift 2 ;;
    --image) IMAGE="${2:?}"; shift 2 ;;
    --name) NAME="${2:?}"; shift 2 ;;
    --timezone) TIMEZONE="${2:?}"; shift 2 ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

# ask KEY "Question" VARIABLE: prompts unless the option was given or --yes is set.
ask() {
  local key="$1" question="$2" var="$3" answer
  [[ "$GIVEN" == *" $key "* || "$ASSUME_YES" == 1 ]] && return 0
  [[ -r /dev/tty ]] || return 0
  read -r -p "$question [${!var}]: " answer </dev/tty || true
  [[ -n "$answer" ]] && printf -v "$var" '%s' "$answer"
  return 0
}

valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )); }

# Prerequisites
command -v docker >/dev/null || die "docker is not installed"
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null; then
  COMPOSE=(docker-compose)
else
  die "docker compose is not installed"
fi
docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon (is it running, do you have permission?)"

# Questions
ask dir "Installation directory" DIR
ask port "Web app port" PORT
until valid_port "$PORT"; do
  [[ "$ASSUME_YES" == 1 || ! -r /dev/tty ]] && die "invalid port: $PORT"
  echo "Please enter a port between 1 and 65535."
  read -r -p "Web app port [3081]: " PORT </dev/tty || true
  PORT="${PORT:-3081}"
done

ask ollama-host "Ollama host" OLLAMA_HOST
until [[ -n "$OLLAMA_HOST" && "$OLLAMA_HOST" != *[[:space:]]* ]]; do
  [[ "$ASSUME_YES" == 1 || ! -r /dev/tty ]] && die "invalid Ollama host: '$OLLAMA_HOST'"
  read -r -p "Ollama host [172.17.0.1]: " OLLAMA_HOST </dev/tty || true
  OLLAMA_HOST="${OLLAMA_HOST:-172.17.0.1}"
done
OLLAMA_HOST="${OLLAMA_HOST%/}"

ask ollama-port "Ollama port" OLLAMA_PORT
until valid_port "$OLLAMA_PORT"; do
  [[ "$ASSUME_YES" == 1 || ! -r /dev/tty ]] && die "invalid Ollama port: $OLLAMA_PORT"
  read -r -p "Ollama port [11434]: " OLLAMA_PORT </dev/tty || true
  OLLAMA_PORT="${OLLAMA_PORT:-11434}"
done

ask public-url "Public URL behind a reverse proxy (empty = detect from proxy headers)" PUBLIC_URL
PUBLIC_URL="${PUBLIC_URL%/}"
[[ -z "$PUBLIC_URL" || "$PUBLIC_URL" =~ ^https?://[^[:space:]]+$ ]] || die "public URL must start with http:// or https://"

[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid version: $VERSION"
IMAGE="$IMAGE:$VERSION"
[[ "$NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "container name must be lowercase letters, digits, '-' or '_'"

# The container runs as the owner of the data directory.
if [[ "$(id -u)" == 0 && -n "${SUDO_UID:-}" ]]; then
  RUN_UID="$SUDO_UID"; RUN_GID="$SUDO_GID"
else
  RUN_UID="$(id -u)"; RUN_GID="$(id -g)"
fi

mkdir -p "$DIR/data"
DIR="$(cd "$DIR" && pwd)"

# Refuse to take over a container of the same name that belongs to another installation.
if owner="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$NAME" 2>/dev/null)"; then
  [[ "$owner" == "$DIR" ]] || die "a container named '$NAME' already exists (${owner:-not managed by compose}); choose another --name or remove it"
fi
[[ "$(id -u)" == 0 ]] && chown "$RUN_UID:$RUN_GID" "$DIR/data"
[[ -w "$DIR/data" ]] || die "$DIR/data is not writable"

info "Writing $DIR/.env and $DIR/docker-compose.yml"
cat >"$DIR/.env" <<EOF
# Generated by install.sh – re-run it to change these values.
COMPOSE_PROJECT_NAME=$NAME
EPP_IMAGE=$IMAGE
EPP_CONTAINER_NAME=$NAME
EPP_PORT=$PORT
EPP_UID=$RUN_UID
EPP_GID=$RUN_GID
EPP_TIMEZONE=$TIMEZONE
EPP_PUBLIC_URL=$PUBLIC_URL
EOF

cat >"$DIR/docker-compose.yml" <<'EOF'
# Generated by install.sh. Portal credentials are entered in the web app after each start.
services:
  epp:
    image: ${EPP_IMAGE}
    container_name: ${EPP_CONTAINER_NAME}
    restart: unless-stopped
    user: "${EPP_UID}:${EPP_GID}"
    environment:
      EPP_TIMEZONE: ${EPP_TIMEZONE}
      EPP_PUBLIC_URL: ${EPP_PUBLIC_URL}
    ports:
      - "${EPP_PORT}:3081"
    volumes:
      - ./data:/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF

cd "$DIR"
info "Pulling $IMAGE"
if ! "${COMPOSE[@]}" pull --quiet 2>/dev/null; then
  docker image inspect "$IMAGE" >/dev/null 2>&1 || die "could not pull $IMAGE and it is not available locally"
  echo "    Pull failed, using the local image."
fi

info "Starting container $NAME"
"${COMPOSE[@]}" up -d

info "Waiting for the app to become healthy"
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$NAME" 2>/dev/null || true)"
  [[ "$status" == healthy ]] && break
  sleep 2
done
[[ "$status" == healthy ]] || die "container did not become healthy, see: ${COMPOSE[*]} -f $DIR/docker-compose.yml logs"

info "Setting Ollama endpoint to $OLLAMA_HOST:$OLLAMA_PORT"
docker exec -i -e OLLAMA_HOST="$OLLAMA_HOST" -e OLLAMA_PORT="$OLLAMA_PORT" "$NAME" python - <<'EOF'
import json, os, urllib.request

base = "http://127.0.0.1:3081/api"
config = json.load(urllib.request.urlopen(f"{base}/config"))
config.pop("ics_token", None)
for key in ("pdf_ollama", "context_ollama"):
    config[key]["host"] = os.environ["OLLAMA_HOST"]
    config[key]["port"] = int(os.environ["OLLAMA_PORT"])
req = urllib.request.Request(f"{base}/config", data=json.dumps(config).encode(), method="PUT",
                             headers={"Content-Type": "application/json"})
urllib.request.urlopen(req)
try:
    models = json.load(urllib.request.urlopen(
        f"{base}/ollama/models?host={os.environ['OLLAMA_HOST']}&port={os.environ['OLLAMA_PORT']}"))["models"]
    print(f"    Ollama reachable, {len(models)} model(s): {', '.join(models[:8])}")
except Exception as e:
    print(f"    Warning: Ollama not reachable from the container yet ({e})")
EOF

HOST_ADDR="$( (hostname -I 2>/dev/null || true) | awk '{print $1}')"
URL="${PUBLIC_URL:-http://${HOST_ADDR:-$(hostname)}:$PORT}"
cat <<EOF

Done. The Eltern-Portal parser is running.

  Web app:     $URL/
  Data:        $DIR/data
  Manage:      cd $DIR && ${COMPOSE[*]} logs -f | restart | down

Next steps:
  1. Open the web app and enter school (tenant), email and password. They are kept in
     memory only, so enter them again after every restart of the container.
  2. In Settings, enable PDF parsing and analysis and choose the Ollama models.
EOF
}

main "$@"
