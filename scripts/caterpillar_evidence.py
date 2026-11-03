"""Retrieve small existing synthesis artifacts; never rerun 30-day research."""
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def api(path):
    result=subprocess.run(['gh','api',path],capture_output=True,timeout=60)
    if result.returncode:raise RuntimeError('GitHub API unavailable: '+path)
    return result.stdout


def collect(repository):
    prefix='repos/'+repository+'/actions/'
    out={'status':'NOT VERIFIED','runs':{},'tokens':{},'issues':[]}
    for run_id in ('41601978354','41659751109'):
        try:
            run=json.loads(api(prefix+'runs/'+run_id))
            out['runs'][run_id]={k:run.get(k) for k in ('head_sha','status','conclusion','html_url','name')}
        except Exception as e:out['issues'].append(str(e))
    try:artifacts=json.loads(api(prefix+'runs/41659751109/artifacts?per_page=100'))['artifacts']
    except Exception as e:
        out['issues'].append(str(e)); return out
    for symbol in ('AAVE','DOGE','SUI','WLD','1000PEPE'):
        matching=[a for a in artifacts if a['name']=='caterpillar-evidence-'+symbol and not a['expired']]
        if len(matching)!=1 or matching[0]['size_in_bytes']>10_000_000:
            out['issues'].append('Missing/expired/oversized synthesis artifact: '+symbol); continue
        artifact=matching[0]
        try:
            with zipfile.ZipFile(io.BytesIO(api(prefix+'artifacts/'+str(artifact['id'])+'/zip'))) as z:
                found=[n for n in z.namelist() if n=='evidence.json']
                if len(found)!=1 or z.getinfo(found[0]).file_size>20_000_000:raise ValueError('Invalid evidence archive')
                data=json.loads(z.read(found[0]))
            if data.get('symbol')!=symbol:raise ValueError('Evidence symbol mismatch')
            out['tokens'][symbol]={'artifact_id':artifact['id'],'evidence':data}
        except Exception as e:out['issues'].append(symbol+': '+str(e))
    out['status']='RETRIEVED_NOT_STRATEGY_VALIDATED' if len(out['tokens'])==5 else 'PARTIAL'
    out['rule_changes_applied']=False
    return out


if __name__=='__main__':
    repository=sys.argv[1]; target=Path(sys.argv[2]); target.parent.mkdir(parents=True,exist_ok=True)
    result=collect(repository); target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'tokens':list(result['tokens']),'issues':result['issues']}))
