"""Create a source ZIP with per-file hashes; excludes credentials, caches and DBs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def package(output,baseline=None):
    output=output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise FileExistsError(output)
    command=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True)
    candidates=[ROOT/name for name in command.stdout.decode().split('\0') if name] if command.returncode==0 else ROOT.rglob('*')
    files={}
    for path in candidates:
        if not path.is_file() or path.is_symlink():continue
        relative=path.relative_to(ROOT)
        if any(part in ('.git','.venv','__pycache__','node_modules') or part.startswith('.env') for part in relative.parts):continue
        if any(part.startswith('.') and part not in ('.github','.gitignore','.dockerignore') for part in relative.parts):continue
        if path.suffix.lower() not in ('.py','.md','.txt','.json','.yaml','.yml','.sql') and path.name not in ('Dockerfile','.gitignore','.dockerignore') and relative.as_posix()!='validation/release.log':continue
        files[relative.as_posix()]=path.read_bytes()
    if baseline:files['baseline/known-working.zip']=baseline.read_bytes()
    report_path=ROOT/'validation/release-result.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {}
    status=('PAPER_RELEASE_TESTS_PASSED_LIVE_UNVERIFIED' if report.get('successful') and report.get('tests_run',0)>0 and not report.get('skipped') else 'UNVERIFIED_SOURCE_SNAPSHOT')
    manifest={'format':1,'status':status,
              'production_database_included':False,'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
    try:
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for name,data in sorted(files.items()):archive.writestr('PANDORA_PAPER/'+name,data)
            archive.writestr('PANDORA_PAPER/MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:raise RuntimeError('ZIP integrity check failed')
            for name,digest in manifest['files'].items():
                if hashlib.sha256(archive.read('PANDORA_PAPER/'+name)).hexdigest()!=digest:
                    raise RuntimeError('archive hash mismatch: '+name)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
    return {'path':str(output),'bytes':output.stat().st_size,'files':len(files)+1,'sha256':digest,'status':manifest['status']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    args=parser.parse_args()
    print(json.dumps(package(args.output,args.baseline),indent=2))


if __name__=='__main__':main()
