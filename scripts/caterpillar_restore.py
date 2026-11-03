"""Restore only an artifact from a completed run of this exact workflow/branch."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile
import io
import os


def gh(path):
    return subprocess.check_output(['gh','api',path],timeout=45)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repository',required=True); p.add_argument('--branch',required=True)
    p.add_argument('--run-id',default=''); a=p.parse_args()
    prefix='repos/'+a.repository+'/actions/'
    if a.run_id:
        runs=[json.loads(gh(prefix+'runs/'+a.run_id))]
    else:
        runs=json.loads(gh(prefix+'workflows/caterpillar-paper.yml/runs?status=completed&per_page=30'))['workflow_runs']
    for run in runs:
        if run['head_branch']!=a.branch or str(run['id'])==os.getenv('GITHUB_RUN_ID'):continue
        artifacts=json.loads(gh(prefix+'runs/'+str(run['id'])+'/artifacts'))['artifacts']
        found=[r for r in artifacts if r['name']=='caterpillar-checkpoint' and not r['expired']]
        if not found:continue
        payload=gh(prefix+'artifacts/'+str(found[0]['id'])+'/zip')
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            names=[n for n in z.namelist() if n=='checkpoint.json']
            if len(names)!=1:raise ValueError('Artifact lacks an unambiguous checkpoint')
            a.output.mkdir(parents=True,exist_ok=True)
            target=a.output/'checkpoint.json'; target.write_bytes(z.read(names[0]))
            print('Restored checkpoint from run '+str(run['id'])); return
    if a.run_id:raise RuntimeError('Requested run has no matching usable checkpoint')
    print('No prior checkpoint: starting a new session')


if __name__=='__main__':main()
