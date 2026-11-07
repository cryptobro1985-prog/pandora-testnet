#!/usr/bin/env bash
# Optional local research service. Never installs software or reclaims disk.
# CORTEX_HF_MODEL explicitly opts in to the selected launcher's download.
set -euo pipefail

fail() { echo "CORTEX_START_ERROR: $1" >&2; exit 2; }
PORT="${CORTEX_PORT:-8081}"
CTX="${CORTEX_CTX_SIZE:-4096}"
THREADS="${CORTEX_THREADS:-4}"
READY_TIMEOUT="${CORTEX_READY_TIMEOUT_SECONDS:-120}"
TASK_TEMP="${RUNNER_TEMP:-/tmp}"
LOG="${CORTEX_LOG:-$TASK_TEMP/cortex20b.log}"
PIDFILE="${CORTEX_PIDFILE:-$TASK_TEMP/cortex20b.pid}"
MODEL_PATH="${CORTEX_MODEL_PATH:-}"
HF_MODEL="${CORTEX_HF_MODEL:-}"

bounded_integer() {
  local value="$2" decimal
  [[ "$value" =~ ^[0-9]{1,6}$ ]] || fail "invalid_$1"
  decimal=$((10#$value))
  (( decimal >= $3 && decimal <= $4 )) || fail "invalid_$1"
  printf -v "$1" '%d' "$decimal"
}
bounded_integer PORT "$PORT" 1 65535
bounded_integer CTX "$CTX" 128 131072
bounded_integer THREADS "$THREADS" 1 256
bounded_integer READY_TIMEOUT "$READY_TIMEOUT" 1 600
[[ -z "$MODEL_PATH" || -z "$HF_MODEL" ]] || fail "choose_model_path_or_hf_model"
[[ -n "$MODEL_PATH" || -n "$HF_MODEL" ]] || fail "set_CORTEX_MODEL_PATH_or_explicit_CORTEX_HF_MODEL"
if [[ -n "$MODEL_PATH" ]]; then
  [[ -f "$MODEL_PATH" && -r "$MODEL_PATH" ]] || fail "local_model_missing_or_unreadable"
  model_args=(-m "$MODEL_PATH")
else
  model_args=(-hf "$HF_MODEL")
fi

if [[ -n "${CORTEX_LLAMA_BIN:-}" ]]; then
  LLAMA_BIN="$(command -v "$CORTEX_LLAMA_BIN" 2>/dev/null)" || fail "configured_llama_binary_missing"
elif command -v llama-server >/dev/null 2>&1; then
  LLAMA_BIN="$(command -v llama-server)"
elif command -v llama >/dev/null 2>&1; then
  LLAMA_BIN="$(command -v llama)"
else
  fail "install_llama_server_separately"
fi
[[ -x "$LLAMA_BIN" ]] || fail "llama_binary_not_executable"
launcher_args=()
if [[ "$(basename "$LLAMA_BIN")" == "llama" ]]; then launcher_args=(serve); fi
command -v curl >/dev/null 2>&1 || fail "curl_required_for_health_probe"
command -v flock >/dev/null 2>&1 || fail "flock_required_for_single_writer"
mkdir -p "$(dirname "$LOG")" "$(dirname "$PIDFILE")"
exec 9>"$PIDFILE.lock"
flock -n 9 || fail "another_launcher_holds_lock"
if [[ -f "$PIDFILE" ]]; then
  read -r prior_pid < "$PIDFILE" || true
  if [[ "${prior_pid:-}" =~ ^[0-9]+$ ]] && kill -0 "$prior_pid" 2>/dev/null; then
    fail "existing_cortex_process_alive"
  fi
fi

if [[ -n "$HF_MODEL" ]]; then
  export HF_HOME="${HF_HOME:-$TASK_TEMP/hf-cortex}"
  mkdir -p "$HF_HOME"
  echo "CORTEX_START: explicit_HF_download_enabled"
fi
child_pid=""
ready=0
cleanup() {
  if [[ "$ready" == 0 && -n "$child_pid" ]]; then
    kill "$child_pid" 2>/dev/null || true
    # Bound cleanup even if the model server ignores SIGTERM.
    sleep 0.1
    kill -KILL "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
    if [[ -f "$PIDFILE" ]] && [[ "$(cat "$PIDFILE")" == "$child_pid" ]]; then rm -f "$PIDFILE"; fi
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
nohup "$LLAMA_BIN" "${launcher_args[@]}" "${model_args[@]}" --host 127.0.0.1 --port "$PORT" \
  -c "$CTX" -t "$THREADS" >"$LOG" 2>&1 &
child_pid=$!
printf '%s\n' "$child_pid" > "$PIDFILE"
deadline=$((SECONDS + READY_TIMEOUT))
while (( SECONDS < deadline )); do
  if ! kill -0 "$child_pid" 2>/dev/null; then
    echo "CORTEX_START_ERROR: process_exited; inspect $LOG" >&2
    exit 1
  fi
  if curl --noproxy '*' --connect-timeout 1 --max-time 2 -fsS \
      "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ready=1
    echo "CORTEX_READY: pid=$child_pid host=127.0.0.1 port=$PORT"
    exit 0
  fi
  sleep 1
done
echo "CORTEX_START_ERROR: health_timeout; inspect $LOG" >&2
exit 1
