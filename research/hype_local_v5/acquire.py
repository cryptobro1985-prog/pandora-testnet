#!/usr/bin/env python3
"""Bounded, provenance-preserving acquisition of the specified HYPE research data.

Uses inherited HTTPS proxy, CA trust and GitHub proxy authentication. Never disables
TLS verification, starts login, scrapes credentials or synthesizes missing data.
Run with --fetch to download artifacts/raw archives after probes succeed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import resource
import urllib.parse
import urllib.error
import urllib.request
import zipfile

REPO = "cryptobro1985-prog/pandora-testnet"
ARTIFACTS = {
    13278474318: "universal-minute-HYPE",
    13279637097: "PANDORA-UNIVERSAL-30D-FINAL",
    13319113404: "HYPE-H1-LOCAL-V5-TICKS-0",
    13318817968: "HYPE-H1-LOCAL-V5-TICKS-1",
    13319258376: "HYPE-H1-LOCAL-V5-TICKS-2",
    13319686512: "HYPE-H1-LOCAL-V5-TICKS-3",
    13318779319: "HYPE-H1-LOCAL-V5-TICKS-4",
    13319471883: "HYPE-H1-LOCAL-V5-TICKS-5",
    13321242644: "HYPE-H1-LOCAL-V5-LIVE-MICROSTRUCTURE",
}
MAX_BYTES = 512 * 1024 * 1024


def digest(path: Path) -> dict:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": sha.hexdigest()}


def safe_extract(path: Path, target: Path, max_bytes: int = 4 * MAX_BYTES,
                 max_files: int = 10000) -> list[dict]:
    """Validate the complete zip before extracting any member; never overwrite."""
    target = target.resolve()
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        if len(members) > max_files or sum(x.file_size for x in members) > max_bytes:
            raise ValueError("archive exceeds declared extraction limits")
        names = set()
        for m in members:
            p = PurePosixPath(m.filename)
            mode = m.external_attr >> 16
            if (p.is_absolute() or ".." in p.parts or "\\" in m.filename or
                    ":" in m.filename or stat.S_ISLNK(mode)):
                raise ValueError("unsafe archive member")
            dst = target.joinpath(*p.parts).resolve()
            if not dst.is_relative_to(target) or m.filename in names:
                raise ValueError("unsafe or duplicate archive member")
            names.add(m.filename)
            if dst.exists() and not m.is_dir():
                raise FileExistsError(dst)
        outputs = []
        for m in members:
            dst = target / m.filename
            if m.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Zip CRC is checked by zipfile; HTTPS and optional publisher digest
            # establish origin. This SHA identifies our exact downloaded input.
            with z.open(m) as src, dst.open("xb") as out:
                shutil.copyfileobj(src, out)
            outputs.append(digest(dst))
        return outputs


def probe(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pandora-hype-research/1"})
        with urllib.request.urlopen(req, timeout=20) as response:
            # Consume bounded metadata only, never raw market payloads on probes.
            response.read(256)
            return {"url": url, "status": "accessible", "http_status": response.status}
    except urllib.error.HTTPError as e:
        return {"url": url, "status": "denied" if e.code in (401, 403) else "http_error",
                "http_status": e.code, "error": str(e)[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "status": "transport_error", "error": str(e)[:200]}


def gh_probe(artifact_id: int) -> dict:
    """Probe private Actions metadata with the SAME auth as the download.

    An unauthenticated urllib GET may return 404 on an accessible private
    artifact. Never gate authenticated gh downloads on that anonymous request.
    This reuses gh's inherited authentication; no tokens are read or copied.
    """
    path = f"/repos/{REPO}/actions/artifacts/{artifact_id}"
    result = {"source":"github_actions", "api_path":path,
              "authentication":"existing_gh_configuration"}
    try:
        proc = subprocess.run(["gh","api",path],capture_output=True,timeout=30)
        if proc.returncode:
            result.update(status="unavailable",error=proc.stderr.decode(errors='replace')[:300])
        else:
            meta = json.loads(proc.stdout)
            if meta.get('id') != artifact_id or meta.get('name') != ARTIFACTS[artifact_id]:
                raise ValueError('artifact identity mismatch')
            result.update(status='accessible',expired=meta.get('expired'),
                          artifact_id=artifact_id, name=meta['name'])
    except (OSError,subprocess.TimeoutExpired,ValueError) as error:
        result.update(status='unavailable',error=str(error)[:300])
    return result


def download(url: str, target: Path, max_bytes: int = MAX_BYTES) -> dict:
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".partial")
    if temp.exists():
        raise FileExistsError(temp)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pandora-hype-research/1"})
        with urllib.request.urlopen(req, timeout=90) as r, temp.open("xb") as out:
            size = 0
            for chunk in iter(lambda: r.read(1024 * 1024), b""):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("download exceeds byte limit")
                out.write(chunk)
        temp.rename(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return {"source": url, **digest(target)}


def gh_artifact(artifact_id: int, target: Path) -> dict:
    """Use gh's existing auth normally; never extract a token from its config."""
    path = f"repos/{REPO}/actions/artifacts/{artifact_id}"
    proc = subprocess.run(["gh", "api", path], capture_output=True, timeout=30)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace")[:300])
    meta = json.loads(proc.stdout)
    if meta.get("expired"):
        raise ValueError("artifact is expired")
    if meta.get("size_in_bytes", MAX_BYTES + 1) > MAX_BYTES:
        raise ValueError("artifact exceeds download limit")
    if meta.get("name") != ARTIFACTS[artifact_id]:
        raise ValueError("artifact name does not match expected identity")
    target.parent.mkdir(parents=True, exist_ok=True)
    # gh follows the signed release-asset redirect while retaining its supported
    # credential scoping. A subprocess deadline bounds stalled downloads.
    def limit_file_size():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    try:
        with target.open("xb") as out:
            proc = subprocess.run(["gh", "api", path + "/zip"], stdout=out,
                                  stderr=subprocess.PIPE, timeout=180,
                                  preexec_fn=limit_file_size)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if proc.returncode:
        target.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr.decode(errors="replace")[:300])
    if target.stat().st_size > MAX_BYTES:
        target.unlink()
        raise ValueError("artifact exceeds download limit")
    record = {"artifact_id": artifact_id, "name": meta["name"], **digest(target)}
    # GitHub's digest is optional on older artifacts. Never invent a publisher hash.
    publisher_digest = meta.get("digest")
    if publisher_digest and publisher_digest != "sha256:" + record["sha256"]:
        target.unlink()
        raise ValueError("publisher artifact SHA-256 mismatch")
    record["publisher_digest"] = publisher_digest
    return record


