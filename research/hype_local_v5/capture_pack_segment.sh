#!/usr/bin/env bash
set -u -o pipefail

RAW="$1"
MINUTES="$2"
COMPACT="${RAW}_compact"
UPLOAD="${RAW}_upload"
rm -rf "$RAW" "$COMPACT" "$UPLOAD"
mkdir -p "$RAW" "$UPLOAD"

CQ_PID=""
CQ_RC=0
CQ_DIR="$UPLOAD/caterpillar_quant"
if [ "${CATERPILLAR_QUANT_ENABLED:-0}" = "1" ]; then
  mkdir -p "$CQ_DIR"
  if [ -n "${CATERPILLAR_WARMSTART_DIR:-}" ] && [ -d "${CATERPILLAR_WARMSTART_DIR}" ]; then
    cp -a "${CATERPILLAR_WARMSTART_DIR}"/. "$CQ_DIR"/ || true
  fi
  python -m research.hype_caterpillar_quant.live_daemon     --capture-root "$RAW" --checkpoint-dir "$CQ_DIR" --minutes "$MINUTES" &
  CQ_PID=$!
fi

set +e
python research/hype_local_v5/resilient_capture.py --minutes "$MINUTES" --chunk-minutes 20 --output "$RAW"
CAPTURE_RC=$?
if [ -n "$CQ_PID" ]; then
  if [ "$CAPTURE_RC" -ne 0 ]; then
    kill "$CQ_PID" 2>/dev/null || true
  fi
  wait "$CQ_PID"
  CQ_RC=$?
fi
python research/hype_local_v5/aggregate_forward.py --root "$RAW" --output "$RAW/AGGREGATE_SEGMENT.json"
AGG_RC=$?
python research/hype_local_v5/compact_pack.py --input "$RAW" --output "$COMPACT"
PACK_RC=$?
set -e

printf '{"capture_rc":%s,"caterpillar_quant_rc":%s,"aggregate_rc":%s,"pack_rc":%s}
'   "$CAPTURE_RC" "$CQ_RC" "$AGG_RC" "$PACK_RC" > "$UPLOAD/CATERPILLAR_STATUS.json"

if [ "$PACK_RC" -eq 0 ]; then
  cp research/hype_local_v5/decode_compact.py "$COMPACT/decode_compact.py"
  python "$COMPACT/decode_compact.py" "$COMPACT" --verify
  python - "$COMPACT" "$CAPTURE_RC" "$AGG_RC" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
m=json.loads((root/"PACK_MANIFEST.json").read_text())
m["capture_exit_code"]=int(sys.argv[2])
m["aggregate_exit_code"]=int(sys.argv[3])
m["storage_target_note"]="Measured 20m reference compressed to ~5.2% of JSONL; 12h target is <100 MB, activity dependent."
(root/"PACK_MANIFEST.json").write_text(json.dumps(m,indent=2)+"\n")
PY
  cp -a "$COMPACT"/. "$UPLOAD"/
  rm -rf "$RAW" "$COMPACT"
  echo "compact" > "$UPLOAD/PACK_MODE.txt"
else
  echo "Compact pack failed rc=$PACK_RC; preserving emergency raw capture." >&2
  tar -cJf "$UPLOAD/EMERGENCY_RAW.tar.xz" -C "$RAW" .
  printf '{"compact_pack_rc":%s,"capture_rc":%s,"aggregate_rc":%s}\n' "$PACK_RC" "$CAPTURE_RC" "$AGG_RC" > "$UPLOAD/PACK_FAILURE.json"
  cp research/hype_local_v5/decode_compact.py "$UPLOAD/decode_compact.py"
  echo "emergency_raw_xz" > "$UPLOAD/PACK_MODE.txt"
  rm -rf "$RAW" "$COMPACT"
fi
