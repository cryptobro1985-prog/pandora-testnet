"""Offline verification of retained JSON datasets; never deserialize pickles.

PYTHONPATH=src python -m research.hype_history_backfill.verify --root . \
    --output docs/DATA_INTEGRITY.json

An integrity pass is not evidence that archived fitted features are causal.
The original snapshot features remain explicitly quarantined in this report.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from research.hype_local_v5.labels import completed_hours, structural_labels


def _reject_constant(value):
    raise ValueError(f'nonfinite JSON number: {value}')


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'nonfinite JSON float: {value}')
    return result


def parse_json(text):
    return json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float)


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            result.update(chunk)
    return result.hexdigest()


def load_json(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return parse_json(stream.read())


def load_jsonl(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return [parse_json(line) for line in stream if line.strip()]


def utc(value):
    return datetime.fromtimestamp(value/1000, timezone.utc).isoformat()


def verify_serialization(root, excluded=()):
    """Read every byte (including gzip CRC/trailer) and reject NaN/Infinity."""
    files, errors = [], []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.resolve() in excluded:
            continue
        if not path.name.endswith(('.json', '.jsonl', '.json.gz', '.jsonl.gz')):
            continue
        record = dict(path=str(path.relative_to(root)), bytes=path.stat().st_size,
                      sha256=sha256(path))
        try:
            if '.jsonl' in path.name:
                opener = gzip.open if path.suffix == '.gz' else open
                count = 0
                with opener(path, 'rt', encoding='utf-8') as stream:
                    for number, line in enumerate(stream, 1):
                        if not line.strip():
                            continue
                        item = parse_json(line)
                        if not isinstance(item, dict):
                            raise ValueError(f'line {number}: JSONL record must be an object')
                        count += 1
                record['records'] = count
            else:
                value = load_json(path)
                record['json_type'] = type(value).__name__
            record['valid'] = True
        except (ValueError, OSError, EOFError, UnicodeError) as exc:
            record['valid'] = False
            errors.append(f'{path.relative_to(root)}: {exc}')
        files.append(record)
    return files, errors


def verify_manifests(root):
    checks, errors = [], []
    for manifest in sorted(root.rglob('*.json')):
        if manifest.name not in ('manifest.json', 'artifact_manifest.json'):
            continue
        value = load_json(manifest)
        if not isinstance(value, dict):
            errors.append(f'{manifest.relative_to(root)}: manifest must be an object')
            continue
        entries = value.get('files', {}) if manifest.name == 'manifest.json' else value
        if not isinstance(entries, dict):
            errors.append(f'{manifest.relative_to(root)}: declared files must be an object')
            continue
        for name, expected in entries.items():
            if not isinstance(name, str) or not isinstance(expected, dict) or not isinstance(expected.get('sha256'), str) or len(expected['sha256']) != 64 or any(c not in '0123456789abcdefABCDEF' for c in expected['sha256']):
                errors.append(f'{manifest.relative_to(root)}: malformed hash entry {name}')
                continue
            path = (manifest.parent/name).resolve()
            if not path.is_relative_to(root.resolve()):
                errors.append(f'{manifest.relative_to(root)}: unsafe declared path {name}')
                continue
            valid = path.is_file() and sha256(path) == expected['sha256']
            if path.is_file() and 'bytes' in expected:
                valid = valid and path.stat().st_size == expected['bytes']
            checks.append(dict(manifest=str(manifest.relative_to(root)), file=name, valid=valid))
            if not valid:
                errors.append(f'{manifest.relative_to(root)}: checksum/size mismatch or missing {name}')
    return checks, errors


def audit_history(root):
    folder = root/'artifacts/history_30d_local116'
    if not folder.is_dir():
        return {}, [], []
    minutes = load_jsonl(folder/'compact_1m.jsonl.gz')
    snapshots = load_jsonl(folder/'candidate_snapshots.jsonl.gz')
    labels = load_json(folder/'labels.json.gz')
    manifest = load_json(folder/'manifest.json')
    errors, warnings = [], []
    start = int(datetime.fromisoformat(manifest['period'][0]).timestamp()*1000)
    end = int(datetime.fromisoformat(manifest['period'][1]).timestamp()*1000)
    starts = [int(row['start_ms']) for row in minutes]
    if any(b <= a for a,b in zip(starts, starts[1:])):
        errors.append('compact minute starts are not strictly increasing')
    missing = sorted(set(range(start,end,60_000))-set(starts))
    if any(row['ts_ms'] != row['start_ms']+60_000 or
           row['bar_end_ms'] != row['ts_ms'] for row in minutes):
        errors.append('compact minute physical/availability boundaries disagree')
    if sum(row['trade_count'] for row in minutes) != manifest['integrity']['total_trades']:
        errors.append('compact trade counts disagree with archive provenance')
    for row in minutes:
        for name in ('high_ts_ms', 'low_ts_ms'):
            if not row['start_ms'] <= row[name] < row['bar_end_ms']:
                errors.append(f'extreme timestamp outside physical minute: {row["start_ms"]}')
    teacher = {}
    for kind, lookback, lookahead in (('strict',6,2), ('internal',3,1)):
        rebuilt, excluded = structural_labels(minutes, lookback, lookahead)
        exact = rebuilt == labels[kind] and excluded == labels[kind+'_exclusions']
        if not exact:
            errors.append(f'{kind} archived labels differ from completed-minute teacher')
        matched = {row[kind+'_label_id'] for row in snapshots if row[kind+'_true']}
        mature = [row for row in labels[kind] if row['reference_finalized']]
        teacher[kind] = dict(labels=len(labels[kind]), finalized=len(mature),
            side_counts=dict(Counter(row['side'] for row in labels[kind])),
            exact_reproduction=exact, exclusions=labels[kind+'_exclusions'],
            labels_represented_by_candidate_snapshots=len(matched),
            candidate_coverage=len(matched)/len(labels[kind]),
            confirmation_delay_hours_min=min(row['label_available_ms']-row['extreme_interval_end_ms'] for row in labels[kind])/3_600_000,
            confirmation_delay_hours_max=max(row['label_available_ms']-row['extreme_interval_start_ms'] for row in labels[kind])/3_600_000,
            terminal_label_censored=bool(labels[kind] and not labels[kind][-1]['reference_finalized']),
            collapsed_reference_finalization='next opposite retained pivot availability; distinct from K2 confirmation')
        for index, row in enumerate(labels[kind]):
            if row['label_available_ms'] < row['hour_ms']+(lookahead+1)*3_600_000:
                errors.append(f'{kind} label {row["label_id"]} matures before required completed future hours')
            if index and row['side'] == labels[kind][index-1]['side']:
                errors.append(f'{kind} retained labels do not alternate')
            minute = next((r for r in minutes if r['start_ms'] == row['extreme_interval_start_ms']),None)
            field = 'high' if row['side'] == 'HIGH' else 'low'
            if minute is None or minute[field] != row['extreme_price']:
                errors.append(f'{kind} label extreme does not reconcile to retained minute')
    groups, seen = defaultdict(list), set()
    for row in snapshots:
        key = row['candidate_id'], row['snapshot_ts_ms']
        if key in seen:
            errors.append(f'duplicate candidate snapshot {key}')
        seen.add(key)
        groups[row['candidate_id']].append(row)
        if row['snapshot_ts_ms'] != row['candidate_ts_ms']+row['delay_s']*1000:
            errors.append(f'snapshot chronology mismatch {key}')
        for kind in ('strict','internal'):
            label_id = row[kind+'_label_id']
            if bool(label_id) != row[kind+'_true']:
                errors.append(f'snapshot truth/id mismatch {key}')
            if label_id:
                label = labels[kind][label_id-1]
                if row['side'] != label['side'] or row['extreme_price'] != label['extreme_price'] or not label['extreme_interval_start_ms'] <= row['candidate_ts_ms'] < label['extreme_interval_end_ms']:
                    errors.append(f'snapshot does not match teacher extreme {key}')
    for candidate_id, rows in groups.items():
        if any(b['snapshot_ts_ms'] <= a['snapshot_ts_ms'] for a,b in zip(rows,rows[1:])):
            errors.append(f'candidate snapshots out of order: {candidate_id}')
    result = dict(period=manifest['period'], minute_rows=len(minutes),
        expected_minutes=(end-start)//60_000,
        missing_minutes=[dict(ts_ms=t, utc=utc(t)) for t in missing],
        completed_h1_rows=len(completed_hours(minutes)),
        retained_trade_count=sum(row['trade_count'] for row in minutes),
        source_archive_days=len(manifest['integrity']['days']),
        raw_archives_retained=manifest['raw_archives_retained'],
        five_second_rows_claimed_but_not_retained=manifest['five_second_bars'],
        labels=teacher, candidates=len(groups), snapshots=len(snapshots),
        snapshots_by_delay_s=dict(sorted(Counter(row['delay_s'] for row in snapshots).items())),
        mean_snapshots_per_candidate=len(snapshots)/len(groups),
        source_boundary_leakage_exposure=dict(
            snapshots_inside_unfinished_5s_bucket=sum(row['snapshot_ts_ms']%5000!=0 for row in snapshots),
            snapshots_inside_unfinished_minute=sum(row['snapshot_ts_ms']%60_000!=0 for row in snapshots),
            minute_features_using_uncompleted_source_bar=sum(minutes[bisect.bisect_right(starts,row['snapshot_ts_ms'])-1]['bar_end_ms']>row['snapshot_ts_ms'] for row in snapshots),
            note='Source code slices bucket starts, then uses final OHLC/flow. Counts show timing exposure, not a claim that each numeric value changes.'),
        extreme_timestamps_equal_bucket_start={name:sum(row[name]==row['start_ms'] for row in minutes) for name in ('high_ts_ms','low_ts_ms')},
        original_snapshot_features_status='QUARANTINED: partial-bucket future leakage; rebuild from completed compact minutes')
    warnings += [
        'Gzip/JSON/checksum validity does not certify causal model inputs.',
        'Original 6261 snapshots are correlated repeated views of 1797 selected candidates, not 6261 independent events.',
        'Original candidate eligibility uses full-minute extrema: 0s/30s observations are selected retrospectively within that minute.',
        'Six-hour record candidate selection misses internal teacher pivots; evaluate all teacher events, including candidates never generated.',
        'High/low timestamps equal bucket start may be initialization placeholders; exact subminute extreme timing is not independently recoverable without raw trades.',
        'Raw trade archives and 5s bars were discarded; recorded hashes/provenance cannot be recomputed from retained raw sources.',
    ]
    gap = root/'artifacts/historical_gaps'
    if gap.is_dir():
        coverage = {}
        for name, filename, cadence in (('mark','mark_1m.jsonl.gz',60_000),('index','index_1m.jsonl.gz',60_000),('oi','open_interest_5m.jsonl.gz',300_000),('funding','funding.jsonl.gz',28_800_000)):
            rows = load_jsonl(gap/filename)
            keys = [row['ts_ms'] for row in rows]
            regular = all(b-a==cadence for a,b in zip(keys,keys[1:]))
            if not regular:
                errors.append(f'{name} source cadence has duplicates/gaps/disorder')
            coverage[name] = dict(rows=len(rows), expected_rows=(end-start)//cadence,
                first_ts_ms=keys[0], last_ts_ms=keys[-1], cadence_ms=cadence,
                complete_grid=regular and len(rows)==(end-start)//cadence and keys[0]==start and keys[-1]+cadence==end,
                receipt_time_available=any(row.get('received_at_ms') is not None or row.get('received_ts_ms') is not None for row in rows),
                timestamp_semantics='bar start; close requires +60000ms' if name in ('mark','index') else 'exchange observation/settlement timestamp')
        enriched = load_jsonl(gap/'candidate_snapshots_enriched.jsonl.gz')
        if len(enriched)!=len(snapshots):
            errors.append('archived gap enrichment row count differs from source snapshots')
        for base, row in zip(snapshots, enriched):
            if any(row.get(key)!=base.get(key) for key in base if key!='features'):
                errors.append('archived enrichment changed snapshot metadata/teacher')
                break
            if any(row['features'].get(key)!=value for key,value in base['features'].items()):
                errors.append('archived enrichment changed pre-existing features')
                break
            t = row['snapshot_ts_ms']
            sources = row['historical_gap_sources']
            for name in ('mark','index','oi','funding'):
                source_ts = sources.get(name+'_ts_ms')
                if source_ts is not None and source_ts+(60_000 if name in ('mark','index') else 0)>t:
                    errors.append(f'archived {name} enrichment uses an uncompleted/future source')
        result['gap_sources'] = coverage
        result['archived_enriched_rows'] = len(enriched)
        result['archived_gap_join'] = 'completion-safe; instant publication assumed; no historical receipt timestamps; upstream features quarantined'
        warnings.append('Mark/index/OI/funding source coverage is complete, but receipt/publication latency is unobserved; as-of lags require forward validation and sensitivity analysis.')
    return result, errors, warnings


def verify(root, excluded=()):
    root = Path(root).resolve()
    files, errors = verify_serialization(root, excluded)
    checks = []
    try:
        checks, manifest_errors = verify_manifests(root)
        errors += manifest_errors
        history, history_errors, warnings = audit_history(root)
        errors += history_errors
    except (ValueError, KeyError, OSError, EOFError, TypeError, IndexError) as exc:
        history, warnings = {}, []
        errors.append(f'dataset/schema audit failed: {exc}')
    return dict(schema='pandora-offline-data-integrity-v1', valid=not errors,
        files_checked=len(files), gzip_files_checked=sum(row['path'].endswith('.gz') for row in files),
        manifest_entries_checked=len(checks), errors=errors, warnings=warnings,
        serialization=files, manifest_checks=checks, history=history,
        scope='JSON/gzip/manifest/chronology only; pickle deserialization deliberately excluded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    excluded = {args.output.resolve()} if args.output else set()
    report = verify(args.root, excluded)
    rendered = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('valid','files_checked','gzip_files_checked','manifest_entries_checked','errors')}, ensure_ascii=False))
    raise SystemExit(0 if report['valid'] else 1)


if __name__ == '__main__':
    main()
