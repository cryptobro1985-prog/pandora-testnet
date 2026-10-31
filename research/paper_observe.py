"""Read-only, resumable PAPER observation; never creates orders or changes a DB.

Requires a verified deployed SHA and healthy risk endpoint before starting.
Output records sampled diagnostics separately from actual executions. Missing
samples cannot establish a missed signal, and MFE is never hypothetical PnL.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import time
import urllib.request

SYMBOLS=('INIT','NEAR','BTC','SOL','ETH','LIT','HYPE','ZEC','TAO','GRASS')


def fetch(base,path):
    req=urllib.request.Request(base.rstrip('/')+path,headers={'User-Agent':'pandora-paper-observer/1.0'})
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.load(response)


def compact(data):
    """Keep audit inputs without duplicating unrelated dashboard history."""
    primary=data.get('strategy1_primary') or {}
    def trade(row):
        fields=('symbol','opened','closed','side','entry','exit','pnl','margin','notional','leverage')
        features=row.get('features') or {}
        return {**{k:row.get(k) for k in fields},'reason':row.get('reason'),
                'features':{k:features.get(k) for k in ('entry_kind','candidate_selection',
                    'mfe_price_move','mae_price_move','mfe_roe_pct','mae_roe_pct','mfe_giveback_move')}}
    return {'strategy1_primary':{**{k:primary.get(k) for k in ('total_equity','realized_pnl','unrealized_pnl')},
             'open_positions':[trade(r) for r in primary.get('open_positions') or []],
             'closed_trades':[trade(r) for r in primary.get('closed_trades') or []]},
            'strategy1_entry_diagnostics':data.get('strategy1_entry_diagnostics') or {}}


def epoch(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):
        return None


def report(records,start,end,expected_sha,required_seconds):
    trades={};entries={};blocks={};errors=[];versions=set();ready=0
    for record in records:
        if record.get('error'):
            errors.append({'at':record['at'],'error':record['error']});continue
        data=record['dashboard'];health=record['health']
        versions.add(health.get('version'));ready+=int(bool(health.get('risk_ready')))
        primary=data.get('strategy1_primary') or {}
        closed=primary.get('closed_trades') or []
        for trade in closed:
            closed_at=epoch(trade.get('closed'))
            if trade.get('symbol') not in SYMBOLS or closed_at is None or not start<=closed_at<=end:continue
            key=(trade['symbol'],trade.get('opened'),trade.get('closed'))
            trades[key]=trade
        for trade in closed+(primary.get('open_positions') or []):
            opened=epoch(trade.get('opened'))
            if opened is not None and start<=opened<=end and trade.get('symbol') in SYMBOLS:
                entries[(trade['symbol'],trade['opened'])]=trade
        for token in (data.get('strategy1_entry_diagnostics') or {}).get('tokens',[]):
            key=(token.get('symbol'),token.get('reason'))
            blocks[key]=blocks.get(key,0)+1
    per_token={s:{'entries':0,'exits':0,'reentries':0,'realized_pnl_net_fees':0.0,'trades':[]} for s in SYMBOLS}
    for trade in entries.values():
        token=per_token[trade['symbol']];token['entries']+=1
        token['reentries']+=int((trade.get('features') or {}).get('entry_kind')=='REENTRY')
    for trade in trades.values():
        token=per_token[trade['symbol']];token['exits']+=1
        token['realized_pnl_net_fees']+=float(trade.get('pnl') or 0)
        f=trade.get('features') or {};entry=float(trade.get('entry') or 0);exit_=float(trade.get('exit') or 0)
        move=int(trade.get('side') or 0)*(exit_/entry-1) if entry>0 else None
        mfe=f.get('mfe_price_move')
        token['trades'].append({**trade,'mfe_capture_ratio':move/float(mfe) if move is not None and mfe and float(mfe)>0 else None})
    return {'started_at_utc':dt.datetime.fromtimestamp(start,dt.timezone.utc).isoformat(),
            'elapsed_seconds':end-start,'requested_seconds':required_seconds,
            'observation_complete':end-start>=required_seconds and not errors and versions=={expected_sha},
            'expected_sha':expected_sha,'observed_versions':sorted(str(v) for v in versions),
            'samples':len(records),'risk_ready_samples':ready,'errors':errors,'tokens':per_token,
            'sampled_blocking_stages':[{'symbol':k[0],'reason':k[1],'samples':v} for k,v in sorted(blocks.items())],
            'missed_signals':None,'missed_signals_limitation':'Sampled dashboard states cannot prove every actionable signal or missed entry. Use durable event-level audit for this count.',
            'pnl_basis':'actual PAPER closed ledger, entry/exit fees included; funding and slippage not modeled',
            'history_limit_warning':'Dashboard history is bounded. Deduplicated snapshots retain observed trades; outages or >300 closures between snapshots can leave gaps.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='https://pandora-testnet-monitor-nfoc.onrender.com')
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--hours',type=float,default=12)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.hours<=0:parser.error('--hours must be positive')
    args.output.mkdir(parents=True,exist_ok=True)
    health=fetch(args.base_url,'/health/risk')
    if health.get('version')!=args.expected_sha or not health.get('risk_ready'):
        raise SystemExit('Refusing to start: deployed SHA and risk heartbeat are not verified')
    manifest=args.output/'manifest.json';samples=args.output/'samples.jsonl'
    if manifest.exists():
        metadata=json.loads(manifest.read_text())
        if metadata['sha']!=args.expected_sha or metadata['base_url']!=args.base_url:
            raise SystemExit('Output belongs to another deployment; choose a new directory')
        start=float(metadata['start'])
    else:
        start=time.time();manifest.write_text(json.dumps({'start':start,'sha':args.expected_sha,'base_url':args.base_url},indent=2))
    records=[json.loads(line) for line in samples.read_text().splitlines()] if samples.exists() else []
    deadline=start+args.hours*3600
    while True:
        at=time.time()
        try:
            health=fetch(args.base_url,'/health')
            data=fetch(args.base_url,'/api/dashboard')
            if health.get('version')!=args.expected_sha:raise RuntimeError('deployment_sha_changed')
            record={'at':at,'health':health,'dashboard':compact(data)}
        except Exception as exc:
            record={'at':at,'error':type(exc).__name__+':'+str(exc)}
        with samples.open('a') as out:out.write(json.dumps(record,default=str)+'\n')
        records.append(record)
        (args.output/'report.json').write_text(json.dumps(report(records,start,time.time(),args.expected_sha,args.hours*3600),indent=2,default=str))
        remaining=deadline-time.time()
        if remaining<=0:break
        time.sleep(min(60,remaining))


if __name__=='__main__':main()
