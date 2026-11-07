#!/usr/bin/env python3
"""Build a reviewable local release; never publishes or deploys."""
from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CACHE_EXCLUDES={'artifacts/full_history_research/features.npz','artifacts/full_history_research/frozen_jepa_latents.npz'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def included():
    return sorted(p for p in ROOT.rglob('*') if p.is_file() and
                  not set(p.relative_to(ROOT).parts).intersection({'.venv','__pycache__','.pytest_cache','.git'})
                  and p.suffix not in {'.pyc','.pyo'} and str(p.relative_to(ROOT)) not in CACHE_EXCLUDES
                  and p.name not in {'.local_writer.lock','.cortex_writer.lock','.jepa_writer.lock','.full_history_writer.lock','.case_writer.lock','.analyzer_writer.lock'})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise SystemExit('Output ZIP must be outside the release tree')
    original=json.loads((ROOT/'docs/ORIGINAL_INPUT_HASHES.json').read_text())
    protected=[n for n in original if n.startswith(('src/research/hype_caterpillar_monitor/',
                                                    'src/research/hype_rest_relay/'))]
    changed=[n for n in protected if not (ROOT/n).is_file() or digest(ROOT/n)!=original[n]]
    if changed: raise SystemExit('Protected monitor/HTTP producer routes changed: '+repr(changed))
    manifest={
        'bundle':'PANDORA_LOCAL_INTELLIGENCE',
        'source_archive':'PANDORA_HYPE_LOCAL_ONLY_CODEX.zip',
        'source_git_sha':'68bcb02ad94bec1f317ca921d55b3af4c8f0c491',
        'monitor_unchanged':True,'real_orders':False,'published':False,
        'protected_original_files':{n:original[n] for n in protected},
        'files':[str(p.relative_to(ROOT)) for p in included()
                 if p.name not in {'SHA256SUMS.txt','BUNDLE_MANIFEST.json'}],
        'integrity_note':'SHA256SUMS excludes itself; manifest is included in checksums. Original upload hashes are retained separately.'}
    (ROOT/'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    files=[p for p in included() if p.name!='SHA256SUMS.txt']
    (ROOT/'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.relative_to(ROOT)}\n' for p in files))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in included():z.write(p,Path('PANDORA_LOCAL_INTELLIGENCE')/p.relative_to(ROOT))
    with zipfile.ZipFile(args.output) as z:
        if z.testzip() is not None:raise SystemExit('ZIP CRC check failed')
        for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
            sha,rel=line.split('  ',1)
            if hashlib.sha256(z.read('PANDORA_LOCAL_INTELLIGENCE/'+rel)).hexdigest()!=sha:
                raise SystemExit('ZIP checksum mismatch '+rel)
    sha=digest(args.output)
    args.output.with_suffix(args.output.suffix+'.sha256').write_text(sha+'  '+args.output.name+'\n')
    print(json.dumps({'zip':str(args.output),'sha256':sha,'bytes':args.output.stat().st_size,
                      'files':len(included()),'monitor_unchanged':True}))

if __name__=='__main__':main()
