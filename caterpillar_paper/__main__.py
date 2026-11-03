import argparse
import fcntl
import json
import os
from pathlib import Path
import queue
import signal
import threading
import time

from .config import Config
from .engine import Engine
from .market import Scanner, StreamBridge, get_json, instruments, h1_history
from .storage import Store, atomic_json
from .publish import publish, ensure_pages


def main():
    parser=argparse.ArgumentParser(description='Public-data-only Caterpillar PAPER runtime')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--minutes',type=float,default=320)
    parser.add_argument('--restore',type=Path)
    parser.add_argument('--publish-repository')
    parser.add_argument('--session-id')
    parser.add_argument('--startup-timeout',type=float,default=180,
                        help='Health deadline for first fresh complete market snapshot, not a trading cooldown')
    args=parser.parse_args()
    if not 0<args.minutes<=330:parser.error('--minutes must be in (0,330]')
    if not 1<=args.startup_timeout<=1800:parser.error('--startup-timeout must be in [1,1800] seconds')
    args.output.mkdir(parents=True,exist_ok=True)
    lock=(args.output/'runtime.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    store=Store(args.output)
    if args.restore:store.restore(args.restore)
    cfg=Config.from_env()
    engine=Engine(cfg,store,run_id=os.getenv('GITHUB_RUN_ID','local'),session_id=args.session_id)
    messages=queue.Queue(maxsize=50000); stop=threading.Event(); scanner=Scanner(cfg)
    errors={}; transport={}; active=list(engine.s['active']); active_lock=threading.Lock()

    def selected():
        with active_lock:return set(active)

    def markets():
        universe={}; last_universe=0
        while not stop.is_set():
            try:
                now=time.time()
                if now-last_universe>3600 or not universe:
                    universe=instruments(); last_universe=now
                data=get_json('/v5/market/tickers',category='linear')['list']
                ranking=scanner.rank(data,universe,time.time())
                messages.put(('scanner',(ranking,universe)),timeout=5)
            except Exception as exc:
                messages.put(('error',('scanner',type(exc).__name__+': '+str(exc)[:180])),timeout=5)
            for symbol in sorted(selected()):
                if stop.is_set():break
                try:messages.put(('h1',(symbol,h1_history(symbol),time.time())),timeout=5)
                except Exception as exc:
                    messages.put(('error',('h1:'+symbol,type(exc).__name__+': '+str(exc)[:180])),timeout=5)
            stop.wait(cfg.scanner_seconds)

    for name,callback in [('market-rest',markets),('public-trades',lambda:StreamBridge(messages).run(stop,selected))]:
        threading.Thread(target=callback,name=name,daemon=True).start()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    started_mono=time.monotonic(); deadline=started_mono+args.minutes*60
    last_snapshot=last_checkpoint=last_publish=0.; publisher=None; published=[]
    stream_generation=None

    def publish_async(snapshot):
        try:
            commit=publish(args.publish_repository,snapshot)
            if not any(row[0]=='ok' for row in published):
                url=ensure_pages(args.publish_repository)
                print('Pages configured: '+str(url)+'; URL still requires external verification',flush=True)
            published.append(('ok',commit))
        except Exception as exc:published.append(('error',str(exc)))

    snapshot={}; fatal=False; market_ready_once=False
    evidence_file=args.output/'research-evidence.json'
    evidence=json.loads(evidence_file.read_text()) if evidence_file.exists() else {'status':'NOT VERIFIED','tokens':{}}
    try:
        while not stop.is_set() and time.monotonic()<deadline:
            now=time.time()
            try:
                kind,data=messages.get(timeout=.1)
                try:
                    if kind=='trade':
                        row,received,generation=data
                        if stream_generation!=generation:
                            engine.reset_flow(engine.s['active'],True,received)
                            stream_generation=generation
                        engine.on_trade(row['coin'],float(row['time'])/1000,float(row['px']),float(row['sz']),
                                        1 if row['side']=='B' else -1,str(row['tid']),received)
                    elif kind=='connection':engine.reset_flow(*data)
                    elif kind=='transport':transport=data
                    elif kind=='h1':
                        engine.seed_h1(*data); errors.pop('h1:'+data[0],None); errors.pop('h1',None)
                    elif kind=='scanner':
                        ranking,universe=data; engine.s['scanner']=ranking; errors.pop('scanner',None)
                        symbols=list(engine.s['active']) or list(cfg.paper_symbols) or [r['symbol'] for r in ranking['candidates'][:5]]
                        if len(symbols)==5:
                            selections={r['symbol']:r for r in ranking['candidates']}
                            if cfg.paper_symbols:selections.update({s:{'reason':'MANUAL_PAPER_SYMBOLS','observed_at':now} for s in cfg.paper_symbols})
                            engine.set_active(symbols,selections,universe,now)
                            with active_lock:active[:]=engine.s['active']
                    elif kind=='error':
                        errors[data[0]]=data[1]
                        if data[0].startswith('h1:'):engine._memory(data[0].split(':',1)[1])['h1_verified']=False
                except (ValueError,KeyError,TypeError,OverflowError) as exc:
                    # Malformed one-symbol market data must not kill other symbols.
                    errors[kind]=type(exc).__name__+': '+str(exc)[:180]
                    if kind=='h1':engine._memory(data[0])['h1_verified']=False
            except queue.Empty:pass
            if now-last_checkpoint>=cfg.checkpoint_seconds:
                engine.checkpoint(); last_checkpoint=now
            if now-last_snapshot>=cfg.snapshot_seconds:
                snapshot=engine.snapshot(now)
                snapshot.update(errors=dict(errors),transport=transport,queue_depth=messages.qsize(),publication=published[-1:] or [])
                snapshot['research_evidence']={'status':evidence['status'],'tokens':list(evidence.get('tokens',{})),
                    'rule_changes_applied':False,'issues':evidence.get('issues',[])}
                if errors:snapshot['status']='ERROR'
                market_ready_once=market_ready_once or snapshot['status']=='ONLINE'
                atomic_json(args.output/'state.json',snapshot); last_snapshot=now
                print(json.dumps({'timestamp':now,'status':snapshot['status'],'session_id':engine.s['session_id'],
                    'active':engine.s['active'],'positions':len(snapshot['positions']),
                    'equity':snapshot['portfolio']['equity'],'errors':errors},allow_nan=False),flush=True)
            if args.publish_repository and now-last_publish>=cfg.publish_seconds and (publisher is None or not publisher.is_alive()):
                publisher=threading.Thread(target=publish_async,args=(snapshot,),daemon=True); publisher.start(); last_publish=now
            if not market_ready_once and time.monotonic()-started_mono>args.startup_timeout:
                errors['startup']='NO_FRESH_COMPLETE_MARKET_SNAPSHOT_WITHIN_HEALTH_DEADLINE'
                fatal=True; break
    except Exception:
        fatal=True; raise
    finally:
        stop.set(); engine.checkpoint()
        snapshot=engine.snapshot(); snapshot.update(status='ERROR' if fatal else 'OFFLINE',errors=errors,transport=transport)
        atomic_json(args.output/'state.json',snapshot)
        if args.publish_repository:
            if publisher:publisher.join(45)
            try:publish(args.publish_repository,snapshot)
            except Exception as exc:print('Final publication failed: '+str(exc),flush=True)
        store.db.close(); lock.close()
    return 2 if fatal else 0


if __name__=='__main__':raise SystemExit(main())
