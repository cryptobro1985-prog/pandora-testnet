"""Research-only strict provenance gate. No live orders; no claims of verified liquidation.
Run: python research/hype_terminal_local_strategy/strict_execution_provenance_research.py
"""
import hashlib
import json
from pathlib import Path
from trade_manifest_gate_research import gate

REQUIRED = ("entry_fill_source", "exit_fill_source", "mark_path_source",
            "l50_path_source", "public_trades_source", "event_sequence_source",
            "protective_stop_order_source")
def strict_gate(row, root):
    base = gate(row)
    if base["status"] != "EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED":
        return base
    required = REQUIRED + (("stop_fill_source",) if row["exit_reason"] == "STOP" else ())
    evidence = row.get("evidence", {})
    if not isinstance(evidence, dict):
        return {"status": "UNKNOWN_EVIDENCE_MANIFEST"}
    for field in required:
        record = evidence.get(field)
        if not isinstance(record, dict):
            return {"status": "UNKNOWN_EVIDENCE_MISSING", "field": field}
        path, digest = record.get("path"), record.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str) or len(digest) != 64:
            return {"status": "UNKNOWN_EVIDENCE_INVALID", "field": field}
        base_dir = Path(root).resolve()
        file_path = (base_dir / path).resolve()
        if not file_path.is_relative_to(base_dir) or not file_path.is_file():
            return {"status": "UNKNOWN_EVIDENCE_UNAVAILABLE", "field": field}
        h = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != digest.lower():
            return {"status": "UNKNOWN_EVIDENCE_HASH_MISMATCH", "field": field}
        start, end = record.get("start_ts_ms"), record.get("end_ts_ms")
        if type(start) is not int or type(end) is not int or start > row["entry_fill_ts_ms"] or end < row["exit_ts_ms"]:
            return {"status": "UNKNOWN_EVIDENCE_TIME_COVERAGE", "field": field}
    ack = row.get("stop_order_accepted_ts_ms")
    if type(ack) is not int or not (row["entry_fill_ts_ms"] <= ack < row["exit_ts_ms"]):
        return {"status": "UNKNOWN_STOP_ACK"}
    if row["exit_reason"] == "STOP" and ack >= row["stop_trigger_ts_ms"]:
        return {"status": "UNKNOWN_STOP_NOT_ACCEPTED_BEFORE_TRIGGER"}
    if row["exit_reason"] == "OPPOSITE_LOCAL":
        if row.get("opposite_local_type") != ("HIGH" if row["side"] == "LONG" else "LOW"):
            return {"status": "UNKNOWN_OPPOSITE_LOCAL_TYPE"}
        if not row.get("first_causally_available_opposite_local_verified", False):
            return {"status": "UNKNOWN_FIRST_OPPOSITE_LOCAL"}
    if row.get("execution_kind") not in ("HISTORICAL_SIMULATED", "PRIVATE_EXCHANGE_FILL"):
        return {"status": "UNKNOWN_EXECUTION_KIND"}
    return {"status": "EVIDENCE_FILES_HASHED_NOT_EXECUTION_OR_LIQUIDATION_VERIFIED",
            "execution_kind": row["execution_kind"],
            "scenario_net_pnl_quote": base["observed_net_pnl_quote"]}

def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "tape.txt"
        p.write_text("test", encoding="utf-8")
        record = {"path": "tape.txt", "sha256": hashlib.sha256(b"test").hexdigest(),
                  "start_ts_ms": 0, "end_ts_ms": 100}
        row = dict(trade_id="T1", side="LONG", local_type="LOW",
                   local_ts_ms=10, signal_available_ts_ms=20, order_submit_ts_ms=21,
                   entry_fill_ts_ms=22, entry_fill_price=100, entry_fill_source="placeholder",
                   entry_notional=100, stop_price=99, exit_reason="STOP",
                   stop_trigger_ts_ms=30, stop_fill_ts_ms=31, stop_fill_price=98.8,
                   stop_fill_source="placeholder", exit_ts_ms=31, exit_fill_price=98.8,
                   exit_fill_source="placeholder", fees_paid=.15, funding_paid=0,
                   mark_path_source="placeholder", l50_path_source="placeholder",
                   public_trades_source="placeholder", event_sequence_source="placeholder",
                   coverage_complete=True, protective_stop_order_source="placeholder",
                   stop_order_accepted_ts_ms=25, execution_kind="HISTORICAL_SIMULATED")
        assert gate(row)["status"] == "EXECUTION_FIELDS_COMPLETE_NOT_LIQUIDATION_VERIFIED"
        assert strict_gate(row, tmp)["status"] == "UNKNOWN_EVIDENCE_MISSING"
        row["evidence"] = {key: dict(record) for key in REQUIRED + ("stop_fill_source",)}
        assert strict_gate(row, tmp)["status"] == "EVIDENCE_FILES_HASHED_NOT_EXECUTION_OR_LIQUIDATION_VERIFIED"
        row["evidence"]["mark_path_source"]["sha256"] = "0" * 64
        assert strict_gate(row, tmp)["status"] == "UNKNOWN_EVIDENCE_HASH_MISMATCH"
        row["evidence"]["mark_path_source"]["sha256"] = record["sha256"]
        row["stop_order_accepted_ts_ms"] = 30
        assert strict_gate(row, tmp)["status"] == "UNKNOWN_STOP_NOT_ACCEPTED_BEFORE_TRIGGER"
    return "4 provenance assertions passed"
if __name__ == "__main__":
    print(self_test())
