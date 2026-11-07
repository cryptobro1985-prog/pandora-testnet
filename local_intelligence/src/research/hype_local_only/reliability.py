"""Local, single-writer persistence for research inference.

The generation pointer is the commit record. A model and the input cursor that
produced it are never committed separately. Pickles must come from a trusted
local training run; SHA256 detects damage, not a malicious pickle author.
"""
from __future__ import annotations

import fcntl
import hashlib
import heapq
import json
import os
import pickle
import tempfile
import time
import uuid
from collections import OrderedDict
from pathlib import Path


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


class WriterLock:
    """Advisory Linux lock shared by pretraining, replay, and live daemons."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+")
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            self.stream = None
            raise RuntimeError(f"another writer owns {self.path}") from None
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(json.dumps({"pid": os.getpid(), "started_ns": time.time_ns()}))
        self.stream.flush()
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


class CheckpointStore:
    SCHEMA = 1

    def __init__(self, root: Path, retain: int = 3):
        self.root = Path(root)
        self.generations = self.root / "runtime_generations"
        self.pointer = self.root / "RUNTIME_CURRENT.json"
        self.retain = max(2, int(retain))
        self.active_generation = None
        self.recovery = None

    def _pointer_names(self):
        try:
            pointer = json.loads(self.pointer.read_text())
            names = [pointer["current"], *pointer.get("fallbacks", [])]
            if not all(isinstance(name, str) and Path(name).name == name for name in names):
                raise ValueError("unsafe generation name")
            return list(dict.fromkeys(names))
        except (OSError, ValueError, KeyError, TypeError):
            if not self.generations.exists():
                return []
            return sorted((p.name for p in self.generations.iterdir() if p.is_dir()), reverse=True)

    def _read(self, name: str):
        if Path(name).name != name:
            raise ValueError("unsafe generation name")
        folder = self.generations / name
        manifest = json.loads((folder / "manifest.json").read_text())
        data = (folder / "bundle.pkl").read_bytes()
        if manifest.get("schema") != self.SCHEMA:
            raise ValueError("unsupported checkpoint schema")
        if len(data) != manifest.get("bytes") or hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
            raise ValueError("checkpoint checksum mismatch")
        bundle = pickle.loads(data)
        if not isinstance(bundle, dict) or bundle.get("schema") != self.SCHEMA:
            raise ValueError("invalid runtime bundle")
        return bundle

    def load(self):
        names = self._pointer_names()
        failures = []
        for name in names:
            try:
                bundle = self._read(name)
            except Exception as exc:
                failures.append({"generation": name, "error": str(exc)})
                continue
            self.active_generation = name
            self.recovery = {"loaded": name, "rejected": failures} if failures else None
            return bundle
        if names or self.pointer.exists():
            raise RuntimeError(f"no intact runtime checkpoint: {failures}")
        return None

    def save(self, bundle: dict):
        if bundle.get("schema") != self.SCHEMA:
            raise ValueError("bundle needs current schema")
        data = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:10]}"
        folder = self.generations / name
        folder.mkdir(parents=True)
        atomic_bytes(folder / "bundle.pkl", data)
        atomic_json(folder / "manifest.json", {
            "schema": self.SCHEMA, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "created_ns": time.time_ns(),
            "last_event_ms": bundle.get("runtime", {}).get("last_seen"),
        })
        _sync_directory(self.generations)
        previous = [self.active_generation, *self._pointer_names()]
        previous = list(dict.fromkeys(n for n in previous if n and n != name))[: self.retain - 1]
        atomic_json(self.pointer, {"schema": self.SCHEMA, "current": name, "fallbacks": previous})
        self.active_generation = name
        # Remove only known generation payloads; never traverse an arbitrary tree.
        keep = {name, *previous}
        for old in self.generations.iterdir():
            if old.is_dir() and old.name not in keep:
                for filename in ("bundle.pkl", "manifest.json"):
                    (old / filename).unlink(missing_ok=True)
                try:
                    old.rmdir()
                except OSError:
                    pass
        return name

    def rollback(self, name: str):
        self._read(name)  # Verify before changing the pointer.
        previous = [n for n in self._pointer_names() if n != name][: self.retain - 1]
        atomic_json(self.pointer, {"schema": self.SCHEMA, "current": name, "fallbacks": previous})
        self.active_generation = name


class JsonlEvidence:
    """Append-only evidence, idempotent across a bundle commit/replay boundary."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ids = set()
        if self.path.exists():
            # A crash may leave a partial final line. Discard that tail before
            # appending, otherwise its next record becomes unreadable too.
            with self.path.open("rb+") as stream:
                valid_end = 0
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        break
                    try:
                        row = json.loads(line)
                        if row.get("event_id"):
                            self.ids.add(row["event_id"])
                    except (ValueError, AttributeError):
                        pass
                    valid_end = stream.tell()
                stream.truncate(valid_end)

    def append(self, row: dict):
        event_id = row.get("event_id")
        if event_id is not None and event_id in self.ids:
            return False
        data = (json.dumps(row, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()
        with self.path.open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if event_id is not None:
            self.ids.add(event_id)
        return True


def event_identity(kind: str, row: dict) -> str:
    """Dedup copies/reconnect replay without depending on capture filename."""
    canonical = {k: v for k, v in row.items() if not k.startswith("_source")}
    if kind == "raw":
        try:
            message = json.loads(row["raw_text"]) if isinstance(row.get("raw_text"), str) else row["raw_text"]
            if isinstance(message, dict) and message.get("topic"):
                # Identical Bybit frames replayed with a new local receipt time
                # still represent the same trades / book update.
                canonical = message
        except (ValueError, KeyError, TypeError):
            pass
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    return kind + ":" + hashlib.sha256(encoded).hexdigest()


class DedupWindow:
    def __init__(self, keys=(), capacity=100_000):
        self.capacity = int(capacity)
        self.keys = OrderedDict((key, None) for key in keys)

    def seen(self, key: str) -> bool:
        if key in self.keys:
            return True
        self.keys[key] = None
        if len(self.keys) > self.capacity:
            self.keys.popitem(last=False)
        return False


class DurableTailer:
    """Bounded k-way merge; offsets are committed only for returned records.

    Reads one lookahead record per file, sorts on receive time, and leaves
    partial lines untouched. The caller commits these offsets together with
    the model after consuming the complete returned batch.
    """
    SOURCES = (("HYPE_live_raw_frames.jsonl", "raw"),
               ("HYPE_market_context.jsonl", "market"),
               ("HYPE_structural_context_1m.jsonl", "struct"),
               ("HYPE_live_microstructure_1s.jsonl", "micro"))

    def __init__(self, offsets=None):
        self.offsets = offsets or {}
        self.notices = []

    def read_events(self, root: Path, limit: int = 2000):
        streams = []
        heap = []
        serial = 0
        try:
            for priority, (pattern, kind) in enumerate(self.SOURCES):
                for path in sorted(Path(root).rglob(pattern)):
                    key = str(path.resolve())
                    try:
                        stream = path.open("rb")
                    except FileNotFoundError:
                        continue
                    streams.append(stream)
                    stat = os.fstat(stream.fileno())
                    head = hashlib.sha256(stream.read(128)).hexdigest() if stat.st_size >= 128 else None
                    cursor = self.offsets.get(key, {})
                    changed = (cursor.get("inode") not in (None, stat.st_ino)
                               or cursor.get("device") not in (None, stat.st_dev)
                               or stat.st_size < cursor.get("offset", 0)
                               or (head is not None and cursor.get("head") not in (None, head)))
                    offset = 0 if changed else int(cursor.get("offset", 0))
                    if changed:
                        self.notices.append({"event": "SOURCE_ROTATED", "source": key})
                    meta = {"inode": stat.st_ino, "device": stat.st_dev, "head": head}
                    stream.seek(offset)
                    serial += 1
                    item = self._next(stream, key, kind, priority, serial, meta)
                    if item:
                        heapq.heappush(heap, item)
            events = []
            while heap and len(events) < max(1, int(limit)):
                ts, priority, serial, kind, row, stream, key, end, meta = heapq.heappop(heap)
                self.offsets[key] = {**meta, "offset": end}
                events.append((ts, priority, kind, row))
                item = self._next(stream, key, kind, priority, serial, meta)
                if item:
                    heapq.heappush(heap, item)
            return events
        finally:
            for stream in streams:
                stream.close()

    def _next(self, stream, key, kind, priority, serial, meta):
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line or not line.endswith(b"\n"):
                return None
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not object")
                ts = int(row.get("received_ts_ms") or row.get("ts_ms") or 0)
            except (ValueError, TypeError):
                self.notices.append({"event": "INVALID_SOURCE_LINE", "source": key, "offset": start})
                self.offsets[key] = {**meta, "offset": stream.tell()}
                continue
            row["_source_path"] = key
            return (ts, priority, serial, kind, row, stream, key, stream.tell(), meta)
