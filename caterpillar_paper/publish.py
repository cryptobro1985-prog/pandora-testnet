"""Publish one atomic snapshot commit to a dedicated GitHub Pages branch.

gh uses injected GitHub auth; credentials never enter the published files.
"""
import base64
import json
from pathlib import Path
import re
import subprocess


def api(path, method='GET', data=None):
    cmd=['gh','api',path,'--method',method]
    if data is not None:cmd+=['--input','-']
    result=subprocess.run(cmd,input=None if data is None else json.dumps(data),text=True,capture_output=True,timeout=40)
    if result.returncode:
        raise RuntimeError('GitHub API failed for '+path+' (exit '+str(result.returncode)+')')
    return json.loads(result.stdout) if result.stdout.strip() else {}


def publish(repository,snapshot,branch='caterpillar-monitor-data'):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):
        raise ValueError('Invalid repository')
    # Read-only repo check distinguishes missing access from an absent data branch.
    api('repos/'+repository)
    prefix='repos/'+repository+'/git/'
    try:parent=api(prefix+'ref/heads/'+branch)['object']['sha']
    except RuntimeError:
        refs=api(prefix+'matching-refs/heads/'+branch)
        if refs:raise
        parent=None
    html=Path(__file__).with_name('monitor.html').read_text().replace('__REPOSITORY__',repository)
    files={'index.html':html,'state.json':json.dumps(snapshot,allow_nan=False),'.nojekyll':''}
    tree=[]
    for path,content in files.items():
        blob=api(prefix+'blobs','POST',{'content':base64.b64encode(content.encode()).decode(),'encoding':'base64'})
        tree.append({'path':path,'mode':'100644','type':'blob','sha':blob['sha']})
    newtree=api(prefix+'trees','POST',{'tree':tree})
    commit=api(prefix+'commits','POST',{'message':'PAPER snapshot '+str(snapshot['snapshot_at']),
        'tree':newtree['sha'],'parents':[parent] if parent else []})
    if parent:api(prefix+'refs/heads/'+branch,'PATCH',{'sha':commit['sha'],'force':False})
    else:api(prefix+'refs','POST',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
    return commit['sha']


def ensure_pages(repository,branch='caterpillar-monitor-data'):
    """Create Pages only when absent; never replace another site's source."""
    try:
        existing=api('repos/'+repository+'/pages')
    except RuntimeError:
        # A denied Pages read must not be mistaken for a missing site.
        result=subprocess.run(['gh','api','repos/'+repository+'/pages','--include'],capture_output=True,text=True,timeout=40)
        if 'HTTP/2.0 404' not in result.stdout and 'HTTP/1.1 404' not in result.stdout:
            raise RuntimeError('Pages access NOT VERIFIED; existing configuration preserved')
        existing=api('repos/'+repository+'/pages','POST',{'source':{'branch':branch,'path':'/'}})
    source=existing.get('source') or {}
    if source.get('branch')!=branch:
        raise RuntimeError('Existing Pages uses another source; configuration preserved')
    api('repos/'+repository+'/pages/builds','POST')
    return existing.get('html_url')
