"""Strategy 1.4 independent PAPER replay of the 848b3c6 Caterpillar execution path."""
import copy, json, math, threading, time
from local_order_flow import (
    POLICY as FLOW_POLICY,
    initial_entry_candidate,
    entry_candidate,
    pressure_exit,
    update_watch,
    reentry_ready,
)
from h1_structure import analyze as legacy_h1_analyze, pending_extreme as legacy_pending_extreme, update_path as legacy_update_path, POLICY as H1_POLICY


class Strategy14:
    def __init__(self, pg, store, market_obs, price_getter, price_snapshot, paper_pnl, fee, now_func):
        self.pg=pg; self.store=store; self.market_obs=market_obs
        self.price_getter=price_getter; self.price_snapshot=price_snapshot
        self.paper_pnl=paper_pnl; self.fee=float(fee); self.now=now_func
        self.lock=threading.RLock()
        self.positions={}; self.watch={}; self.h1={}; self._h1_verified={}
        self.equity=500.0; self.realized=0.0; self.started_at=None
        self._persist={}

    def ensure_schema(self, reset_marker):
        queries=(
          "CREATE TABLE IF NOT EXISTS strategy14_account_state(id integer PRIMARY KEY,equity double precision NOT NULL,realized_pnl double precision NOT NULL,started_at text NOT NULL,updated_at text NOT NULL)",
          "CREATE TABLE IF NOT EXISTS strategy14_positions(symbol text PRIMARY KEY,side integer NOT NULL,entry double precision NOT NULL,notional double precision NOT NULL,margin double precision NOT NULL,leverage double precision NOT NULL,opened text NOT NULL,opened_epoch double precision NOT NULL,signal_candle_time bigint,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
          "CREATE TABLE IF NOT EXISTS strategy14_trade_history(id bigserial PRIMARY KEY,opened text,closed text,symbol text,side integer,entry double precision,exit double precision,pnl double precision,reason text,margin double precision,notional double precision,leverage double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
          "CREATE TABLE IF NOT EXISTS strategy14_watchlist(symbol text PRIMARY KEY,side integer NOT NULL,origin_signal_candle bigint,exit_price double precision,exit_at text NOT NULL,expires_epoch double precision NOT NULL DEFAULT 0,reentries integer NOT NULL DEFAULT 0,context jsonb NOT NULL DEFAULT '{}'::jsonb)",
          "CREATE TABLE IF NOT EXISTS strategy14_signal_journal(id text PRIMARY KEY,ts text NOT NULL,candle_time bigint,action text NOT NULL,side integer,price double precision,features jsonb NOT NULL DEFAULT '{}'::jsonb)",
        )
        with self.pg() as db:
            with db.transaction():
                for q in queries: db.execute(q)
                db.execute("insert into strategy14_account_state(id,equity,realized_pnl,started_at,updated_at) values(1,500,0,%s,%s) on conflict(id) do nothing",(self.now(),self.now()))
                done=db.execute("select 1 from audit_journal where event_id=%s limit 1",(reset_marker,)).fetchone()
                if not done:
                    db.execute("truncate table strategy14_positions,strategy14_watchlist,strategy14_signal_journal,strategy14_trade_history restart identity")
                    stamp=self.now()
                    db.execute("update strategy14_account_state set equity=500,realized_pnl=0,started_at=%s,updated_at=%s where id=1",(stamp,stamp))
                    db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,%s,'strategy14_reset',%s::jsonb)",
                      (stamp,reset_marker,json.dumps({"starting_equity":500,"variant":"1.4","logic":"exact_legacy_profitable"})))
        self.restore()

    def restore(self):
        with self.pg() as db:
            acct=db.execute("select * from strategy14_account_state where id=1").fetchone()
            pos=db.execute("select * from strategy14_positions").fetchall()
            watches=db.execute("select * from strategy14_watchlist").fetchall()
        with self.lock:
            self.equity=float(acct["equity"]); self.realized=float(acct["realized_pnl"]); self.started_at=acct["started_at"]
            self.positions={r["symbol"]:{**dict(r),"t":float(r["opened_epoch"])} for r in pos}
            self.watch={r["symbol"]:dict(r) for r in watches}

    @staticmethod
    def confirmed_h1(a):
        if not isinstance(a,dict): return False
        try:
            side=int(a.get("entry_side") or 0); price=float(a.get("pivot_price") or 0); signal=int(a.get("signal_candle_time") or 0)
        except (TypeError,ValueError,OverflowError): return False
        expected="LOCAL_HIGH" if side==-1 else "LOCAL_LOW" if side==1 else None
        return bool(expected and a.get("ready") and a.get("h1_direction_anchor") and a.get("anchor_confirmed")
                    and not a.get("entry_blocked") and a.get("pivot_type")==expected
                    and math.isfinite(price) and price>0 and signal>0)

    def _h1_flow_transfer(self,symbol,new_side,stamp=None):
        new_side=int(new_side or 0)
        if new_side not in (-1,1):
            return {"confirmed":False,"reason":"invalid_candidate_side"}
        stamp=time.time() if stamp is None else float(stamp)
        flow=self.market_obs.flow_context(symbol,stamp)
        if not isinstance(flow,dict) or not flow.get("trade_data_fresh"):
            return {"confirmed":False,"reason":"waiting_for_fresh_executed_flow","flow":flow}
        try:
            age=float(flow.get("latest_trade_age_seconds"))
            i60=float(flow.get("flow_imbalance"))
            i180=float(flow.get("flow_imbalance_180s"))
            i300=float(flow.get("flow_imbalance_300s"))
            r300=float(flow.get("price_return_300s"))
        except (TypeError,ValueError,OverflowError):
            return {"confirmed":False,"reason":"waiting_for_m1_m3_m5_flow_coverage","flow":flow}
        aligned60=new_side*i60; aligned180=new_side*i180; aligned300=new_side*i300
        price_response=new_side*r300
        confirmed=bool(-1<=age<=15 and aligned60>0 and aligned180>0 and aligned300>0 and price_response>0)
        return {"confirmed":confirmed,
          "reason":"executed_flow_control_transfer_confirmed" if confirmed else "opposite_structure_but_previous_side_still_controls",
          "candidate_side":new_side,"aligned_flow_60s":aligned60,"aligned_flow_180s":aligned180,
          "aligned_flow_300s":aligned300,"aligned_price_return_300s":price_response,
          "latest_trade_age_seconds":age,"flow_source":flow.get("volume_source")}

    def _runtime_h1_verified(self,symbol,analysis=None,stamp=None):
        with self.lock:meta=copy.deepcopy(self._h1_verified.get(symbol))
        if not meta:return False
        stamp=time.time() if stamp is None else float(stamp)
        try:
            verified=float(meta.get("verified_at") or 0)
            last_closed=int(meta.get("last_candle_time") or 0)
            side=int(meta.get("entry_side") or 0)
            signal=int(meta.get("signal_candle_time") or 0)
            pivot=int(meta.get("pivot_candle_time") or 0)
        except (TypeError,ValueError,OverflowError):
            return False
        age=stamp-verified
        if age<0 or age>90:return False
        expected_latest=int(((stamp*1000.0-1000.0)//3_600_000)*3_600_000-3_600_000)
        if expected_latest>0 and last_closed<expected_latest:return False
        if analysis is not None:
            try:
                if int(analysis.get("entry_side") or 0)!=side:return False
                if int(analysis.get("signal_candle_time") or 0)!=signal:return False
                if int(analysis.get("pivot_candle_time") or 0)!=pivot:return False
            except (TypeError,ValueError,OverflowError):
                return False
        return side in (-1,1) and signal>0 and pivot>0

    def scan_h1(self,symbol,rows,now_ms):
        analysis=legacy_h1_analyze(rows,now_ms,symbol)
        with self.lock:prior=copy.deepcopy(self.h1.get(symbol))
        if not analysis.get("ready") or not analysis.get("anchor_confirmed"):
            if self.confirmed_h1(prior):
                analysis={**prior,"ready":True,"stale_source_reason":analysis.get("reason"),
                  "anchor_recovered_from":"latest_valid_strategy14_observation",
                  **legacy_pending_extreme(rows,now_ms,int(prior.get("entry_side") or 0),prior.get("pivot_price"))}
            else:
                with self.lock:self.h1[symbol]=copy.deepcopy(analysis)
                return analysis
        if self.confirmed_h1(prior):
            prior_t=int(prior.get("signal_candle_time") or 0); new_t=int(analysis.get("signal_candle_time") or 0)
            prior_side=int(prior.get("entry_side") or 0); new_side=int(analysis.get("entry_side") or 0)
            if prior_t>new_t:
                analysis={**prior,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
                  **legacy_pending_extreme(rows,now_ms,prior_side,prior.get("pivot_price")),
                  "anchor_guard":"newest_confirmed_anchor_wins"}
            elif prior_side in (-1,1) and new_side in (-1,1) and new_side!=prior_side:
                if new_t<=prior_t:
                    analysis={**prior,"ready":True,"last_candle_time":analysis.get("last_candle_time"),
                      **legacy_pending_extreme(rows,now_ms,prior_side,prior.get("pivot_price")),
                      "anchor_guard":"blocked_non_new_opposite_pivot"}
                else:
                    candidate=copy.deepcopy(analysis)
                    transfer=self._h1_flow_transfer(symbol,new_side)
                    if not transfer.get("confirmed"):
                        analysis={**prior,"ready":True,"last_candle_time":candidate.get("last_candle_time"),
                          **legacy_pending_extreme(rows,now_ms,prior_side,prior.get("pivot_price")),
                          "anchor_guard":"opposite_h1_waiting_for_executed_flow_transfer",
                          "pending_opposite_pivot_type":candidate.get("pivot_type"),
                          "pending_opposite_pivot_price":candidate.get("pivot_price"),
                          "pending_opposite_signal_candle_time":candidate.get("signal_candle_time"),
                          "pending_opposite_pivot_candle_time":candidate.get("pivot_candle_time"),
                          "pending_opposite_flow_transfer":transfer}
                    else:
                        analysis["flow_transfer_confirmation"]=transfer
                        analysis["anchor_guard"]="opposite_h1_structure_and_flow_confirmed"
        if self.confirmed_h1(analysis):
            with self.lock:
                self._h1_verified[symbol]={
                  "verified_at":time.time(),"observed_at_ms":int(now_ms),
                  "last_candle_time":int(analysis.get("last_candle_time") or 0),
                  "entry_side":int(analysis.get("entry_side") or 0),
                  "signal_candle_time":int(analysis.get("signal_candle_time") or 0),
                  "pivot_candle_time":int(analysis.get("pivot_candle_time") or 0),
                  "pivot_type":analysis.get("pivot_type"),"pivot_price":analysis.get("pivot_price")}
        with self.lock:self.h1[symbol]=copy.deepcopy(analysis)
        return analysis

    def _margin_state(self):
        with self.lock:
            realized=float(self.equity); positions=copy.deepcopy(self.positions)
        prices=self.price_snapshot()
        unreal=0.0
        for sym,p in positions.items():
            mark=prices.get(sym)
            if not mark: continue
            try: unreal+=self.paper_pnl(float(p["notional"]),float(p["entry"]),float(mark),int(p["side"]),self.fee)
            except Exception: pass
        equity=max(0.0,realized+unreal)
        used=sum(max(0.0,float(p.get("margin",0) or 0)) for p in positions.values())
        return equity,used,max(0.0,equity-used)

    def _journal(self,kind,payload):
        try:
            with self.pg() as db:db.execute("insert into audit_journal(recorded_at,event_id,kind,payload) values(%s,null,%s,%s::jsonb)",(self.now(),kind,json.dumps(payload,default=str)))
        except Exception: pass

    def _open(self,symbol,side,analysis,entry_kind="ORDER_FLOW",watch=None):
        side=int(side or 0)
        if side not in (-1,1) or not self.confirmed_h1(analysis): return False
        if not self._runtime_h1_verified(symbol,analysis): return False
        flow=self.market_obs.flow_context(symbol,time.time())
        selection=(entry_candidate(symbol,analysis,None,flow,time.time()) if entry_kind=="REENTRY"
                   else initial_entry_candidate(symbol,analysis,None,flow,time.time()))
        if not selection.get("eligible"): return False
        price=self.price_getter(symbol)
        if price is None:return False
        if entry_kind=="REENTRY":
            if not watch or int(watch.get("side") or 0)!=side:return False
            if not reentry_ready(side,None,price,watch,flow,time.time()):return False
        with self.lock:
            if symbol in self.positions:return False
        equity,used,free=self._margin_state()
        if equity<=0 or free<0.01:return False
        leverage=25.0
        desired=equity*0.20
        margin=min(desired,free)
        if margin<0.01:return False
        notional=margin*leverage
        opened=self.now(); epoch=time.time()
        reentries=(int((watch or {}).get("reentries") or 0)+1) if entry_kind=="REENTRY" else 0
        signal=int(analysis.get("signal_candle_time") or 0)
        features={**copy.deepcopy(analysis),"symbol":symbol,"strategy_name":"Strategy 1.1 legacy",
          "variant":"1.4","policy":H1_POLICY,"caterpillar_policy":FLOW_POLICY,"entry_kind":entry_kind,
          "candidate_selection":selection,"origin_h1_signal_candle":signal,"swing_reentries":reentries,
          "reference_margin_fraction":0.20,"reference_leverage":25.0,"actual_margin":margin,
          "mfe_price_move":0.0,"mae_price_move":0.0,"mfe_roe_pct":0.0,"mae_roe_pct":0.0,
          "entry_mark":float(price),"profit_lock_armed":False,
          "profit_lock_mode":"executed_flow_reversal_only",
          "m15_entry_context":None,"m15_reentry_context":None,
          "reentry_watch":copy.deepcopy(watch) if watch else None,
          "estimated_round_trip_cost_move":2*self.fee+0.0004,
          "execution_cost_budget_only":True}
        pos={"symbol":symbol,"side":side,"entry":float(price),"notional":notional,"margin":margin,
             "leverage":leverage,"opened":opened,"t":epoch,"signal_candle_time":signal,"features":features}
        claim=("S14:REENTRY:%s:%s:%s"%(symbol,signal,reentries) if entry_kind=="REENTRY"
               else "S14:OPEN:%s:%s:%s"%(symbol,signal,side))
        with self.pg() as db:
            with db.transaction():
                self.store.fence(db)
                row=db.execute("insert into strategy14_signal_journal(id,ts,candle_time,action,side,price,features) values(%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do nothing returning id",
                  (claim,opened,signal,"REENTRY" if entry_kind=="REENTRY" else "OPEN",side,float(price),json.dumps(features,default=str))).fetchone()
                if not row:return False
                row=db.execute("insert into strategy14_positions(symbol,side,entry,notional,margin,leverage,opened,opened_epoch,signal_candle_time,features) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(symbol) do nothing returning symbol",
                  (symbol,side,float(price),notional,margin,leverage,opened,epoch,signal,json.dumps(features,default=str))).fetchone()
                if not row:return False
                if entry_kind=="REENTRY":db.execute("delete from strategy14_watchlist where symbol=%s",(symbol,))
        with self.lock:
            self.positions[symbol]=pos
            if entry_kind=="REENTRY":self.watch.pop(symbol,None)
        self._journal("strategy14_trade_opened",{"symbol":symbol,"side":side,"entry":price,"entry_kind":entry_kind,"margin":margin,"notional":notional})
        return True

    def _close(self,symbol,mark,reason,watch_context=None):
        with self.lock:pos=copy.deepcopy(self.positions.get(symbol))
        if not pos:return None
        mark=float(mark)
        pnl=self.paper_pnl(pos["notional"],pos["entry"],mark,pos["side"],self.fee)
        features=copy.deepcopy(pos.get("features") or {})
        features["actual_exit_reason"]=reason;features["actual_exit_mark"]=mark
        if watch_context:features["executed_flow_exit_context"]=copy.deepcopy(watch_context)
        watch=None
        watch_reasons=(
          "m15_adverse_pressure_profit_protect","profit_lock_stop","m15_momentum_weakening",
          "m15_pressure_reversal","m15_pressure_reversal_profit_only","caterpillar_breakeven",
          "executed_flow_counter_dominance","m15_opposite_control_exit",
          "executed_flow_counter_control_exit","executed_flow_weakening_profit_exit",
          "executed_flow_profit_flip_exit","executed_flow_risk_flip_exit",
          "m1_m3_m5_mfe_profit_exit","m1_m3_m5_risk_exit",
          "m1_m3_confirmed_counterflow_exit","m1_m3_m5_mfe_preservation_exit",
          "executed_flow_15s30s_counter_control_exit","executed_flow_15s30s_mfe_weakening_exit"
        )
        if reason in watch_reasons:
            watch={"symbol":symbol,"side":int(pos["side"]),
              "origin_signal_candle":int(features.get("origin_h1_signal_candle") or pos.get("signal_candle_time") or 0),
              "exit_price":mark,"exit_at":self.now(),"expires_epoch":0.0,
              "reentries":int(features.get("swing_reentries",0) or 0),
              "context":copy.deepcopy(watch_context or {})}
            # Exact profitable runtime behavior: MFE/risk exits DO NOT imply
            # that a new pullback has already completed. They arm WAIT_PULLBACK.
            opposite_flow_exit=reason in (
              "executed_flow_15s30s_counter_control_exit","executed_flow_weakening_exit",
              "executed_flow_counter_control_exit","executed_flow_counter_dominance"
            )
            flow_at=(watch_context or {}).get("flow_context") or {}
            try:
                opposite_epoch=float(flow_at["volume_window_end_epoch"])-float(flow_at["latest_trade_age_seconds"])
                if not math.isfinite(opposite_epoch):opposite_epoch=None
            except (KeyError,TypeError,ValueError,OverflowError):
                opposite_epoch=None
            confirmed_opposite=bool(opposite_flow_exit and opposite_epoch is not None)
            watch["context"].update(
              phase="WAIT_RESUMPTION" if confirmed_opposite else "WAIT_PULLBACK",
              counter_pressure_seen=confirmed_opposite,
              caterpillar_policy=FLOW_POLICY
            )
            if confirmed_opposite:
                watch["context"]["last_opposite_trade_epoch"]=opposite_epoch
        with self.pg() as db:
            with db.transaction():
                self.store.fence(db)
                row=db.execute("delete from strategy14_positions where symbol=%s and opened=%s returning symbol",(symbol,pos["opened"])).fetchone()
                if not row:return None
                acct=db.execute("update strategy14_account_state set equity=equity+%s,realized_pnl=realized_pnl+%s,updated_at=%s where id=1 returning equity,realized_pnl",
                  (pnl,pnl,self.now())).fetchone()
                db.execute("insert into strategy14_trade_history(opened,closed,symbol,side,entry,exit,pnl,reason,margin,notional,leverage,features) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                  (pos["opened"],self.now(),symbol,pos["side"],pos["entry"],mark,pnl,reason,pos["margin"],pos["notional"],pos["leverage"],json.dumps(features,default=str)))
                if watch:
                    db.execute("insert into strategy14_watchlist(symbol,side,origin_signal_candle,exit_price,exit_at,expires_epoch,reentries,context) values(%s,%s,%s,%s,%s,0,%s,%s::jsonb) on conflict(symbol) do update set side=excluded.side,origin_signal_candle=excluded.origin_signal_candle,exit_price=excluded.exit_price,exit_at=excluded.exit_at,reentries=excluded.reentries,context=excluded.context",
                      (symbol,watch["side"],watch["origin_signal_candle"],watch["exit_price"],watch["exit_at"],watch["reentries"],json.dumps(watch["context"],default=str)))
        with self.lock:
            self.positions.pop(symbol,None)
            if watch:self.watch[symbol]=watch
            self.equity=float(acct["equity"]);self.realized=float(acct["realized_pnl"])
        self._journal("strategy14_trade_closed",{"symbol":symbol,"side":pos["side"],"entry":pos["entry"],"exit":mark,"pnl":pnl,"reason":reason,"equity":self.equity})
        return {"symbol":symbol,"pnl":pnl,"reason":reason,"equity":self.equity}

    def _mark(self,symbol,pos,mark):
        mark=float(mark)
        updated,liq=legacy_update_path(pos,mark)
        f=updated.setdefault("features",{})
        f["caterpillar_policy"]=FLOW_POLICY
        with self.lock:self.positions[symbol]=updated

        flow=self.market_obs.flow_context(symbol,time.time())
        reason=pressure_exit(updated,None,mark,flow)
        if reason:
            return self._close(symbol,mark,reason,{"flow_context":flow,"observed_at":self.now()})
        if liq:
            return self._close(symbol,mark,"paper_liquidation_proxy")

        last=self._persist.get(symbol,0)
        if time.time()-last>=30:
            with self.pg() as db:
                with db.transaction():
                    self.store.fence(db)
                    db.execute("update strategy14_positions set features=%s::jsonb where symbol=%s and opened=%s",
                      (json.dumps(f,default=str),symbol,pos["opened"]))
            self._persist[symbol]=time.time()
        return None

    def cycle(self,symbols,prices):
        with self.lock:positions=copy.deepcopy(self.positions)
        for symbol,pos in positions.items():
            mark=prices.get(symbol)
            if mark:self._mark(symbol,pos,mark)
        for symbol in symbols:
            with self.lock:
                if symbol in self.positions:continue
                analysis=copy.deepcopy(self.h1.get(symbol))
                watch=copy.deepcopy(self.watch.get(symbol))
            if not self.confirmed_h1(analysis):continue
            side=int(analysis.get("entry_side") or 0)
            mark=prices.get(symbol)
            if not mark:continue
            if watch and int(watch.get("side") or 0)==-side:
                with self.pg() as db:db.execute("delete from strategy14_watchlist where symbol=%s",(symbol,))
                with self.lock:self.watch.pop(symbol,None)
                watch=None
            flow=self.market_obs.flow_context(symbol,time.time())
            if watch:
                updated=update_watch(watch,float(mark),None,flow,time.time())
                with self.lock:self.watch[symbol]=updated
                if reentry_ready(side,None,float(mark),updated,flow,time.time()):self._open(symbol,side,analysis,"REENTRY",updated)
            else:
                if initial_entry_candidate(symbol,analysis,None,flow,time.time()).get("eligible"):
                    self._open(symbol,side,analysis,"ORDER_FLOW")

    def snapshot(self,limit=50):
        prices=self.price_snapshot()
        with self.lock:
            positions=copy.deepcopy(self.positions); h1=copy.deepcopy(self.h1); realized=float(self.realized); started=self.started_at
        unreal=0.0;out=[]
        for symbol,p in positions.items():
            mark=prices.get(symbol)
            pnl=self.paper_pnl(p["notional"],p["entry"],mark,p["side"],self.fee) if mark else None
            if pnl is not None:unreal+=pnl
            out.append({"symbol":symbol,"side":int(p["side"]),"entry":p["entry"],"mark":mark,"margin":p["margin"],
                        "notional":p["notional"],"leverage":p["leverage"],"opened":p["opened"],"unrealized_pnl":pnl,
                        "features":copy.deepcopy(p.get("features") or {})})
        with self.pg() as db:
            rows=db.execute("select * from strategy14_trade_history order by id desc limit %s",(int(limit),)).fetchall()
            acct=db.execute("select * from strategy14_account_state where id=1").fetchone()
        return {"name":"Strategy 1.1 · LEGACY","starting_equity":500.0,"realized_equity":float(acct["equity"]),
          "realized_pnl":float(acct["realized_pnl"]),"unrealized_pnl":unreal,"total_equity":float(acct["equity"])+unreal,
          "started_at":acct["started_at"],"open_positions":out,"closed_trades":[dict(r) for r in rows],
          "h1":h1,"policy":FLOW_POLICY,"h1_policy":H1_POLICY}
