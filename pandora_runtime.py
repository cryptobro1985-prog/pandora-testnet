"""Persistent PAPER orchestration. No private exchange endpoints or order API."""
import copy
import json
import time

from engine_store import LeaseLost
from pandora_scanner import LiveScanner
from pandora_flow_v2_live import enabled as v2_enabled, analysis_for_flow as v2_analysis, entry_candidate as v2_candidate
from pandora_locals import execution_anchor
from pandora_win_core import allocation, pyramid_decision, apply_add, mark_metrics
from pandora_risk import RiskPolicy, plan_add, position_risk, signal_strength


class PandoraRuntime:
    def __init__(self, app):
        self.a=app;self.scanner=LiveScanner(candidate_limit=int(app.os.getenv('PANDORA_SCAN_CANDIDATES','30')))
        self.max_adds=int(app.os.getenv('PANDORA_MAX_ADDS','4'))
        self.add_fraction=float(app.os.getenv('PANDORA_ADD_MARGIN_FRACTION','0.10'))
        self.position_fraction=float(app.os.getenv('PANDORA_MAX_POSITION_MARGIN_FRACTION','0.40'))
        if not 0<=self.max_adds<=20 or not 0<self.add_fraction<=self.position_fraction<=1:
            raise ValueError('invalid explicit pyramiding risk configuration')
        self.tokens={};self.last_saved={};self.max_equity=400. if v2_enabled() else 500.;self.last_scanner_save=0;self.last_scanner_at=0
        self.max_equity=max(self.max_equity,float(app.S.get('pandora_equity',400 if v2_enabled() else 500)))
        with app.pg() as db:
            db.execute("create table if not exists pandora_win_token_state(symbol text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_win_runtime_state(name text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_win_pyramid_adds(id bigserial primary key,symbol text not null,opened text not null,add_number integer not null,payload jsonb not null,unique(symbol,opened,add_number))")
            for row in db.execute('select symbol,payload from pandora_win_token_state').fetchall():self.tokens[row['symbol']]=row['payload']
            for row in db.execute('select name,payload from pandora_win_runtime_state').fetchall():
                if row['name']=='scanner':
                    self.scanner.restore(row['payload'])
                    app.S['bybit_discovery']=copy.deepcopy(row['payload'])
                elif row['name']=='account':self.max_equity=max(self.max_equity,float(row['payload'].get('max_equity',500)))

    def event(self,db,action,symbol,reason,context):
        self.a.STORE.fence(db)
        payload=dict(symbol=symbol,action=action,reason=reason,market_context=context,mode='PAPER_ONLY')
        db.execute("insert into pandora_win_audit_journal(recorded_at,kind,payload) values(%s,%s,%s::jsonb)",
                   (self.a.now(),'pandora_'+action,json.dumps(payload,default=str)))

    def save_token(self,db,symbol,state):
        db.execute("insert into pandora_win_token_state(symbol,payload) values(%s,%s::jsonb) on conflict(symbol) do update set payload=excluded.payload,updated_at=clock_timestamp()",
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
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active'):return False
            snapshot=copy.deepcopy(snapshot)
            observed=float(snapshot.get('at') or 0)
            if observed<float(getattr(self,'last_scanner_at',0)):return False
            with a.LOCK:
                held=set(a.S.get('pandora_win_positions',{}))
                selected=set(snapshot.get('selected_symbols') or ())
                watches=copy.deepcopy(a.S.get('pandora_watch',{}))
            snapshot['retained_open_positions']=sorted(held-selected)
            states=snapshot.setdefault('states',{})
            for symbol in held-selected:states[symbol]='FADING'
            to_clear={}
            for event in snapshot.get('events',[]):
                if event.get('state')=='ROTATE_OUT' and event['symbol'] in held:
                    event['state']='FADING'
                if event.get('state')=='ROTATE_OUT' and event['symbol'] not in selected:
                    to_clear[event['symbol']]=watches.get(event['symbol'])
            changed=bool(snapshot.get('events'))
            save=changed or time.time()-self.last_scanner_save>=5
            if save:
                with a.pg() as db:
                    with db.transaction():
                        a.STORE.fence(db)
                        db.execute("insert into pandora_win_runtime_state(name,payload) values('scanner',%s::jsonb) on conflict(name) do update set payload=excluded.payload,updated_at=clock_timestamp()",(json.dumps(snapshot),))
                        for event in snapshot.get('events',[]):
                            self.event(db,event['action'],event['symbol'],event['reason'],snapshot)
                            if event['symbol'] in to_clear:
                                if event['action']!='ROTATE_OUT':
                                    self.event(db,'ROTATE_OUT',event['symbol'],'no_position_and_activity_faded',event)
                                db.execute('delete from pandora_win_watchlist where symbol=%s',(event['symbol'],))
                self.last_scanner_save=time.time()
            # A failed commit must not erase a live watch or publish the failed
            # selection. Account serialization also prevents rotation/entry races.
            with a.LOCK:
                for symbol,previous in to_clear.items():
                    if a.S.get('pandora_watch',{}).get(symbol)==previous:
                        a.S.get('pandora_watch',{}).pop(symbol,None)
                a.S['bybit_discovery']=snapshot
            self.last_scanner_at=observed
            return True

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
            row=db.execute('select payload from pandora_win_token_state where symbol=%s',(symbol,)).fetchone()
        if row:
            with self.a.LOCK:self.tokens[symbol]=row['payload']

    def refresh_after_lease(self):
        """A standby may have restored before the previous writer's final commit."""
        with self.a.pg() as db:
            tokens={r['symbol']:r['payload'] for r in db.execute('select symbol,payload from pandora_win_token_state').fetchall()}
            account=db.execute("select payload from pandora_win_runtime_state where name='account'").fetchone()
        with self.a.LOCK:
            self.tokens=tokens
            self.a.S['_pandora_h1_runtime_verified']={}
        if account:self.max_equity=max(self.max_equity,float(account['payload'].get('max_equity',500)))

    def pyramid(self,symbol,analysis,flow,mark):
        a=self.a
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active') or a.S.get('orders_enabled') or a.S.get('mode')!='PAPER_ONLY':return False
            if not v2_enabled() and not a.pandora_runtime_h1_verified(symbol,analysis):return False
            if not v2_enabled() and not self.scanner.entry_liquidity_ready(symbol):return False
            price=a.current_entry_price(symbol)
            if price is None or price!=mark:return False
            position=copy.deepcopy(a.S.get('pandora_win_positions',{}).get(symbol))
            if not position:return False
            instrument=a.S.get('_bybit_instruments',{}).get(symbol,{})
            if time.time()-float(instrument.get('observed_at',0))>86400 or float(instrument.get('max_leverage',0))<position['leverage']:return False
            ready,state=pyramid_decision(position,analysis,flow,mark,self.max_adds)
            if not ready:
                with a.LOCK:
                    live=a.S.get('pandora_win_positions',{}).get(symbol)
                    if live and live['opened']==position['opened']:
                        live.setdefault('features',{})['pyramid_state']=state
                return False
            policy=RiskPolicy.from_env()
            # Re-read at allocation time; the caller's earlier flow is not proof
            # that the trade tape is still fresh after preceding DB work.
            fresh_flow=a.MARKET_OBS.flow_context(symbol)
            if not pyramid_decision(position,analysis,fresh_flow,mark,self.max_adds)[0]:return False
            flow=fresh_flow
            risk=a.risk_snapshot(policy)
            if not risk['allowed']:return False
            equity=risk['equity'];free=risk['free_margin']
            add_request_fraction=self.add_fraction*(.5+signal_strength(position['side'],analysis,flow))
            plan=plan_add(position,mark,equity*add_request_fraction,equity,free,
                float(instrument['max_leverage']),analysis,flow,risk['portfolio_risk'],policy)
            if not plan.allowed:return False
            updated,record=apply_add(position,mark,plan.added_margin,flow,analysis,a.now(),
                added_notional=plan.added_notional,total_margin=plan.margin,leverage=plan.leverage)
            updated['features']['risk_plan']=plan.to_dict()
            record['risk_plan']=plan.to_dict()
            record['requested_margin_fraction']=add_request_fraction
            record['equity_at_add']=equity
            updated=mark_metrics(updated,mark,flow,analysis,a.FEE)
            record['mfe_after_add']=updated['features']['peak_mfe_usd']
            updated['features']['pyramid_adds'][-1]['mfe_after_add']=record['mfe_after_add']
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db)
                    row=db.execute("insert into pandora_win_pyramid_adds(symbol,opened,add_number,payload) values(%s,%s,%s,%s::jsonb) on conflict do nothing returning id",
                        (symbol,position['opened'],record['add_number'],json.dumps(record))).fetchone()
                    if not row:return False
                    result=db.execute("update pandora_win_positions set entry=%s,notional=%s,margin=%s,leverage=%s,features=%s::jsonb where symbol=%s and opened=%s returning symbol",
                        (updated['entry'],updated['notional'],updated['margin'],updated['leverage'],json.dumps(updated['features']),symbol,position['opened'])).fetchone()
                    if not result:raise RuntimeError('pyramid_position_changed')
                    self.event(db,'ADD_LONG' if position['side']>0 else 'ADD_SHORT',symbol,'profitable_stronger_executed_impulse',record)
            with a.LOCK:a.S['pandora_win_positions'][symbol]=updated
            return True

    def cycle(self,prices):
        a=self.a
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active'):return
            with a.LOCK:
                a.S['_execution_started_epoch']=time.time()
                a.S['_execution_running']=True
                a.S['_execution_errors']={}
            try:
                self._cycle(prices)
            except Exception as exc:
                with a.LOCK:
                    a.S['_execution_errors']['__cycle__']=type(exc).__name__+':'+str(exc)[:160]
                raise
            finally:
                with a.LOCK:
                    a.S['_execution_running']=False
                    a.S['_execution_heartbeat']=time.time()
                    a.S['_execution_ok']=not bool(a.S['_execution_errors'])

    def _cycle(self,prices):
        a=self.a
        with a.LOCK:
            symbols=set(a.pandora_trade_symbols())|{s for s,t in self.tokens.items() if t.get('state')!='ROTATE_OUT'}
        held=set(a.S.get('pandora_win_positions',{}))
        for symbol in sorted(symbols,key=lambda s:(s not in held,s)):
            try:
                self._cycle_symbol(symbol,prices)
            except LeaseLost:
                raise
            except Exception as exc:
                # One malformed token or unavailable row must not prevent risk
                # reduction for every other open position in this iteration.
                error=type(exc).__name__+':'+str(exc)[:160]
                with a.LOCK:
                    a.S['_execution_errors'][symbol]=error
                    a.S.setdefault('sources',{})['PandoraToken:'+symbol]={'ok':False,'error':error,'at':a.now()}
        equity,used,free=a._pandora_margin_state()
        if hasattr(a,'risk_snapshot'):a.risk_snapshot()
        self.max_equity=max(self.max_equity,equity)
        with a.LOCK:a.S['pandora_account']=dict(max_equity=self.max_equity,current_exposure=sum(p['notional']*a.fresh_mark_price(s)/p['entry'] for s,p in a.S['pandora_win_positions'].items()) if a.S.get('margin_valuation',{}).get('complete',True) and all(a.fresh_mark_price(s) is not None for s in a.S['pandora_win_positions']) else None,used_margin=used,free_margin=free)
        if time.time()-self.last_saved.get('account',0)>=5:
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db)
                    db.execute("insert into pandora_win_runtime_state(name,payload) values('account',%s::jsonb) on conflict(name) do update set payload=excluded.payload,updated_at=clock_timestamp()",(json.dumps(a.S['pandora_account']),))
            self.last_saved['account']=time.time()

    def _cycle_symbol(self,symbol,prices):
        if v2_enabled():return self._cycle_symbol_v2(symbol,prices)
        a=self.a
        with a.LOCK:
            selected=set((a.S.get('bybit_discovery') or {}).get('selected_symbols') or [])
            pos=copy.deepcopy(a.S.get('pandora_win_positions',{}).get(symbol))
            analysis=copy.deepcopy(a.S.get('_pandora_analysis',{}).get(symbol) or {})
        flow=a.MARKET_OBS.flow_context(symbol)
        mark=getattr(a,'fresh_mark_price',a.current_entry_price)(symbol)
        context=dict(flow=flow,local=analysis,mark=mark,selected=symbol in selected)
        if symbol not in selected and not pos:
            if symbol in a.S.get('pandora_watch',{}):a._pandora_watch_clear(symbol,'token_rotated_out')
            if self.tokens.get(symbol,{}).get('state')!='ROTATE_OUT':self.transition(symbol,'ROTATE_OUT','ROTATE_OUT','no_position_and_not_selected',context)
            return
        # Risk guards may use a genuinely fresh own-symbol mark even when
        # checkpoint publication or the executed tape is unavailable. The app's
        # guard must not make discretionary signal exits from stale flow.
        if pos and mark is not None:
            a.pandora_mark_positions({symbol:mark})
            if symbol not in a.S['pandora_win_positions']:
                self.reload_token(symbol)
                # Only after the close commits: a NEW opposite confirmed local
                # and live entry-control may open the reverse in this cycle.
                with a.LOCK:latest=copy.deepcopy(a.S.get('_pandora_analysis',{}).get(symbol) or {})
                if symbol in selected and int(latest.get('entry_side') or 0)==-int(pos['side']):
                    a.pandora_flow_fast_entries({symbol:mark})
                return
        if not flow.get('trade_data_fresh') or mark is None:
            self.transition(symbol,'WAIT_REENTRY' if not pos else ('LONG' if pos['side']>0 else 'SHORT'),
                'FLOW_STALE','fresh_mark_required' if mark is None else 'fresh_executed_trade_required',context)
            return
        if pos:
            current=a.S['pandora_win_positions'].get(symbol)
            if not current or current.get('opened')!=pos.get('opened'):return
            updated=mark_metrics(current,mark,flow,analysis,a.FEE)
            # Defend against a row disappearing through an external writer as
            # well as keeping normal operator-close transactions serialized.
            live=a.S['pandora_win_positions'].get(symbol)
            if not live or live.get('opened')!=pos.get('opened'):return
            if time.time()-self.last_saved.get('position:'+symbol,0)>=1:
                with a.pg() as db:
                    with db.transaction():
                        a.STORE.fence(db)
                        row=db.execute('update pandora_win_positions set features=%s::jsonb where symbol=%s and opened=%s returning symbol',
                            (json.dumps(updated['features']),symbol,pos['opened'])).fetchone()
                        if not row:
                            with a.LOCK:
                                if a.S['pandora_win_positions'].get(symbol,{}).get('opened')==pos['opened']:
                                    a.S['pandora_win_positions'].pop(symbol,None)
                            return
                self.last_saved['position:'+symbol]=time.time()
            with a.LOCK:a.S['pandora_win_positions'][symbol]=updated
            context.update(exit_control_state=copy.deepcopy(updated['features'].get('exit_control_state')),
                exit_decision=copy.deepcopy(updated['features'].get('exit_decision')),
                pressure_state=copy.deepcopy(updated['features'].get('pressure_state')))
            side='LONG' if pos['side']>0 else 'SHORT'
            added=symbol in selected and self.pyramid(symbol,analysis,flow,mark)
            weakening=(flow.get('dominance_side')==-pos['side'] or flow.get('buy_absorbed' if pos['side']>0 else 'sell_absorbed'))
            phase=side+'_PYRAMID' if added else side+'_WEAKENING' if weakening else side
            self.transition(symbol,phase,'HOLD','confirmed_continuation_add' if added else (updated['features'].get('exit_decision') or {}).get('reason','observe_counterpressure' if weakening else 'same_side_control_or_no_confirmed_transfer'),context)
        else:
            if analysis.get('entry_blocked') and analysis.get('forming_local'):
                forming=analysis['forming_local']
                self.transition(symbol,'FORMING_'+forming['pivot_type'],forming['pivot_type']+'_FORMING',
                    'old_anchor_extended_waiting_for_structure_confirmation',context)
                return
            if not a.pandora_runtime_h1_verified(symbol,analysis):
                forming=analysis.get('forming_local') or {}
                phase='FORMING_'+forming['pivot_type'] if forming else 'SELECTED'
                self.transition(symbol,phase,'WAIT','fresh_local_structure_required',context);return
            before=set(a.S['pandora_win_positions'])
            a.pandora_flow_fast_entries({symbol:mark})
            if symbol in a.S['pandora_win_positions'] and symbol not in before:
                self.reload_token(symbol)
            else:
                phase='WAIT_REENTRY' if symbol in a.S.get('pandora_watch',{}) else ('LONG_READY' if analysis.get('entry_side')==1 else 'SHORT_READY')
                self.transition(symbol,phase,'WAIT','waiting_for_executed_control_or_resumption',context)

    def _cycle_symbol_v2(self,symbol,prices):
        """Flow-only decisions; keep existing PAPER ledger and risk manager."""
        a=self.a
        with a.LOCK:
            selected=set((a.S.get('bybit_discovery') or {}).get('selected_symbols') or ())
            pos=copy.deepcopy(a.S.get('pandora_win_positions',{}).get(symbol))
        if symbol not in selected and pos is None:
            if symbol in a.S.get('pandora_watch',{}):
                a._pandora_watch_clear(symbol,'token_rotated_out_no_open_position')
            if self.tokens.get(symbol,{}).get('state')!='ROTATE_OUT':
                self.transition(symbol,'ROTATE_OUT','ROTATE_OUT','not_in_hourly_top5_and_no_position',{'flow_v2':True})
            return
        flow=a.MARKET_OBS.flow_context(symbol)
        mark=a.fresh_mark_price(symbol)
        context={'flow':flow,'mark':mark,'selected':symbol in selected,'flow_v2':True}
        if pos:
            if mark is None:
                self.transition(symbol,'DATA_UNCERTAIN','FLOW_STALE','fresh_mark_missing',context)
                return
            a.pandora_mark_positions({symbol:mark})
            with a.LOCK:
                latest=copy.deepcopy(a.S.get('pandora_win_positions',{}).get(symbol))
            if not latest:
                self.reload_token(symbol)
                return
            side=int(latest['side'])
            if not flow.get('trade_data_fresh'):
                self.transition(symbol,'DATA_UNCERTAIN','FLOW_STALE','fresh_executed_tape_required',context)
                return
            analysis=v2_analysis(side,flow,mark)
            added=symbol in selected and self.pyramid(symbol,analysis,flow,mark)
            features=latest.get('features') or {}
            self.transition(symbol,
                ('LONG' if side>0 else 'SHORT')+('_PYRAMID' if added else ''),
                'HOLD','confirmed_flow_impulse_add' if added else
                    (features.get('exit_decision') or {}).get('reason','flow_control_intact'),context)
            return
        if symbol not in selected:return
        if mark is None or not flow.get('trade_data_fresh'):
            self.transition(symbol,'WAIT','FLOW_STALE','fresh_bybit_tape_or_mark_required',context)
            return
        candidate=v2_candidate(symbol,flow)
        if not candidate.get('eligible'):
            self.transition(symbol,'WAIT','WAIT',candidate.get('reason','no_confirmed_flow_control'),context)
            return
        a.pandora_flow_fast_entries({symbol:mark})
        with a.LOCK:
            opened=copy.deepcopy(a.S.get('pandora_win_positions',{}).get(symbol))
        if opened:
            self.reload_token(symbol)
        else:
            self.transition(symbol,'WAIT','WAIT','flow_signal_waiting_ledger_or_risk_validation',context)

    def snapshot(self):
        with self.a.LOCK:
            visible=set(self.a.pandora_trade_symbols())
            tokens={symbol:copy.deepcopy(state) for symbol,state in self.tokens.items() if symbol in visible}
        policy=RiskPolicy.from_env()
        return dict(tokens=tokens,max_equity=self.max_equity,
                    sizing_policy=dict(min_margin_fraction=policy.min_margin_fraction,max_entry_margin_fraction=policy.max_entry_margin_fraction,min_leverage=policy.min_leverage,max_leverage=policy.max_leverage,fixed_sl_tp=False,pnl_based_halts=False),
                    pyramiding=dict(max_adds=self.max_adds,add_margin_fraction=self.add_fraction,
                                    max_position_margin_fraction=self.position_fraction))
