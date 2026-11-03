"""Finite GitHub-native evidence/access check; publishes no credentials."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

from caterpillar_evidence import collect


def request(path,method='GET',data=None):
    cmd=['gh','api',path,'--method',method]
    if data is not None:cmd+=['--input','-']
    r=subprocess.run(cmd,input=None if data is None else json.dumps(data),text=True,capture_output=True,timeout=45)
    try:body=json.loads(r.stdout)
    except ValueError:body={}
    return r.returncode,body


def main():
    p=argparse.ArgumentParser();p.add_argument('repository');p.add_argument('output',type=Path);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    evidence=collect(a.repository)
    prefix='repos/'+a.repository
    code,repo=request(prefix)
    diagnostic={'repository':{k:repo.get(k) for k in ('full_name','private','visibility','has_pages','permissions')},'api_read_exit':code}
    code,pages=request(prefix+'/pages')
    diagnostic['pages']={'exit_code':code,**{k:pages.get(k) for k in ('status','html_url','message','source','build_type','public')}}
    if code and pages.get('status')=='404' and not repo.get('has_pages'):
        created_code,created=request(prefix+'/pages','POST',{'source':{'branch':'caterpillar-monitor-data','path':'/'}})
        diagnostic['pages_create']={'exit_code':created_code,**{k:created.get(k) for k in ('message','status','html_url','errors')}}
        if not created_code:pages=created
    code,runs=request(prefix+'/actions/workflows/caterpillar-paper.yml/runs?per_page=5')
    diagnostic['runs']=[{k:r.get(k) for k in ('id','status','conclusion','head_sha','html_url','head_branch')}
                        for r in runs.get('workflow_runs',[])]
    for item in diagnostic['runs']:
        _,jobs=request(prefix+'/actions/runs/'+str(item['id'])+'/jobs')
        item['jobs']=[{'name':j['name'],'status':j['status'],'conclusion':j['conclusion'],
                      'steps':[{k:s.get(k) for k in ('name','status','conclusion')} for s in j.get('steps',[])]}
                      for j in jobs.get('jobs',[])]
    urls={'bybit_rest':'https://api.bybit.com/v5/market/time',
          'public_snapshot':'https://raw.githubusercontent.com/'+a.repository+'/caterpillar-monitor-data/state.json'}
    if pages.get('html_url'):
        urls['monitor']=pages['html_url']
    for name,url in urls.items():
        try:
            with urllib.request.urlopen(url,timeout=20) as response:
                data=response.read(500000)
                diagnostic[name]={'http_status':response.status,'url':url,
                    'pandora_marker':b'PANDORA CATERPILLAR' in data if name=='monitor' else None}
                if name=='public_snapshot':
                    snap=json.loads(data);diagnostic[name].update(session_id=snap.get('session_id'),snapshot_at=snap.get('snapshot_at'),status=snap.get('status'),
                        run_id=snap.get('run_id'),positions=len(snap.get('positions',[])),active=len(snap.get('tokens',[])),equity=snap.get('portfolio',{}).get('equity'))
        except urllib.error.HTTPError as exc:
            diagnostic[name]={'http_status':exc.code,'url':url,'public_error_excerpt':exc.read(1500).decode(errors='replace')}
        except Exception as exc:diagnostic[name]={'error':str(exc)[:200],'url':url}
    observed=diagnostic.get('public_snapshot',{})
    denied=diagnostic.get('bybit_rest',{}).get('public_error_excerpt','')
    # Stop only our confirmed empty, blocked PAPER run. Preserve its checkpoint
    # through its signal handler and always() artifact step; no real orders exist.
    if 'block access from your country' in denied and observed.get('positions')==0 and observed.get('active')==0:
        for item in diagnostic['runs']:
            if (item['status']=='in_progress' and item['head_branch']=='caterpillar-paper-runtime-v1'
                    and str(item['id'])==str(observed.get('run_id'))):
                exit_code,result=request(prefix+'/actions/runs/'+str(item['id'])+'/cancel','POST')
                diagnostic['stopped_empty_blocked_run']={'id':item['id'],'request_exit':exit_code,'message':result.get('message')}
    for name,value in [('evidence.json',evidence),('diagnostics.json',diagnostic)]:
        (a.output/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    # This branch is owned by the finite diagnostic workflow, not the live publisher.
    branch='caterpillar-runtime-evidence'; git=prefix+'/git/'
    code,ref=request(git+'ref/heads/'+branch)
    parent=ref.get('object',{}).get('sha') if code==0 else None
    tree=[]
    for filename in ('evidence.json','diagnostics.json'):
        code,blob=request(git+'blobs','POST',{'content':base64.b64encode((a.output/filename).read_bytes()).decode(),'encoding':'base64'})
        if code:raise RuntimeError('Cannot publish evidence blob')
        tree.append({'path':filename,'mode':'100644','type':'blob','sha':blob['sha']})
    code,newtree=request(git+'trees','POST',{'tree':tree})
    if code:raise RuntimeError('Cannot publish evidence tree')
    code,commit=request(git+'commits','POST',{'message':'Caterpillar source evidence and actual access checks',
        'tree':newtree['sha'],'parents':[parent] if parent else []})
    if code:raise RuntimeError('Cannot publish evidence commit')
    if parent:code,_=request(git+'refs/heads/'+branch,'PATCH',{'sha':commit['sha'],'force':False})
    else:code,_=request(git+'refs','POST',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
    if code:raise RuntimeError('Cannot publish evidence ref')
    print(json.dumps({'evidence_status':evidence['status'],'diagnostics':diagnostic},indent=2))


if __name__=='__main__':main()
