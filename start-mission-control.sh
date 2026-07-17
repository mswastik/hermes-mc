#!/usr/bin/env bash
# Hermes Mission Control — standalone launcher (no plugin system required).
#
# What it does:
#   1. Ensures the standard Hermes dashboard is running on 127.0.0.1:9119
#      (starts it via `hermes dashboard` if not already up).
#   2. Serves a self-contained mission-control page on a SEPARATE port (9120)
#      that talks to the 9119 dashboard API. It never modifies or relaunches
#      9119 itself — it only reads the dashboard's public root HTML (loopback,
#      no auth) to obtain the ephemeral session token, which it injects into the
#      served page. The token never leaves the machine.
#   3. The actual server (mc_srv.py) is pre-written and NOT regenerated here,
#      so this script can't clobber it.
#
# Usage:
#   ./start-mission-control.sh          # serve on 9120, open browser
#   ./start-mission-control.sh --no-open # serve only (background/dev)

set -euo pipefail

PORT="${MC_PORT:-9120}"
DASH_HOST="${MC_DASH_HOST:-127.0.0.1}"
DASH_PORT="${MC_DASH_PORT:-9119}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_PY="$REPO_DIR/mc_srv.py"
PID_FILE="/tmp/hermes-mc-standalone.pid"
LOG_FILE="/tmp/hermes-mc-standalone.log"
DASH_LOG="/tmp/hermes-dashboard.log"

log() { echo "[mission-control] $*"; }

# ---- 1) ensure the standard dashboard is running on 9119 ----
if curl -s -m 3 -o /dev/null "http://$DASH_HOST:$DASH_PORT/api/status"; then
  log "Dashboard already running at http://$DASH_HOST:$DASH_PORT"
else
  log "Dashboard not reachable — starting it via 'hermes dashboard'…"
  # Launch in the user's environment (not the agent venv) so it uses the
  # same config/auth as a normal 'hermes dashboard' invocation.
  nohup hermes dashboard --port "$DASH_PORT" --no-open >"$DASH_LOG" 2>&1 &
  DASH_PID=$!
  log "  dashboard pid=$DASH_PID (log: $DASH_LOG)"
  # wait for readiness (up to ~25s; first launch may build the web UI)
  ready=0
  for _ in $(seq 1 50); do
    if curl -s -m 1 -o /dev/null "http://$DASH_HOST:$DASH_PORT/api/status"; then
      ready=1; break
    fi
    # if the process died, surface the log
    if ! kill -0 "$DASH_PID" 2>/dev/null; then
      log "  ERROR: dashboard process exited. Last lines of $DASH_LOG:"
      tail -n 15 "$DASH_LOG" >&2 || true
      exit 1
    fi
    sleep 0.5
  done
  if [ "$ready" -eq 1 ]; then
    log "  dashboard is up."
  else
    log "  WARNING: dashboard did not become ready in time. Continuing anyway — check $DASH_LOG."
  fi
fi

# ---- 2) ensure local React UMD is vendored (one-time, cached) ----
VENDOR_DIR="$REPO_DIR/vendor"
mkdir -p "$VENDOR_DIR"
need_vendor=0
[ -f "$VENDOR_DIR/react.production.min.js" ] || need_vendor=1
[ -f "$VENDOR_DIR/react-dom.production.min.js" ] || need_vendor=1
if [ "$need_vendor" -eq 1 ]; then
  log "Vendoring React UMD into $VENDOR_DIR (one-time)…"
  curl -sSL -o "$VENDOR_DIR/react.production.min.js" \
    https://unpkg.com/react@18.3.1/umd/react.production.min.js
  curl -sSL -o "$VENDOR_DIR/react-dom.production.min.js" \
    https://unpkg.com/react@18.3.1/umd/react-dom.production.min.js
fi

# ---- 3) launch the pre-written proxy server (kill any previous instance) ----
if [ -f "$PID_FILE" ]; then
  OLD="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$OLD" ] && kill "$OLD" 2>/dev/null || true
fi
# also kill anything else bound to our port
for p in $(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oP 'pid=\K[0-9]+'); do
  kill -9 "$p" 2>/dev/null || true
done
sleep 0.5

log "Starting standalone server on http://127.0.0.1:$PORT/mission-control …"
MC_PORT="$PORT" nohup python3 "$SERVER_PY" >"$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

# wait for readiness
for _ in $(seq 1 20); do
  if curl -s -m 1 -o /dev/null "http://127.0.0.1:$PORT/mission-control"; then break; fi
  sleep 0.5
done

URL="http://127.0.0.1:$PORT/mission-control"
log "Ready: $URL"

if [ "${1:-}" != "--no-open" ]; then
  (command -v xdg-open >/dev/null && xdg-open "$URL") \
    || (command -v open >/dev/null && open "$URL") \
    || log "Open this in your browser: $URL"
fi
