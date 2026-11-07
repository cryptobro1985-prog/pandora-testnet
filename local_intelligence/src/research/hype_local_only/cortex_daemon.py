#!/usr/bin/env python3
"""Independent advisory process: an LLM failure cannot block Quantum inference."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import time
from .cortex_meta import (StatisticalCortex, atomic_json, canonical, clean_features,
                          load_memory, save_memory, VERSION)
from .cortex_provider import AdapterConfig, CortexProvider
from .jepa_research import causal_cortex_evidence

def acquire_owner(directory: Path):
    handle = (directory / "cortex_daemon.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("cortex_daemon_already_running") from None
    return handle

def json_object(text):
    """Compatibility helper; partial objects and reasoning text are rejected."""
    obj = json.loads(str(text))
    if not isinstance(obj, dict):
        raise ValueError("cortex_response_not_object")
    return obj

def compact_memory(memory, side):
    """Archive associations are descriptive and never validation proof."""
    return {"provenance": "archive_descriptive_only_not_oos_validated", "micro": {
        f"{side}_{stage}s": {
            "top_feature_relationships": ((memory.get("heads") or {}).get(f"{side}_{stage}s") or {}).get("top_feature_relationships", [])[:8]
        } for stage in (60, 180, 300)}}

def call_cortex(url, model, payload, timeout):
    config = AdapterConfig.from_env({"CORTEX_BACKEND": "local_llama", "CORTEX_LOCAL_URL": url,
                                    "ASTRA_CORTEX_MODEL": model, "CORTEX_TIMEOUT_SECONDS": str(timeout)})
    return CortexProvider(config).generate(payload)

class BackgroundProvider:
    """At most one daemon thread/request, no retries or queue growth."""
    def __init__(self, provider):
        self.provider = provider
        self.result = queue.Queue(maxsize=1)
        self.worker = None

    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def submit(self, payload, now_ms):
        if self.busy or not self.result.empty():
            return False
        def generate():
            try:
                item = {"decision": self.provider.generate(payload), "error": None}
            except Exception as exc:
                code = str(exc)
                item = {"decision": None, "error": code if re.fullmatch(r"provider_[a-z0-9_]+", code) else type(exc).__name__}
            item.update({"request_ts_ms": now_ms, "candidate_id": (payload.get("candidate") or {}).get("candidate_id"),
                         "completed_ts_ms": int(time.time() * 1000)})
            self.result.put_nowait(item)
        self.worker = threading.Thread(target=generate, name="cortex-advisory", daemon=True)
        self.worker.start()
        return True

    def poll(self):
        try:
            return self.result.get_nowait()
        except queue.Empty:
            return None

def persist_proposals(path: Path, proposals: list[dict], now_ms: int, source: str) -> int:
    try:
        state = load_memory(path) if path.exists() else {"version": VERSION, "hypotheses": []}
    except (ValueError, KeyError, OSError, TypeError):
        state = {"version": VERSION, "hypotheses": [], "recovery": "invalid_memory_ignored"}
    known = {h["id"]: h for h in state.get("hypotheses", [])}
    for proposal in proposals[:6]:
        identity = hashlib.sha256(canonical(proposal)).hexdigest()[:20]
        if identity not in known:
            known[identity] = {"id": identity, "proposal": proposal, "proposed_ts_ms": now_ms,
                               "source": source, "status": "PENDING_OFFLINE_VALIDATION", "production_eligible": False}
    state["hypotheses"] = list(known.values())[-256:]
    save_memory(path, state)
    return len(state["hypotheses"])

def build_payload(status, report, memory, now_ms):
    candidate = status.get("candidate") or {}
    features = clean_features((status.get("cortex_evidence") or {}).get("features"))
    return {"as_of_ms": now_ms, "candidate": candidate,
            "expected_next_local": status.get("expected_side"),
            "last_teacher_local": status.get("last_teacher_local"),
            "features": features, "allowed_features": sorted(features),
            "feature_snapshot": {k: v for k, v in (status.get("cortex_evidence") or {}).items() if k != "features"},
            "statistical_analysis": report,
            "jepa_evidence": causal_cortex_evidence(status.get("jepa_evidence"), now_ms),
            "research_hypotheses": [{k: h.get(k) for k in ("id", "conditions", "side", "stage_s", "status")}
                                    for h in memory.get("hypotheses", [])[:48]],
            "constraints": {"advisory_only": True, "may_modify_quantum": False,
                            "real_orders": False, "missing_features_are_unknown": True}}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--minutes", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, default=300)
    parser.add_argument("--research-memory", type=Path)
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args()
    if args.minutes <= 0 or args.interval_seconds < 1 or not .05 <= args.poll_seconds <= 30:
        parser.error("minutes/interval must be positive and poll-seconds must be 0.05..30")
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    owner = acquire_owner(args.checkpoint_dir)
    memory_path = args.research_memory or args.checkpoint_dir / "CORTEX_RESEARCH_MEMORY.json"
    memory_error = None
    try:
        memory = load_memory(memory_path) if memory_path.exists() else {}
    except (ValueError, KeyError, OSError, TypeError):
        memory, memory_error = {}, "invalid_research_memory_ignored"
    analyst = StatisticalCortex(args.checkpoint_dir / "CORTEX_STATISTICAL_STATE.json", memory)
    provider_config_error = None
    try:
        provider = CortexProvider(AdapterConfig.from_env())
    except Exception as exc:
        code = str(exc)
        provider_config_error = code if re.fullmatch(r"provider_[a-z0-9_]+", code) else type(exc).__name__
        provider = CortexProvider(AdapterConfig())
    background = BackgroundProvider(provider)
    status_path = args.checkpoint_dir / "LOCAL_ONLY_STATUS.json"
    out = args.checkpoint_dir / "CORTEX_LOCAL_ONLY_STATUS.json"
    proposal_path = args.checkpoint_dir / "CORTEX_LLM_HYPOTHESES.json"
    deadline = time.monotonic() + args.minutes * 60
    next_call = 0.0
    calls = errors = 0
    last_llm = None
    last = {}
    while time.monotonic() < deadline:
        now_ms = int(time.time() * 1000)
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() and status_path.stat().st_size <= 1_048_576 else {}
            report = analyst.analyze(status, now_ms)
            completed = background.poll()
            if completed is not None:
                last_llm = completed
                if completed["error"]:
                    errors += 1
                else:
                    calls += 1
                    persist_proposals(proposal_path, completed["decision"].get("hypotheses", []), now_ms,
                                      provider.config.backend + ":" + provider.config.model)
            candidate_id = (status.get("candidate") or {}).get("candidate_id")
            relevant = bool(last_llm and not last_llm["error"] and report["fresh_status"]
                            and last_llm["candidate_id"] == candidate_id
                            and 0 <= now_ms - last_llm["request_ts_ms"] <= analyst.stale_ms)
            if (provider.available and report["fresh_status"] and report["fresh_features"]
                    and time.monotonic() >= next_call and not background.busy):
                if background.submit(build_payload(status, report, memory, now_ms), now_ms):
                    next_call = time.monotonic() + args.interval_seconds
            last = {"state": "STATISTICAL_READY" if report["fresh_status"] else "WAITING_FOR_FRESH_QUANTUM",
                    "updated_ts_ms": now_ms, "calls": calls, "errors": errors,
                    "decision": last_llm["decision"] if relevant else report["decision"],
                    "candidate_side": (status.get("candidate") or {}).get("side"),
                    "memory_version": memory.get("version"), "statistical_analysis": report,
            "jepa_evidence": causal_cortex_evidence(status.get("jepa_evidence"), now_ms),
                    "llm": {"configured_backend": provider.config.backend, "model": provider.config.model,
                            "configured": provider.available, "availability_reason": provider.availability_reason,
                            "configuration_error": provider_config_error,
                            "connection_verified": bool(provider.last_response_metadata.get("connection_verified")),
                            "confidence_is_uncalibrated": True,
                            "in_flight": background.busy,
                            "current_advisory": relevant,
                            "last_request_ts_ms": last_llm["request_ts_ms"] if last_llm else None,
                            "last_error": last_llm["error"] if last_llm else None},
                    "research_memory_error": memory_error,
                    "quantum_independent": True, "model_or_threshold_changes": False,
                    "research_only": True, "real_orders": False}
        except Exception as exc:
            errors += 1
            last = {**last, "state": "DEGRADED", "updated_ts_ms": now_ms, "errors": errors,
                    "calls": calls, "error": type(exc).__name__, "decision": None,
                    "quantum_independent": True, "real_orders": False}
        atomic_json(out, last)
        time.sleep(min(args.poll_seconds, max(0, deadline - time.monotonic())))
    print("LOCAL_CORTEX=" + json.dumps(last, separators=(",", ":"), ensure_ascii=False))
    owner.close()

if __name__ == "__main__":
    main()
