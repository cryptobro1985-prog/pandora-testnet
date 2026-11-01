"""Persistent PAPER orchestration. No private exchange endpoints or order API."""
import copy
import json
import time

from pandora_scanner import LiveScanner
from pandora_locals import execution_anchor
from pandora_win_core import allocation, pyramid_decision, apply_add, mark_metrics


class PandoraRuntime:
    def __init__(self, app):
        self.a=app;self.scanner=LiveScanner(candidate_limit=int(app.os.getenv('PANDORA_SCAN_CANDIDATES','30')))
        self.max_adds=int(app.os.getenv('PANDORA_MAX_ADDS','2'))
        self.add_fraction=float(app.os.getenv('PANDORA_ADD_MARGIN_FRACTION','0.10'))
        self.position_fraction=float(app.os.getenv('PANDORA_MAX_POSITION_MARGIN_FRACTION','0.40'))
        if not 0<=self.max_adds<=20 or not 0<self.add_fraction<=self.position_fraction<=1:
            raise ValueError('invalid explicit pyramiding risk configuration')
        self.tokens={};self.last_saved={};self.max_equity=500.;self.last_scanner_save=0
        self.max_equity=max(self.max_equity,float(app.S.get('local_experiment_equity',500)))
        with app.pg() as db:
            db.execute("create table if not exists pandora_token_state(symbol text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_runtime_state(name text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_pyramid_adds(id bigserial primary key,symbol text not null,opened text not null,add_number integer not null,payload jsonb not null,unique(symbol,opened,add_number))")
            for row in db.execute('select symbol,payload from pandora_token_state').fetchall():self.tokens[row['symbol']]=row['payload']
            for row in db.execute('select name,payload from pandora_runtime_state').fetchall():
                if row['name']=='scanner':
                    self.scanner.restore(row['payload'])
                    app.S['bybit_discovery']=copy.deepcopy(row['payload'])
                elif row['name']=='account':self.max_equity=float(row['payload'].get('max_equity',500))

    def event(self,db,action,symbol,reason,context):
        self.a.STORE.fence(db)
        payload=dict(symbol=symbol,action=action,reason=reason,market_context=context,mode='PAPER_ONLY')
        db.execute("insert into audit_journal(recorded_at,kind,payload) values(%s,%s,%s::jsonb)",
                   (self.a.now(),'pandora_'+action,json.dumps(payload,default=str)))

    def save_token(self,db,symbol,state):
        db.execute("insert into pandora_token_state(symbol,payload) values(%s,%s::jsonb) on conflict(symbol) do update set payload=excluded.payload,updated_at=clock_timestamp()",
                   (symbol,json.dumps(state,default=str)))

    def transition(self,symbol,phase,action,reason,context,force=False):
        a=self.a;stamp=time.time();previous=self.tokens.get(symbol,{})
        changed=previous.get('state')!=phase or previous.get('action')!=action or previous.get('reason')!=reason
        state={**previous,'state':phase,'action':action,'reason':reason,'at':a.now(),'context':context}
        if not force and not changed and stamp-self.last_saved.get(symbol,0)<5:
            self.tokens[symbol]=state;return
        with a.pg() as db:
            with db.transaction():
                a.STORE.fence(db)
                self.save_token(db,symbol,state)
                # HOLD/WAIT are recorded on each new context or at least every 5s,
                # not on every millisecond packet. The full state is checkpointed.
                self.event(db,action,symbol,reason,context)
        with a.LOCK:self.tokens[symbol]=state
        self.last_saved[symbol]=stamp

    def scanner_snapshot(self,snapshot):
        a=self.a
        if not a.S.get('engine_active'):return
        changed=bool(snapshot.get('events'))
        if not changed and time.time()-self.last_scanner_save<5:return
        with a.pg() as db:
            with db.transaction():
                a.STORE.fence(db)
                db.execute("insert into pandora_runtime_state(name,payload) values('scanner',%s::jsonb) on conflict(name) do update set payload=excluded.payload,updated_at=clock_timestamp()",(json.dumps(snapshot),))
                for event in snapshot.get('events',[]):
                    self.event(db,event['action'],event['symbol'],event['reason'],snapshot)
                    if event.get('state')=='ROTATE_OUT':
                        self.event(db,'ROTATE_OUT',event['symbol'],'no_position_and_activity_faded',event)
                        db.execute('delete from local_v12_watchlist where symbol=%s',(event['symbol'],))
                        with a.LOCK:a.S.get('local_experiment_watch',{}).pop(event['symbol'],None)
        self.last_scanner_save=time.time()

    def semantic_open(self,db,symbol,position):
        side='LONG' if position['side']>0 else 'SHORT'
        previous=self.tokens.get(symbol,{})
        prior_side=previous.get('last_closed_side')
        kind=position['features'].get('entry_kind')
        action=('REENTRY_'+side if kind=='REENTRY' else
                'REVERSE_'+('LONG_TO_SHORT' if position['side']<0 else 'SHORT_TO_LONG')
                if prior_side and prior_side!=position['side'] else 'OPEN_'+side)
        self.event(db,action,symbol,'structure_and_fresh_executed_control',position)
        state={**previous,'state':side,'action':action,'last_position_side':position['side'],'reason':'structure_and_fresh_executed_control'}
        self.save_token(db,symbol,state)
        # Publish memory only after caller commits via normal cycle/restore.

    def semantic_close(self,db,symbol,position,reason,price,pnl,watch):
        side='LONG' if position['side']>0 else 'SHORT'
        self.event(db,'CLOSE_'+side,symbol,reason,dict(position=position,exit=price,pnl=pnl,watch=watch))
        state={**self.tokens.get(symbol,{}),'state':'WAIT_REENTRY' if watch else 'SELECTED',
               'action':'CLOSE_'+side,'last_closed_side':position['side'],'last_closed_reason':reason,
               'last_closed_price':price,'last_closed_at':self.a.now()}
        self.save_token(db,symbol,state)

    def reload_token(self,symbol):
        with self.a.pg() as db:
            row=db.execute('select payload from pandora_token_state where symbol=%s',(symbol,)).fetchone()
        if row:
            with self.a.LOCK:self.tokens[symbol]=row['payload']

    def refresh_after_lease(self):
        """A standby may have restored before the previous writer's final commit."""
        with self.a.pg() as db:
            tokens={r['symbol']:r['payload'] for r in db.execute('select symbol,payload from pandora_token_state').fetchall()}
            account=db.execute("select payload from pandora_runtime_state where name='account'").fetchone()
        with self.a.LOCK:
            self.tokens=tokens
            self.a.S['_local_h1_runtime_verified']={}
        if account:self.max_equity=max(self.max_equity,float(account['payload'].get('max_equity',500)))

    def pyramid(self,symbol,analysis,flow,mark):
        a=self.a
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active') or a.S.get('orders_enabled') or a.S.get('mode')!='PAPER_ONLY':return False
            if not a.strategy1_runtime_h1_verified(symbol,analysis):return False
            price=a.current_entry_price(symbol)
            if price is None or price!=mark:return False
            position=copy.deepcopy(a.S.get('local_v12_positions',{}).get(symbol))
            if not position:return False
            instrument=a.S.get('_bybit_instruments',{}).get(symbol,{})
            if time.time()-float(instrument.get('observed_at',0))>86400 or float(instrument.get('max_leverage',0))<position['leverage']:return False
            ready,state=pyramid_decision(position,analysis,flow,mark,self.max_adds)
            if not ready:
                with a.LOCK:
                    live=a.S.get('local_v12_positions',{}).get(symbol)
                    if live and live['opened']==position['opened']:
                        live.setdefault('features',{})['pyramid_state']=state
                return False
            equity,used,free=a._local_experiment_margin_state()
            headroom=max(0.,equity*self.position_fraction-float(position['margin']))
            margin=min(equity*self.add_fraction,headroom,free/(1+2*a.FEE*position['leverage']))
            if margin<.01:return False
            updated,record=apply_add(position,mark,margin,flow,analysis,a.now())
            updated=mark_metrics(updated,mark,flow,analysis,a.FEE)
            record['mfe_after_add']=updated['features']['peak_mfe_usd']
            updated['features']['pyramid_adds'][-1]['mfe_after_add']=record['mfe_after_add']
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db)
                    row=db.execute("insert into pandora_pyramid_adds(symbol,opened,add_number,payload) values(%s,%s,%s,%s::jsonb) on conflict do nothing returning id",
                        (symbol,position['opened'],record['add_number'],json.dumps(record))).fetchone()
                    if not row:return False
                    result=db.execute("update local_v12_positions set entry=%s,notional=%s,margin=%s,features=%s::jsonb where symbol=%s and opened=%s returning symbol",
                        (updated['entry'],updated['notional'],updated['margin'],json.dumps(updated['features']),symbol,position['opened'])).fetchone()
                    if not result:raise RuntimeError('pyramid_position_changed')
                    self.event(db,'ADD_LONG' if position['side']>0 else 'ADD_SHORT',symbol,'profitable_stronger_executed_impulse',record)
            with a.LOCK:a.S['local_v12_positions'][symbol]=updated
            return True

    def cycle(self,prices):
        a=self.a
        if not a.S.get('engine_active'):return
        with a.LOCK:
            selected=set((a.S.get('bybit_discovery') or {}).get('selected_symbols') or [])
            symbols=set(a.strategy1_trade_symbols())|{s for s,t in self.tokens.items() if t.get('state')!='ROTATE_OUT'}
        for symbol in sorted(symbols):
            with a.LOCK:
                pos=copy.deepcopy(a.S.get('local_v12_positions',{}).get(symbol))
                analysis=copy.deepcopy(a.S.get('_local4_analysis',{}).get(symbol) or {})
            flow=a.MARKET_OBS.flow_context(symbol);mark=a.current_entry_price(symbol)
            context=dict(flow=flow,local=analysis,mark=mark,selected=symbol in selected)
            if symbol not in selected and not pos:
                if symbol in a.S.get('local_experiment_watch',{}):a._local_experiment_watch_clear(symbol,'token_rotated_out')
                if self.tokens.get(symbol,{}).get('state')!='ROTATE_OUT':self.transition(symbol,'ROTATE_OUT','ROTATE_OUT','no_position_and_not_selected',context)
                continue
            if not flow.get('trade_data_fresh') or mark is None:
                self.transition(symbol,'WAIT_REENTRY' if not pos else ('LONG' if pos['side']>0 else 'SHORT'),
                    'FLOW_STALE','fresh_executed_trade_and_mark_required',context)
                continue
            if pos:
                # The existing causal pressure structure absorbs small bounces.
                a.local_experiment_mark_positions({symbol:mark})
                if symbol not in a.S['local_v12_positions']:
                    self.reload_token(symbol)
                    continue
                pos=mark_metrics(a.S['local_v12_positions'][symbol],mark,flow,analysis,a.FEE)
                with a.LOCK:a.S['local_v12_positions'][symbol]=pos
                if time.time()-self.last_saved.get('position:'+symbol,0)>=1:
                    with a.pg() as db:
                        with db.transaction():
                            a.STORE.fence(db)
                            db.execute('update local_v12_positions set features=%s::jsonb where symbol=%s and opened=%s',
                                (json.dumps(pos['features']),symbol,pos['opened']))
                    self.last_saved['position:'+symbol]=time.time()
                side='LONG' if pos['side']>0 else 'SHORT'
                added=symbol in selected and self.pyramid(symbol,analysis,flow,mark)
                weakening=(flow.get('dominance_side')==-pos['side'] or flow.get('buy_absorbed' if pos['side']>0 else 'sell_absorbed'))
                phase=side+'_PYRAMID' if added else side+'_WEAKENING' if weakening else side
                self.transition(symbol,phase,'HOLD','confirmed_continuation_add' if added else 'observe_counterpressure' if weakening else 'same_side_control_or_no_confirmed_transfer',context)
            else:
                if analysis.get('entry_blocked') and analysis.get('forming_local'):
                    forming=analysis['forming_local']
                    self.transition(symbol,'FORMING_'+forming['pivot_type'],forming['pivot_type']+'_FORMING',
                        'old_anchor_extended_waiting_for_structure_confirmation',context)
                    continue
                if not a.strategy1_runtime_h1_verified(symbol,analysis):
                    forming=analysis.get('forming_local') or {}
                    phase='FORMING_'+forming['pivot_type'] if forming else 'SELECTED'
                    self.transition(symbol,phase,'WAIT','fresh_local_structure_required',context);continue
                before=set(a.S['local_v12_positions'])
                a.local4_fast_entries({symbol:mark})
                if symbol in a.S['local_v12_positions'] and symbol not in before:
                    self.reload_token(symbol)
                else:
                    phase='WAIT_REENTRY' if symbol in a.S.get('local_experiment_watch',{}) else ('LONG_READY' if analysis.get('entry_side')==1 else 'SHORT_READY')
                    self.transition(symbol,phase,'WAIT','waiting_for_executed_control_or_resumption',context)
        equity,used,free=a._local_experiment_margin_state()
        self.max_equity=max(self.max_equity,equity)
        with a.LOCK:a.S['pandora_account']=dict(max_equity=self.max_equity,current_exposure=sum(p['notional'] for p in a.S['local_v12_positions'].values()),used_margin=used,free_margin=free)
        if time.time()-self.last_saved.get('account',0)>=5:
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db)
                    db.execute("insert into pandora_runtime_state(name,payload) values('account',%s::jsonb) on conflict(name) do update set payload=excluded.payload,updated_at=clock_timestamp()",(json.dumps(a.S['pandora_account']),))
            self.last_saved['account']=time.time()

    def snapshot(self):
        with self.a.LOCK:tokens=copy.deepcopy(self.tokens)
        return dict(tokens=tokens,max_equity=self.max_equity,
                    pyramiding=dict(max_adds=self.max_adds,add_margin_fraction=self.add_fraction,
                                    max_position_margin_fraction=self.position_fraction))