def fetch_historical_oi(start: dt.date, end: dt.date, target: Path) -> dict:
    """Fetch true 5-minute OI observations only; never invent subminute samples."""
    start_ms = int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp() * 1000)
    end_ms = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(),
                                    dt.timezone.utc).timestamp() * 1000) - 1
    cursor = end_ms
    observations = {}
    pages = 0
    while cursor >= start_ms:
        if pages >= 100:
            raise ValueError("OI pagination exceeded 100 pages")
        params = urllib.parse.urlencode({"category": "linear", "symbol": "HYPEUSDT",
                 "intervalTime": "5min", "startTime": start_ms,
                 "endTime": cursor, "limit": 200})
        req = urllib.request.Request("https://api.bybit.com/v5/market/open-interest?" + params,
                  headers={"User-Agent": "pandora-hype-research/1"})
        with urllib.request.urlopen(req, timeout=30) as response:
            obj = json.loads(response.read(4 * 1024 * 1024))
        if obj.get("retCode") != 0:
            raise ValueError("Bybit OI returned nonzero retCode")
        rows = obj["result"]["list"]
        if not rows:
            break
        stamps = []
        for row in rows:
            ts = int(row["timestamp"])
            value = float(row["openInterest"])
            if value <= 0 or not math.isfinite(value):
                raise ValueError("invalid OI observation")
            if ts > cursor or ts < start_ms:
                raise ValueError("OI response outside requested interval")
            previous = observations.get(ts)
            if previous is not None and previous != value:
                raise ValueError("conflicting duplicate OI observation")
            observations[ts] = value
            stamps.append(ts)
        oldest = min(stamps)
        if oldest > cursor:
            raise ValueError("nonprogressing OI pagination")
        cursor = oldest - 1
        pages += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as out:
        out.write("ts_ms,open_interest\n")
        for ts in sorted(observations):
            out.write(f"{ts},{observations[ts]}\n")
    return {"source": "Bybit V5 public historical open-interest intervalTime=5min",
            "points": len(observations), "pages": pages,
            "available_30s_history": False, **digest(target)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument('--source',choices=['all','artifacts','bybit'],default='all',
                    help='independent source families; artifacts never require Bybit connectivity')
    ap.add_argument('--artifact-ids',nargs='+',type=int,choices=sorted(ARTIFACTS),
                    help='specific known artifact identities; default: all requested artifacts')
    ap.add_argument("--raw-start", default="2026-10-04")
    ap.add_argument("--raw-end", default="2026-11-02")
    args = ap.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    start = dt.date.fromisoformat(args.raw_start)
    end = dt.date.fromisoformat(args.raw_end)
    if not 0 <= (end - start).days < 62:
        ap.error("raw range must contain 1..62 days")
    public_url = f"https://public.bybit.com/trading/HYPEUSDT/HYPEUSDT{start.isoformat()}.csv.gz"
    oi_url = ("https://api.bybit.com/v5/market/open-interest?category=linear&symbol=HYPEUSDT"
              "&intervalTime=5min&limit=1")
    wanted = args.artifact_ids or list(ARTIFACTS)
    github_probe = gh_probe(wanted[0]) if args.source in ('all','artifacts') else None
    raw_probe = probe(public_url) if args.source in ('all','bybit') else None
    oi_probe = probe(oi_url) if args.source in ('all','bybit') else None
    probes = [p for p in (github_probe,raw_probe,oi_probe) if p is not None]
    report = {"observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "probes": probes, "files": [], "errors": [],
              "artifact_metadata": ARTIFACTS,
              "historical_microstructure": {
                  "book": "not available from candle or executed-trade archives",
                  "liquidations": "not inferable from executed trades",
                  "oi": "5min REST history does not provide historical 30s OI"},
              "fetch_requested": args.fetch, "source_selection":args.source,
              "selected_artifact_ids":wanted if github_probe is not None else [],
              "complete": False}
    if args.fetch and github_probe is not None and github_probe['status']=='accessible':
        for ident in wanted:
            name = ARTIFACTS[ident]
            try:
                archive = args.output / "archives" / f"{ident}.zip"
                record = gh_artifact(ident, archive)
                record["extracted"] = safe_extract(archive, args.output / "artifacts" / name)
                report["files"].append(record)
            except Exception as e:
                report["errors"].append({"artifact_id": ident, "error": str(e)[:300]})
    if args.fetch and raw_probe is not None and raw_probe['status']=='accessible':
        day = start
        while day <= end:
            url = f"https://public.bybit.com/trading/HYPEUSDT/HYPEUSDT{day.isoformat()}.csv.gz"
            try:
                report["files"].append(download(url, args.output / "raw" / f"HYPEUSDT{day}.csv.gz"))
            except Exception as e:
                report["errors"].append({"day": str(day), "error": str(e)[:300]})
            day += dt.timedelta(days=1)
    if args.fetch and oi_probe is not None and oi_probe['status']=='accessible':
        try:
            report["files"].append(fetch_historical_oi(start, end, args.output / "oi/HYPE_oi_5m.csv"))
        except Exception as e:
            report["errors"].append({"dataset": "historical_oi_5m", "error": str(e)[:300]})
    report["downloaded_files"] = len(report["files"])
    expected = (len(wanted) if github_probe is not None else 0)+((end-start).days+2 if raw_probe is not None else 0)
    report['download_phase_successful'] = (args.fetch and all(p['status']=='accessible' for p in probes)
        and not report['errors'] and len(report['files'])==expected)
    # Probe success never means the entire required dataset is complete.
    (args.output / "acquisition.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"downloaded_files": len(report["files"]), "probes": probes}, indent=2))
    return 0 if report['download_phase_successful'] else 2


if __name__ == "__main__":
    raise SystemExit(main())
