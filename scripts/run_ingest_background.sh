#!/usr/bin/env bash
# Run hospitality (or any) ingest detached from SSH — survives disconnect.
#
# Usage:
#   ./scripts/run_ingest_background.sh start
#   ./scripts/run_ingest_background.sh status
#   ./scripts/run_ingest_background.sh logs      # tail application log
#   ./scripts/run_ingest_background.sh progress  # where ingest left off
#   ./scripts/run_ingest_background.sh stop
#
# Resume: each completed part file is recorded in run/ingest_checkpoint.json
#   INGEST_BOOTSTRAP_CHECKPOINT=true  — one-time seed from logs/ingest.log
#
# Logs:
#   logs/ingest.log         — structured progress (from ingest.py)
#   logs/ingest_stdout.log  — raw stdout/stderr (crashes, tracebacks)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="${INGEST_PID_FILE:-run/ingest.pid}"
STDOUT_LOG="${INGEST_STDOUT_LOG:-logs/ingest_stdout.log}"
APP_LOG="${INGEST_LOG_PATH:-logs/ingest.log}"
CHECKPOINT="${INGEST_CHECKPOINT_PATH:-run/ingest_checkpoint.json}"
PYTHON="${INGEST_PYTHON:-$ROOT/venv/bin/python}"
INGEST_SCRIPT="${INGEST_SCRIPT:-$ROOT/src/data/ingest.py}"

mkdir -p logs run

_is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null
}

_cmd_start() {
  if _is_running; then
    echo "Ingest already running (PID $(cat "$PID_FILE"))."
    echo "  tail -f $APP_LOG"
    exit 1
  fi
  if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python not found: $PYTHON"
    exit 1
  fi
  if [[ ! -f "$INGEST_SCRIPT" ]]; then
    echo "ERROR: Ingest script not found: $INGEST_SCRIPT"
    exit 1
  fi

  export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-}"
  {
    echo "======== ingest background start $(date -Iseconds) ========"
    echo "cwd=$ROOT"
    echo "python=$PYTHON"
  } >>"$STDOUT_LOG"

  # nohup: ignore SIGHUP when SSH session closes
  nohup "$PYTHON" "$INGEST_SCRIPT" >>"$STDOUT_LOG" 2>&1 &
  echo $! >"$PID_FILE"

  sleep 1
  if ! _is_running; then
    echo "ERROR: ingest exited immediately. Check $STDOUT_LOG"
    rm -f "$PID_FILE"
    exit 1
  fi

  echo "Ingest started in background."
  echo "  PID:      $(cat "$PID_FILE")"
    echo "  Progress:   $APP_LOG"
    echo "  Raw log:    $STDOUT_LOG"
    echo "  Checkpoint: $CHECKPOINT"
  echo ""
  echo "  tail -f $APP_LOG"
  echo "  ./scripts/run_ingest_background.sh status"
}

_cmd_stop() {
  if ! _is_running; then
    echo "Ingest is not running."
    rm -f "$PID_FILE"
    exit 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  echo "Stopping ingest (PID $pid)..."
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Stopped."
      return 0
    fi
    sleep 2
  done
  echo "Still running; sending SIGKILL..."
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Stopped (SIGKILL)."
}

_checkpoint_summary() {
  if [[ ! -f "$CHECKPOINT" ]]; then
    echo "  Checkpoint: (none yet)"
    return
  fi
  if command -v jq >/dev/null 2>&1; then
    local n chunks
    n="$(jq '.completed_files | length' "$CHECKPOINT" 2>/dev/null || echo "?")"
    chunks="$(jq '.chunks_indexed' "$CHECKPOINT" 2>/dev/null || echo "?")"
    echo "  Checkpoint: $n file(s) done, $chunks chunks recorded"
  else
    echo "  Checkpoint: $CHECKPOINT ($(wc -l <"$CHECKPOINT" 2>/dev/null || echo 0) lines)"
  fi
}

_cmd_status() {
  if _is_running; then
    local pid elapsed
    pid="$(cat "$PID_FILE")"
    elapsed="$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ' || echo "?")"
    echo "RUNNING  PID=$pid  elapsed=$elapsed"
    echo "  $APP_LOG"
    echo "  $STDOUT_LOG"
    _checkpoint_summary
    if [[ -f "$APP_LOG" ]]; then
      echo ""
      echo "Last 5 lines of $APP_LOG:"
      tail -n 5 "$APP_LOG" | sed 's/^/  /'
    fi
  else
    echo "NOT RUNNING"
    rm -f "$PID_FILE" 2>/dev/null || true
    _checkpoint_summary
    if [[ -f "$APP_LOG" ]]; then
      echo ""
      echo "Last 5 lines of $APP_LOG:"
      tail -n 5 "$APP_LOG" | sed 's/^/  /'
    fi
    exit 1
  fi
}

_cmd_logs() {
  if [[ ! -f "$APP_LOG" ]]; then
    echo "No log yet: $APP_LOG (start ingest first)"
    exit 1
  fi
  tail -f "$APP_LOG"
}

_cmd_restart() {
  _cmd_stop || true
  sleep 2
  _cmd_start
}

_cmd_progress() {
  echo "=== Ingest progress ==="
  _checkpoint_summary
  if [[ -f "$CHECKPOINT" ]] && command -v jq >/dev/null 2>&1; then
    echo ""
    echo "Last success:"
    jq -r '"  month=\(.last_month) blob=\(.last_blob) updated=\(.updated_at)"' "$CHECKPOINT" 2>/dev/null || true
  fi
  if [[ -f "$APP_LOG" ]]; then
    echo ""
    echo "Last month header:"
    grep "=== Month " "$APP_LOG" 2>/dev/null | tail -1 | sed 's/^/  /' || true
    echo "Last DONE line:"
    grep "DONE " "$APP_LOG" 2>/dev/null | tail -1 | sed 's/^/  /' || true
    echo "Last COMPLETE:"
    grep "COMPLETE" "$APP_LOG" 2>/dev/null | tail -1 | sed 's/^/  /' || true
    echo "Last ERROR:"
    grep "ERROR Ingest failed" "$APP_LOG" 2>/dev/null | tail -1 | sed 's/^/  /' || true
  fi
}

usage() {
  echo "Usage: $0 {start|stop|status|logs|progress|restart}"
}

case "${1:-}" in
  start) _cmd_start ;;
  stop) _cmd_stop ;;
  status) _cmd_status ;;
  logs) _cmd_logs ;;
  progress) _cmd_progress ;;
  restart) _cmd_restart ;;
  *) usage; exit 1 ;;
esac
