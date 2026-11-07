"""Publish bounded research reports through normal authenticated Git.

For an explicitly requested GitHub Actions research run. Uses checkout's existing
Git authentication; never reads tokens or changes proxy/network configuration.
Git plumbing preserves the working checkout and publishes only a separate report
branch. No deploy, production branch, force push, or raw credential file copying.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

BRANCH='research/hype-local-v5-results'
LIMIT=90*1024*1024
ALLOWED={'.json','.csv','.md','.log','.gz'}


def git(*args,input=None,env=None,check=True):
    result=subprocess.run(['git',*args],input=input,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,env=env,check=False,timeout=180)
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-1200:])
    return result


def prepare_reports(stage,out,reports):
    out.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for folder in reports:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.is_symlink() or path.suffix not in ALLOWED:
                continue
            relative=path.relative_to(folder)
            if any(x.startswith('.') for x in relative.parts):
                continue
            # Explicit report roots only: raw inputs and credentials are excluded.
            if any(x in ('raw','archives','artifacts','.git','.env') for x in relative.parts):
                continue
            target=out/'reports'/folder.name/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            if path.stat().st_size>2*1024*1024 and path.suffix!='.gz':
                target=target.with_suffix(target.suffix+'.gz')
                with path.open('rb') as source,target.open('wb') as raw:
                    with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as dest:
                        for chunk in iter(lambda:source.read(1024*1024),b''):dest.write(chunk)
            else:
                target.write_bytes(path.read_bytes())
            if target.stat().st_size>LIMIT:
                raise ValueError('report exceeds per-file Git limit; kept in Actions artifact: '+str(relative))
            sha=hashlib.sha256(target.read_bytes()).hexdigest()
            manifest.append(dict(path=str(target.relative_to(out)),bytes=target.stat().st_size,sha256=sha))
    status=dict(stage=stage,source_commit=os.getenv('GITHUB_SHA') or git('rev-parse','HEAD').stdout.decode().strip(),
        run_id=os.getenv('GITHUB_RUN_ID','local'),run_attempt=os.getenv('GITHUB_RUN_ATTEMPT','1'),
        report_branch=BRANCH,reports=manifest,orders_enabled=False,
        note='Stage is execution progress, not proof that market checks passed; read included run_status.json')
    (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    return status


def publish(out,status):
    prefix='runs/'+status['run_id']+'-'+status['run_attempt']+'/'+status['stage']
    env=os.environ.copy()
    env.update(GIT_AUTHOR_NAME='github-actions[bot]',GIT_COMMITTER_NAME='github-actions[bot]',
        GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com',
        GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com')
    with tempfile.TemporaryDirectory(prefix='hype-report-index-') as temp:
        env['GIT_INDEX_FILE']=str(Path(temp)/'index')
        for attempt in range(3):
            remote=git('ls-remote','--heads','origin','refs/heads/'+BRANCH).stdout.decode().strip()
            parent=remote.split()[0] if remote else None
            if parent:
                git('fetch','--no-tags','--no-write-fetch-head','origin',parent)
                git('read-tree',parent,env=env)
            else:
                git('read-tree','--empty',env=env)
            records=[]
            for path in sorted(out.rglob('*')):
                if path.is_file():
                    blob=git('hash-object','-w',str(path)).stdout.decode().strip()
                    dest=prefix+'/'+path.relative_to(out).as_posix()
                    records.append('100644 '+blob+'\t'+dest+'\n')
                    if path.relative_to(out).as_posix()=='status.json':
                        records.append('100644 '+blob+'\tstatus.json\n')
            git('update-index','--index-info',input=''.join(records).encode(),env=env)
            tree=git('write-tree',env=env).stdout.decode().strip()
            args=['commit-tree',tree]+(['-p',parent] if parent else [])
            commit=git(*args,input=('HYPE research '+status['stage']+' run '+status['run_id']+'\n').encode(),env=env).stdout.decode().strip()
            result=git('push','origin',commit+':refs/heads/'+BRANCH,check=False)
            if result.returncode==0:
                return commit
        raise RuntimeError('report branch publication failed after three non-force attempts')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stage',choices=['started','replay','final'],required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--reports',nargs='*',type=Path,default=[])
    args=ap.parse_args()
    status=prepare_reports(args.stage,args.output,args.reports)
    print(json.dumps({'status':'published','commit':publish(args.output,status),'branch':BRANCH}))


if __name__=='__main__':main()
