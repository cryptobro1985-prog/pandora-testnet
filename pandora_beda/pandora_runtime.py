"""One event-driven PAPER executor; universe time never selects trade direction."""
import copy
import json
import time
from dataclasses import asdict
from engine_store import LeaseLost
from pandora_scanner import LiveScanner
from pandora_universe import HourlyUniverse
from pandora_flow_strategy import FlowStrategy
from pandora_experiment import EXPERIMENT_ID
from pandora_risk import RiskPolicy, plan_add, signal_strength
from pandora_win_core import pyramid_decision, apply_add, mark_metrics


class PandoraRuntime:
    def __init__(self, app):
        self.a=app
        self.scanner=LiveScanner(candidate_limit=int(app.os.getenv('PANDORA_SCAN_CANDIDATES','30')))
        self.universe=HourlyUniverse()
        self.strategy=FlowStrategy()
        self.max_adds=int(app.os.getenv('PANDORA_MAX_ADDS','2'))
        self.add_fraction=float(app.os.getenv('PANDORA_ADD_MARGIN_FRACTION','0.10'))
        self.position_fraction=float(app.os.getenv('PANDORA_MAX_POSITION_MARGIN_FRACTION','0.40'))
        if not 0<=self.max_adds<=20 or not 0<self.add_fraction<=self.position_fraction<=1:
            raise ValueError('invalid pyramiding risk configuration')
        self.tokens={};self.last_saved={};self.max_equity=500.;self.last_scanner_save=0.;self.last_scanner_at=0.
        with app.pg() as db:
            db.execute("create table if not exists pandora_win_token_state(symbol text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_win_runtime_state(name text primary key,payload jsonb not null,updated_at timestamptz not null default clock_timestamp())")
            db.execute("create table if not exists pandora_win_pyramid_adds(id bigserial primary key,symbol text not null,opened text not null,add_number integer not null,payload jsonb not null,unique(symbol,opened,add_number))")
        self._restore()

    def _restore(self):
        a=self.a
        with a.pg() as db:
            self.tokens={r['symbol']:r['payload'] for r in db.execute('select symbol,payload from pandora_win_token_state').fetchall()}
            records={r['name']:r['payload'] for r in db.execute('select name,payload from pandora_win_runtime_state').fetchall()}
        self.strategy=FlowStrategy(records.get('flow_strategy'))
        self.universe=HourlyUniverse(state=records.get('universe'))
        self.max_equity=max(float(a.S.get('pandora_equity',500)),float(records.get('account',{}).get('max_equity',500)))
        a.MARKET_OBS.restore_execution_sequences({symbol:state.get('last_sequence',0) for symbol,state in self.strategy.tokens.items()})
        for symbol in set(self.strategy.tokens)|set(a.S.get('pandora_win_positions',{})):
            pos=a.S.get('pandora_win_positions',{}).get(symbol)
            state=self.strategy.get_state(symbol)
            if pos and int(state.get('actual_side') or 0)!=int(pos['side']):self.strategy.on_open(symbol,pos['side'],pos['entry'])
            self.strategy.mark_data_uncertain(symbol,position=pos,reason='Restart requires fresh independent executions.')
        a.S['bybit_discovery']=self.universe.snapshot(held=a.S.get('pandora_win_positions',{}))

    @staticmethod
    def _write_runtime(db,name,payload):
        db.execute("insert into pandora_win_runtime_state(name,payload) values(%s,%s::jsonb) on conflict(name) do update set payload=excluded.payload,updated_at=clock_timestamp()",(name,json.dumps(payload,default=str)))

    def event(self,db,action,symbol,reason,context):
        a=self.a;a.STORE.fence(db)
        decision=(context or {}).get('flow_decision') or context or {}
        payload=dict(experiment_id=EXPERIMENT_ID,symbol=symbol,action=action,reason=reason,
            timestamp=a.now(),exchange_timestamp=decision.get('exchange_epoch'),receive_timestamp=decision.get('received_epoch'),
            state_before=decision.get('state_before'),state_after=decision.get('state_after'),market_context=context,mode='PAPER_ONLY')
        db.execute("insert into pandora_win_audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,%s,%s::jsonb)",
            (a.now(),decision.get('action_id'),'pandora_'+action,json.dumps(payload,default=str)))

    def save_token(self,db,symbol,state):
        db.execute("insert into pandora_win_token_state(symbol,payload) values(%s,%s::jsonb) on conflict(symbol) do update set payload=excluded.payload,updated_at=clock_timestamp()",(symbol,json.dumps(state,default=str)))

    def transition(self,symbol,phase,action,reason,context,force=False):
        a=self.a;stamp=time.monotonic();previous=self.tokens.get(symbol,{})
        changed=any(previous.get(k)!=v for k,v in (('state',phase),('action',action),('reason',reason)))
        state={**previous,'state':phase,'action':action,'reason':reason,'at':a.now(),'context':context}
        if changed or force or stamp-self.last_saved.get(symbol,0)>=5:
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db);self.save_token(db,symbol,state)
                    self.event(db,action,symbol,reason,context)
            self.last_saved[symbol]=stamp
        with a.LOCK:self.tokens[symbol]=state

    def update_universe(self,discovery,held=()):
        with self.a.ACCOUNT_LOCK:
            draft=HourlyUniverse(state=self.universe.to_dict())
            snapshot=draft.update(discovery,held=held)
            if self.scanner_snapshot(snapshot,universe_state=draft.to_dict()):return snapshot
            return copy.deepcopy(self.a.S.get('bybit_discovery',{}))

    def scanner_snapshot(self,snapshot,universe_state=None):
        a=self.a
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active'):return False
            snapshot=copy.deepcopy(snapshot)
            if float(snapshot.get('at',0))<self.last_scanner_at:return False
            held=set(a.S.get('pandora_win_positions',{}));selected=set(snapshot.get('selected_symbols') or [])
            snapshot['retained_open_positions']=sorted(held-selected)
            for symbol in held-selected:snapshot.setdefault('states',{})[symbol]='MANAGED_POSITION'
            if snapshot.get('events') or time.monotonic()-self.last_scanner_save>=5:
                with a.pg() as db:
                    with db.transaction():
                        a.STORE.fence(db)
                        self._write_runtime(db,'universe',universe_state if universe_state is not None else self.universe.to_dict())
                        for event in snapshot.get('events',[]):self.event(db,event['action'],event.get('symbol'),event.get('reason'),event)
                self.last_scanner_save=time.monotonic()
            with a.LOCK:
                if universe_state is not None:self.universe=HourlyUniverse(state=universe_state)
                a.S['bybit_discovery']=snapshot
            self.last_scanner_at=float(snapshot.get('at',0))
            return True

    def semantic_open(self,db,symbol,position):
        clone=FlowStrategy(self.strategy.to_dict())
        previous=clone.get_state(symbol).get('close_ack')
        clone.on_open(symbol,position['side'],position['entry'])
        side='LONG' if position['side']>0 else 'SHORT'
        action='REENTRY_'+side if position['features'].get('entry_kind')=='REENTRY' else ('REVERSE_'+('LONG_TO_SHORT' if position['side']<0 else 'SHORT_TO_LONG') if previous and previous['side']!=position['side'] else 'OPEN_'+side)
        self._write_runtime(db,'flow_strategy',clone.to_dict())
        state=dict(state=side,action=action,reason='flow_confirmed_entry',last_position_side=position['side'])
        self.save_token(db,symbol,state)
        decision=copy.deepcopy(position['features'].get('flow_decision',{}))
        decision['state_after']=side
        self.event(db,action,symbol,'flow_confirmed_entry',dict(position=position,flow_decision=decision))

    def semantic_close(self,db,symbol,position,reason,price,pnl,watch):
        clone=FlowStrategy(self.strategy.to_dict());clone.on_close(symbol,position['side'],price)
        # Executions already received before the actual fill cannot count as
        # independent post-close confirmation, even if queued for processing.
        boundary=max(int(clone.tokens[symbol]['last_sequence']),
            int(self.a.MARKET_OBS.event_status(symbol).get('latest_sequence',0)))
        clone.tokens[symbol]['close_ack'].update(sequence=boundary,closed_event_sequence=boundary)
        self._write_runtime(db,'flow_strategy',clone.to_dict())
        side='LONG' if position['side']>0 else 'SHORT'
        self.save_token(db,symbol,dict(state='FLAT_AFTER_'+side,action='CLOSE_'+side,reason=reason,last_closed_side=position['side']))
        decision=self.current_decision(symbol)
        decision['state_after']='FLAT_AFTER_'+side
        self.event(db,'CLOSE_'+side,symbol,reason,dict(position=position,exit=price,pnl=pnl,flow_decision=decision))

    def reload_token(self,symbol):
        with self.a.pg() as db:
            row=db.execute('select payload from pandora_win_token_state where symbol=%s',(symbol,)).fetchone()
            flow=db.execute("select payload from pandora_win_runtime_state where name='flow_strategy'").fetchone()
        if row:self.tokens[symbol]=row['payload']
        if flow:self.strategy=FlowStrategy(flow['payload'])

    def refresh_after_lease(self):self._restore()

    def event_fresh(self,symbol):
        quality=self.a.MARKET_OBS.flow_context(symbol)
        return bool(quality.get('trade_data_fresh') and self.strategy.tokens.get(symbol,{}).get('sequence_valid',True))

    def current_decision(self,symbol):
        # Monitoring must not restore a read-only snapshot over a concurrent
        # ingest/fill acknowledgement. The account lock is reentrant on writes.
        with self.a.ACCOUNT_LOCK:
            decision=self.strategy.evaluate(symbol,position=self.a.S.get('pandora_win_positions',{}).get(symbol),
                selected_entry=symbol in self.universe.entry_symbols,policy=RiskPolicy.from_env(),data_fresh=self.event_fresh(symbol))
            flow=decision.get('flow',{})
            stamp=time.time()
            flow['latest_trade_age_seconds']=max(0.,stamp-flow['latest_trade_epoch']) if flow.get('latest_trade_epoch') is not None else None
            flow['latest_receive_age_seconds']=max(0.,stamp-flow['latest_receive_epoch']) if flow.get('latest_receive_epoch') is not None else None
            return decision

    def flow_snapshot(self,symbol):return self.current_decision(symbol).get('flow',{})
    def entry_decision(self,symbol):return self.current_decision(symbol)

    def pyramid(self,symbol,analysis,flow,mark):
        a=self.a
        with a.ACCOUNT_LOCK:
            if not a.S.get('engine_active') or a.S.get('orders_enabled') or a.S.get('mode')!='PAPER_ONLY':return False
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
            fresh_flow=self.flow_snapshot(symbol)
            if not self.event_fresh(symbol):return False
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
            with a.LOCK:a.S.update(_execution_running=True,_execution_errors={})
            try:self._cycle(prices)
            except Exception as exc:
                with a.LOCK:a.S['_execution_errors']['__cycle__']=type(exc).__name__+':'+str(exc)[:160]
                raise
            finally:
                with a.LOCK:a.S.update(_execution_running=False,_execution_heartbeat=time.time(),_execution_ok=not bool(a.S.get('_execution_errors')))

    def _cycle(self,prices):
        a=self.a
        symbols=set(self.universe.entry_symbols)|set(a.S.get('pandora_win_positions',{}))
        for symbol in sorted(symbols,key=lambda s:(s not in a.S.get('pandora_win_positions',{}),s)):
            try:self._cycle_symbol(symbol,prices)
            except LeaseLost:raise
            except Exception as exc:
                with a.LOCK:a.S['_execution_errors'][symbol]=type(exc).__name__+':'+str(exc)[:160]
        equity,used,free=a._pandora_margin_state();a.risk_snapshot()
        self.max_equity=max(self.max_equity,equity)
        with a.LOCK:a.S['pandora_account']=dict(max_equity=self.max_equity,used_margin=used,free_margin=free)
        if time.monotonic()-self.last_saved.get('checkpoint',0)>=5:
            with a.pg() as db:
                with db.transaction():
                    a.STORE.fence(db)
                    self._write_runtime(db,'flow_strategy',self.strategy.to_dict())
                    self._write_runtime(db,'universe',self.universe.to_dict())
                    self._write_runtime(db,'account',a.S['pandora_account'])
            self.last_saved['checkpoint']=time.monotonic()

    def _cycle_symbol(self,symbol,prices):
        a=self.a;policy=RiskPolicy.from_env();selected=symbol in self.universe.entry_symbols
        a.pandora_mark_positions({symbol:prices.get(symbol)})
        position=a.S.get('pandora_win_positions',{}).get(symbol)
        cursor=int(self.strategy.tokens.get(symbol,{}).get('last_sequence',0))
        status=a.MARKET_OBS.event_status(symbol,cursor)
        if status.get('gap'):
            self.strategy.reset_observation(symbol,'Execution buffer gap; rebuild independent evidence.',sequence=int(status['oldest_sequence'])-1)
            cursor=int(status['oldest_sequence'])-1
        events=a.MARKET_OBS.events_after(symbol,cursor)
        fresh=self.event_fresh(symbol)
        decision=None
        for event in events:
            event_fresh=bool(fresh and -1<=time.time()-event['exchange_epoch']<=self.strategy.config.freshness_limit_seconds)
            decision=self.strategy.ingest(symbol,event,position=position,selected_entry=selected,policy=policy,data_fresh=event_fresh)
        if decision is None:decision=self.current_decision(symbol)
        mark=a.fresh_mark_price(symbol)
        if not fresh or mark is None:
            decision=self.strategy.mark_data_uncertain(symbol,position=position,selected_entry=selected,policy=policy,
                reason='Fresh sequenced executions and an independent current mark are required.')
            if position:
                protective=self.strategy.data_loss_protection(symbol,mark,position=position,mark_fresh=mark is not None,policy=policy)
                if protective['action']=='CLOSE':
                    a.pandora_close(symbol,mark,'data_loss_observed_structure_breach',watch_context={'flow_decision':protective})
                    decision=protective
        elif events and decision.get('new_event'):
            if decision['action']=='CLOSE' and position:
                a.pandora_close(symbol,mark,'executed_flow_control_transfer',watch_context={'flow_decision':decision})
            elif decision['action'] in ('OPEN','REENTRY') and not position and selected:
                if not a.pandora_open(symbol,decision['side'],decision['analysis'],execution_context=decision):
                    rejection=a.S.get('pandora_executor_rejections',{}).get(symbol) or {}
                    decision={**decision,'action':'WAIT','reason':rejection.get('reason','PAPER_ENTRY_NOT_COMMITTED')}
            elif decision['action']=='HOLD' and position and selected:
                self.pyramid(symbol,decision['analysis'],decision['flow'],mark)
        current=a.S.get('pandora_win_positions',{}).get(symbol)
        actual_state=self.strategy.tokens.get(symbol,{}).get('position_state',decision.get('position_state','FLAT'))
        decision={**decision,'position_state':actual_state,'state_after':actual_state}
        if current:
            updated=mark_metrics(current,mark,decision.get('flow',{}),decision.get('analysis',{}),a.FEE) if mark is not None else current
            updated.setdefault('features',{}).update(flow_decision=copy.deepcopy(decision),flow_regime=decision.get('flow_regime'),position_state=decision.get('position_state'))
            with a.LOCK:live=a.S.get('pandora_win_positions',{}).get(symbol)
            if not live or live.get('opened')!=current.get('opened'):return
            if time.monotonic()-self.last_saved.get('position:'+symbol,0)>=1:
                with a.pg() as db:
                    with db.transaction():
                        a.STORE.fence(db)
                        row=db.execute('update pandora_win_positions set features=%s::jsonb where symbol=%s and opened=%s returning symbol',
                            (json.dumps(updated['features']),symbol,current['opened'])).fetchone()
                        if not row:
                            with a.LOCK:
                                if a.S.get('pandora_win_positions',{}).get(symbol,{}).get('opened')==current['opened']:
                                    a.S['pandora_win_positions'].pop(symbol,None)
                            return
                self.last_saved['position:'+symbol]=time.monotonic()
            with a.LOCK:
                if a.S.get('pandora_win_positions',{}).get(symbol,{}).get('opened')==current['opened']:
                    a.S['pandora_win_positions'][symbol]=updated
        phase=decision.get('position_state') or ('FLAT' if not current else 'LONG' if current['side']>0 else 'SHORT')
        context={'flow_decision':decision,'flow':decision.get('flow',{}),'position':copy.deepcopy(current),'mark':mark,
                 'management_state':'ACTIVE_ENTRY' if selected else 'MANAGED_POSITION'}
        self.transition(symbol,phase,decision['action'],decision['reason'],context)

    def snapshot(self):
        visible=set(self.a.pandora_runtime_symbols())
        return dict(experiment_id=EXPERIMENT_ID,tokens={s:copy.deepcopy(v) for s,v in self.tokens.items() if s in visible},
            max_equity=self.max_equity,universe=self.universe.to_dict(),flow_config=asdict(self.strategy.config),
            sizing_policy=dict(min_margin_fraction=RiskPolicy.from_env().min_margin_fraction,min_leverage=RiskPolicy.from_env().min_leverage,max_leverage=RiskPolicy.from_env().max_leverage,fixed_sl_tp=False,pnl_based_halts=False),
            pyramiding=dict(max_adds=self.max_adds,add_margin_fraction=self.add_fraction,max_position_margin_fraction=self.position_fraction))
