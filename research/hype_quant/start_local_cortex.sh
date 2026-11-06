#!/usr/bin/env bash
set -euo pipefail

PORT="${CORTEX_PORT:-8081}"
CTX="${CORTEX_CTX_SIZE:-4096}"
THREADS="${CORTEX_THREADS:-4}"
LOG="${CORTEX_LOG:-/tmp/cortex20b.log}"
PIDFILE="${CORTEX_PIDFILE:-/tmp/cortex20b.pid}"
MODEL="${CORTEX_HF_MODEL:-ggml-org/gpt-oss-20b-GGUF:MXFP4}"

echo "CORTEX20B: reclaiming runner disk"
sudo rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc /usr/local/.ghcup 2>/dev/null || true
sudo apt-get clean || true
rm -rf "$HOME/.cache/pip" 2>/dev/null || true
df -h / || true

if ! command -v llama >/dev/null 2>&1; then
  echo "CORTEX20B: installing llama.cpp launcher"
  curl -LsSf https://llama.app/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v llama
llama --version || true

echo "CORTEX20B: starting $MODEL on 127.0.0.1:$PORT"
export HF_HOME="${HF_HOME:-$RUNNER_TEMP/hf-cortex}"
mkdir -p "$HF_HOME"
nohup llama serve -hf "$MODEL" --host 127.0.0.1 --port "$PORT" -c "$CTX" -t "$THREADS" >"$LOG" 2>&1 &
echo $! > "$PIDFILE"

for i in $(seq 1 240); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/tmp/cortex-health.json 2>/dev/null; then
    echo "CORTEX20B_READY attempt=$i"
    cat /tmp/cortex-health.json || true
    df -h / || true
    exit 0
  fi
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "CORTEX20B_PROCESS_EXITED"
    tail -n 200 "$LOG" || true
    exit 1
  fi
  if (( i % 12 == 0 )); then
    echo "CORTEX20B_WAIT attempt=$i"
    tail -n 20 "$LOG" || true
    df -h / || true
  fi
  sleep 5
done

echo "CORTEX20B_TIMEOUT"
tail -n 250 "$LOG" || true
exit 1
