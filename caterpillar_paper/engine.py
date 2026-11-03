"""Causal H1/flow decisions and a shared, isolated PAPER portfolio.

Live transport and dashboards are readers/producers, never trading adapters.
Signal fills require a strictly later real trade; no historical extremes as fills.
"""
from collections import OrderedDict, deque
from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN
import copy
import math
import time
import uuid

from research.caterpillar.caterpillar.h1 import H1Tracker, H1Bar
from research.caterpillar.caterpillar.model import Config as ResearchConfig, Local, Trade, features
from .config import METADATA


class Engine:
    def __init__(self, config, store, run_id='local', session_id=None):
        self.config, self.store, self.run_id = config, store, str(run_id)
        self.s = store.load() or {
            'schema_version': 1, 'session_id': session_id or str(uuid.uuid4()),
            'config_hash': config.digest, 'config': asdict(config), 'metadata': METADATA,
            'seq': 0, 'cash': config.start_equity, 'max_equity': config.start_equity,
            'max_drawdown': 0., 'positions': {}, 'closed': [], 'symbols': {},
            'active': [], 'scanner': {}, 'started': time.time(), 'checkpoint_at': None,
        }
        self.validate()
        if self.s['config_hash'] != config.digest:
            raise ValueError('Config changed: start a new session/output or restore exact config')
        if session_id and self.s['session_id'] != session_id:
            raise ValueError('Session ID does not match checkpoint')
        self.memory = {}; self.events = []
        self.rcfg = ResearchConfig(block_trades=config.block_trades, baseline_blocks=config.baseline_blocks,
                                   warmup_blocks=config.warmup_blocks, control_imbalance=config.control_imbalance,
                                   fee_bps=config.fee_bps, slippage_bps=config.slippage_bps)
        for symbol in self.s['symbols']:
            self._memory(symbol)
            # Never restore actionable flow, marks, queued fills, or transfer streaks.
            row = self.s['symbols'][symbol]
            row['pending'] = None
            row['state'], row['reason'] = 'STALE', 'RESTORED_REQUIRES_FRESH_MARKET_DATA'
        self.save()

    def validate(self):
        s = self.s
        if s.get('schema_version') != 1 or not isinstance(s.get('session_id'), str):
            raise ValueError('Invalid persisted state')
        if len(s['active']) != len(set(s['active'])) or len(s['active']) > 5:
            raise ValueError('Invalid active universe')
        values = [s['cash'], s['max_equity'], s['max_drawdown']]
        for symbol, p in s['positions'].items():
            if (p['symbol'] != symbol or p['side'] not in (-1, 1) or p['quantity'] <= 0
                    or p['entry'] <= 0 or p['margin'] <= 0 or p['leverage'] > 25):
                raise ValueError('Invalid position')
            values.extend(p[k] for k in ('entry','quantity','margin','notional','entry_fee','mfe','mae'))
            if not math.isclose(p['notional'], p['margin']*p['leverage'], rel_tol=1e-9):
                raise ValueError('Broken notional accounting')
        if any(not math.isfinite(v) for v in values):
            raise ValueError('Nonfinite accounting')
        ids = [p['position_id'] for p in list(s['positions'].values())+s['closed']]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate position identity')
        expected = self.config.start_equity+sum(p['pnl'] for p in s['closed'])-sum(p['entry_fee'] for p in s['positions'].values())
        if not math.isclose(s['cash'], expected, abs_tol=1e-7):
            raise ValueError('Cash does not reconcile with fills/fees')

    def _symbol(self, symbol):
        if symbol not in self.s['symbols']:
            self.s['symbols'][symbol] = {'local': None, 'locals': [], 'h1': None, 'state': 'WAIT_LOCAL',
                'reason': 'LOCAL_UNCONFIRMED', 'cycle_id': None, 'watch': None, 'pending': None,
                'instrument': {}, 'selection': None, 'last_decision': None}
        return self.s['symbols'][symbol]

    def _memory(self, symbol):
        row = self._symbol(symbol)
        if symbol not in self.memory:
            h1 = H1Tracker(self.config.h1_lookback)
            if row['h1']:
                data = row['h1']
                h1.history.extend(H1Bar(**b) for b in data['history'])
                h1.pending = {k: Local(**v) for k,v in data['pending'].items()}
                h1.next_ident = data['next_ident']; h1.latest_available_ts = data['latest_available_ts']
            self.memory[symbol] = {'h1': h1, 'block': [], 'history': deque(maxlen=self.config.baseline_blocks),
                'seen': OrderedDict(), 'last_ts': None, 'mark': None, 'received': None, 'connected': False,
                'flow': None, 'control_streak': 0, 'last_control': 0, 'transfer': 0, 'h1_verified': False}
        return self.memory[symbol]

    def emit(self, symbol, event, reason, ts, **extra):
        self.s['seq'] += 1
        row = self._symbol(symbol) if symbol else {}
        e = {'seq': self.s['seq'], 'event_id': self.s['session_id']+':'+str(self.s['seq']),
             'session_id': self.s['session_id'], 'run_id': self.run_id, 'timestamp': ts,
             'symbol': symbol, 'event': event, 'reason': reason, 'state': row.get('state'),
             'local': copy.deepcopy(row.get('local')), 'cycle_id': row.get('cycle_id'), **extra}
        self.events.append(e)

    def decision(self, symbol, state, reason, ts, event=None, **extra):
        row = self._symbol(symbol)
        changed = (row['state'], row['reason']) != (state, reason)
        before = row['state']; row.update(state=state, reason=reason)
        row['last_decision'] = {'timestamp': ts, 'reason': reason, 'state': state}
        if changed or event:
            self.emit(symbol, event or state, reason, ts, state_before=before, **extra)

    def save(self):
        try:self.validate()
        except ValueError as exc:raise RuntimeError('PERSISTENCE_INVARIANT_FAILED: '+str(exc)) from exc
        self.store.commit(self.s, self.events); self.events = []

    def set_active(self, symbols, selections, instruments, ts):
        if not self.s['active']:
            if len(symbols) != 5 or len(set(symbols)) != 5 or any(s not in instruments for s in symbols):
                raise ValueError('Need five validated instruments')
            self.s['active'] = list(symbols)
            for symbol in symbols:
                row = self._symbol(symbol); row['selection'] = selections.get(symbol)
                self.emit(symbol, 'SELECTED', 'SESSION_UNIVERSE_FROZEN', ts, selection=row['selection'])
        for symbol in self.s['active']:
            if symbol in instruments:
                self._symbol(symbol)['instrument'] = instruments[symbol]
        self.save()

    def reset_flow(self, symbols, connected, ts=None):
        ts = time.time() if ts is None else ts
        for symbol in symbols:
            m = self._memory(symbol)
            m.update(block=[], history=deque(maxlen=self.config.baseline_blocks), last_ts=None,
                     connected=connected, flow=None, control_streak=0, last_control=0, transfer=0,
                     mark=None, received=None)
            self._symbol(symbol)['pending'] = None
            self.decision(symbol, 'STALE', 'RECONNECT_REQUIRES_NEW_FLOW' if connected else 'WEBSOCKET_DISCONNECTED', ts,
                          event='RECONNECT' if connected else 'FLOW_STALE')
        self.save()

    def seed_h1(self, symbol, candles, observed_at):
        m = self._memory(symbol); row = self._symbol(symbol); h1 = m['h1']
        initial = not h1.history
        for candle in candles:
            if h1.history and candle['open_ts'] <= h1.history[-1].start:
                continue
            bar = dict(candle)
            # On initial historical bootstrap record theoretical closed-bar availability;
            # live confirmations use actual observation time. Neither can fill past trades.
            bar['available_ts'] = bar['open_ts']+3600 if initial else observed_at
            events, _ = h1.seed(bar, observed_at)
            position=self.s['positions'].get(symbol)
            if position and bar['open_ts']+3600>position['opened']:
                anchor=position['anchor']
                broken=bar['low']<anchor['price'] if position['side']==1 else bar['high']>anchor['price']
                if broken:position['structural_reason']='ORIGINAL_LOCAL_INVALIDATED'
            for local, stage, reason in events:
                if stage != 'CONFIRMED':
                    continue
                item = asdict(local)
                item.update(symbol=symbol, pivot_time=local.candle_open_ts, confirmed_time=local.confirmed_ts,
                            observed_at=observed_at, algorithm=METADATA['local_algorithm'], valid=True,
                            exact_pivot_timestamp=None, invalidation_reason=None)
                if (position and (1 if local.kind=='LOW' else -1)==-position['side']
                        and local.confirmed_ts>position['anchor']['confirmed_time']):
                    position['structural_reason']='OPPOSITE_CONFIRMED_H1'
                row['locals'].append(item); row['locals'] = row['locals'][-20:]
                # Simultaneously confirmed high and low are ambiguous; no arbitrary side choice.
                same = [x for x in row['locals'] if x['confirmed_time'] == item['confirmed_time']]
                row['local'] = None if len({x['kind'] for x in same}) > 1 else item
                self.emit(symbol, 'LOCAL_CONFIRMED', reason, observed_at, confirmed_local=item)
            # A closed bar can invalidate a previously confirmed anchor during bootstrap/recovery.
            local = row['local']
            if local and bar['open_ts'] >= local['candle_close_ts']:
                breached = bar['low'] < local['price'] if local['kind']=='LOW' else bar['high'] > local['price']
                if breached:
                    local['valid'] = False; local['invalidation_reason'] = 'CLOSED_H1_ANCHOR_BREACH'
        row['h1'] = {'history': [asdict(b) for b in h1.history],
                     'pending': {k: asdict(v) for k,v in h1.pending.items()},
                     'next_ident': h1.next_ident, 'latest_available_ts': h1.latest_available_ts}
        # New risk requires the latest actually closed hour and a successful current fetch.
        m['h1_verified'] = bool(h1.history and h1.history[-1].end == math.floor(observed_at/3600)*3600)
        self.save()

    def control(self, flow):
        c = self.config
        for side in (1, -1):
            response = flow['buy_response_bps'] if side == 1 else -flow['sell_response_bps']
            absorbed = flow['buy_absorption'] if side == 1 else flow['sell_absorption']
            if flow['imbalance']*side >= c.control_imbalance and flow['move_bps']*side > 0 and response > 0 and not absorbed:
                return side
        return 0

    def portfolio(self, now):
        gross = fees = used = exposure = 0.; missing = []
        for symbol,p in self.s['positions'].items():
            m = self._memory(symbol)
            if not m['connected'] or m['mark'] is None or m['received'] is None or not -1 <= now-m['last_ts'] <= self.config.freshness_seconds:
                missing.append(symbol)
            else:
                gross += p['quantity']*(m['mark']-p['entry'])*p['side']
                fees += p['quantity']*m['mark']*(self.config.fee_bps+self.config.slippage_bps)/10000
            used += p['margin']; exposure += p['notional']
        equity = None if missing else self.s['cash']+gross
        return {'cash': self.s['cash'], 'equity': equity, 'realized_pnl': sum(p['pnl'] for p in self.s['closed']),
                'unrealized_pnl': None if missing else gross-fees,
                'estimated_exit_cost': None if missing else fees,
                'used_margin': used, 'free_equity': None if missing else max(0., equity-used-fees),
                'gross_notional': exposure, 'unpriced_positions': missing,
                'start_equity': self.config.start_equity, 'max_equity': self.s['max_equity'],
                'max_drawdown': self.s['max_drawdown']}

    def _close(self, symbol, mark, ts, reason):
        p = self.s['positions'].pop(symbol)
        fill = mark*(1-p['side']*self.config.slippage_bps/10000)
        gross = p['quantity']*(fill-p['entry'])*p['side']
        exit_fee = p['quantity']*fill*self.config.fee_bps/10000
        pnl = gross-p['entry_fee']-exit_fee
        self.s['cash'] += gross-exit_fee
        closed = {**p, 'exit': fill, 'exit_mark': mark, 'closed': ts, 'duration': ts-p['opened'],
                  'exit_fee': exit_fee, 'fees': p['entry_fee']+exit_fee, 'pnl': pnl,
                  'pnl_percent': pnl/p['margin']*100, 'reason': reason,
                  'mfe_captured_percent': pnl/p['mfe']*100 if p['mfe']>0 else None,
                  'mfe_giveback': p['mfe']-pnl,
                  'exit_slippage_usd': abs(fill-mark)*p['quantity']}
        self.s['closed'].append(closed)
        row = self._symbol(symbol); row['pending'] = None
        normal = reason == 'EFFECTIVE_CONTROL_TRANSFER'
        row['watch'] = {'side': p['side'], 'local': p['anchor'], 'exit_price': mark,
                        'exit_at': ts, 'extreme': mark, 'depth_bps': 0., 'cycle_id': p['cycle_id']} if normal else None
        self.decision(symbol, 'EXITED_WAIT_CORRECTION' if normal else 'LOCAL_INVALIDATED', reason, ts,
                      event='EXIT' if normal else 'EMERGENCY_EXIT', position_id=p['position_id'], trade=closed)

    def _open(self, symbol, pending, mark, ts, now):
        row = self._symbol(symbol); local = row['local']; side = pending['side']
        port = self.portfolio(now); instrument = row['instrument']
        limit = min(self.config.leverage, float(instrument.get('max_leverage', 0)))
        if limit < 1 or instrument.get('status') != 'Trading':
            return self.decision(symbol, 'WAIT_ENTRY', 'INSTRUMENT_NOT_READY', ts)
        if port['equity'] is None or port['free_equity'] is None:
            return self.decision(symbol, 'WAIT_ENTRY', 'PORTFOLIO_MARKS_STALE', ts)
        margin = max(0., port['equity'])*self.config.margin_fraction
        notional = margin*limit
        entry_fee = notional*self.config.fee_bps/10000
        exit_reserve = notional*(self.config.fee_bps+self.config.slippage_bps)/10000
        if margin <= 0 or margin+entry_fee+exit_reserve > port['free_equity']:
            return self.decision(symbol, 'WAIT_ENTRY', 'INSUFFICIENT_FREE_EQUITY', ts)
        fill = mark*(1+side*self.config.slippage_bps/10000)
        quantity = notional/fill
        lot=instrument.get('lot_size') or {}
        if lot:
            step=Decimal(str(lot.get('qtyStep','0')))
            if not step.is_finite() or step<=0:
                return self.decision(symbol,'WAIT_ENTRY','INVALID_CONTRACT_LOT_SIZE',ts)
            quantity=float((Decimal(str(quantity))/step).to_integral_value(rounding=ROUND_DOWN)*step)
            notional=quantity*fill; margin=notional/limit; entry_fee=notional*self.config.fee_bps/10000
            if (quantity<float(lot.get('minOrderQty',0)) or notional<float(lot.get('minNotionalValue',0))
                    or quantity<=0 or quantity>float(lot.get('maxMktOrderQty',float('inf')))):
                return self.decision(symbol,'WAIT_ENTRY','CONTRACT_SIZE_LIMIT',ts)
        cycle = pending.get('cycle_id') or self.s['session_id']+':'+symbol+':'+str(self.s['seq']+1)
        ident = cycle+':position:'+str(self.s['seq']+1)
        row['cycle_id'] = cycle
        p = {'position_id': ident, 'symbol': symbol, 'side': side, 'entry': fill, 'entry_mark': mark,
             'opened': ts, 'signal_ts': pending['ts'], 'margin': margin, 'notional': notional,
             'quantity': quantity, 'leverage': limit, 'entry_fee': entry_fee,
             'entry_slippage_usd': abs(fill-mark)*quantity, 'anchor': copy.deepcopy(local),
             'cycle_id': cycle, 'kind': pending['action'], 'mfe': 0., 'mae': 0.,
             'mfe_ts': ts, 'mae_ts': ts, 'mfe_percent': 0., 'mae_percent': 0.}
        self.s['cash'] -= entry_fee; self.s['positions'][symbol] = p; row['watch'] = None
        self.decision(symbol, 'POSITION_REENTRY' if pending['action']=='REENTRY' else ('POSITION_LONG' if side==1 else 'POSITION_SHORT'),
                      'CONFIRMED_H1_EFFECTIVE_FLOW_ACCELERATION', ts, event=pending['action'],
                      position_id=ident, position=copy.deepcopy(p), flow=self._memory(symbol)['flow'])

    def on_trade(self, symbol, ts, price, quantity, side, ident, received_at, now=None):
        now = time.time() if now is None else now
        if symbol not in self.s['active'] or type(side) is not int or side not in (-1,1) or not ident:
            return False
        if any(not math.isfinite(x) or x<=0 for x in (ts, price, quantity, received_at, now)):
            return False
        if not -1 <= now-ts <= self.config.freshness_seconds or not -1 <= now-received_at <= self.config.freshness_seconds:
            return False
        m = self._memory(symbol); row = self._symbol(symbol)
        if not m['connected'] or ident in m['seen'] or m['last_ts'] is not None and ts<m['last_ts']:
            return False
        if m['last_ts'] is not None and ts-m['last_ts'] > self.config.freshness_seconds:
            self.reset_flow([symbol], True, now); m=self._memory(symbol)
        m['seen'][ident] = ts
        # Retain all IDs within the freshness horizon; overflow fails closed rather than evicting fresh IDs.
        while m['seen'] and ts-next(iter(m['seen'].values())) > self.config.freshness_seconds+2:
            m['seen'].popitem(last=False)
        if len(m['seen'])>200000:
            raise RuntimeError('TRADE_DEDUP_CAPACITY_EXCEEDED')
        m.update(last_ts=ts, mark=price, received=received_at)
        local = row['local']
        if local and local['valid'] and (price-local['price'])*(1 if local['kind']=='LOW' else -1)<0:
            local['valid']=False; local['invalidation_reason']='LIVE_ANCHOR_BREACH'
            self.emit(symbol, 'LOCAL_INVALIDATED', 'LIVE_ANCHOR_BREACH', ts)
        p = self.s['positions'].get(symbol)
        if p:
            net = p['quantity']*(price*(1-p['side']*self.config.slippage_bps/10000)-p['entry'])*p['side']
            net -= p['entry_fee']+p['quantity']*price*self.config.fee_bps/10000
            if net>p['mfe']: p.update(mfe=net,mfe_ts=ts,mfe_percent=100*net/p['margin'])
            if net<p['mae']: p.update(mae=net,mae_ts=ts,mae_percent=100*net/p['margin'])
            gross = p['quantity']*(price-p['entry'])*p['side']
            opposite = local and local['valid'] and (1 if local['kind']=='LOW' else -1)==-p['side'] and local['confirmed_time']>p['anchor']['confirmed_time']
            breached = (price-p['anchor']['price'])*p['side']<0
            liquidation = p['margin']+gross <= p['quantity']*price*self.config.maintenance_fraction+p['quantity']*price*self.config.fee_bps/10000
            structural=p.get('structural_reason')
            if liquidation or opposite or breached or structural:
                self._close(symbol,price,ts,'MODELED_MAINTENANCE_BREACH' if liquidation else 'OPPOSITE_CONFIRMED_H1' if opposite else structural or 'ORIGINAL_LOCAL_INVALIDATED')
                self.save(); p=None
        pending = row['pending']
        if pending and ts>pending['ts']:
            row['pending']=None
            if pending['action']=='EXIT' and symbol in self.s['positions']:
                self._close(symbol,price,ts,'EFFECTIVE_CONTROL_TRANSFER'); self.save()
            elif pending['action'] in ('ENTRY','REENTRY') and symbol not in self.s['positions']:
                ready = (now-pending['ts']<=self.config.freshness_seconds and local and local['valid']
                         and local['ident']==pending['local_id'] and (price-local['price'])*pending['side']>0
                         and m['h1_verified'] and m['h1'].history[-1].end==math.floor(now/3600)*3600
                         and side==pending['side'] and (price-pending['price'])*pending['side']>=0)
                if ready:self._open(symbol,pending,price,ts,now)
                else:self.decision(symbol,'WAIT_ENTRY','SIGNAL_INVALIDATED_BEFORE_FILL',ts)
                self.save()
        watch = row['watch']
        if watch and ts>watch['exit_at']:
            watch['extreme'] = min(watch['extreme'],price) if watch['side']==1 else max(watch['extreme'],price)
            watch['depth_bps'] = max(watch['depth_bps'], (watch['exit_price']-watch['extreme'])/watch['exit_price']*10000*watch['side'])
        m['block'].append(Trade(symbol,ts,price,quantity,side,str(ident),received_at))
        if len(m['block'])>=self.config.block_trades:
            flow = features(m['block'], list(m['history']), self.rcfg); m['block']=[]
            flow['effective_control']=self.control(flow)
            m['flow']=flow
            self.evaluate(symbol,flow,now)
            m['history'].append(flow)
            self.save()
        port=self.portfolio(now)
        if port['equity'] is not None:
            self.s['max_equity']=max(self.s['max_equity'],port['equity'])
            self.s['max_drawdown']=max(self.s['max_drawdown'],1-port['equity']/self.s['max_equity'])
        return True

    def evaluate(self, symbol, flow, now):
        m=self._memory(symbol); row=self._symbol(symbol); local=row['local']; ts=flow['ts']
        control=self.control(flow)
        m['control_streak'] = m['control_streak']+1 if control and control==m['last_control'] else int(bool(control))
        m['last_control']=control
        p=self.s['positions'].get(symbol)
        if p:
            m['transfer']=m['transfer']+1 if control==-p['side'] else 0
            if m['transfer']>=self.config.transfer_blocks:
                row['pending']={'action':'EXIT','ts':ts}
                self.decision(symbol,'CONTROL_WEAKENING','EFFECTIVE_CONTROL_TRANSFER',ts,event='EXIT_SIGNAL',flow=flow)
            else:
                self.decision(symbol,'CONTROL_WEAKENING' if control==-p['side'] else ('POSITION_REENTRY' if p['kind']=='REENTRY' else 'POSITION_LONG' if p['side']==1 else 'POSITION_SHORT'),
                              'MICRO_COUNTER_FLOW_NO_CONFIRMED_TRANSFER' if control==-p['side'] else 'NO_OPPOSITE_EFFECTIVE_TAKEOVER',ts,flow=flow)
            return
        if row['pending']:
            return
        if not local or not local['valid']:
            self.decision(symbol,'WAIT_LOCAL','LOCAL_UNCONFIRMED' if not local else 'LOCAL_INVALIDATED',ts); return
        side=1 if local['kind']=='LOW' else -1
        reasons=[]
        if not m['h1_verified'] or m['h1'].history[-1].end!=math.floor(now/3600)*3600:
            reasons.append('H1_HISTORY_NOT_CURRENT')
        if len(m['history'])<self.config.warmup_blocks:reasons.append('FLOW_BASELINE_WARMUP')
        if control!=side:reasons.append('NO_PRICE_RESPONSIVE_CONTROL')
        acceleration=flow['buy_acceleration'] if side==1 else flow['sell_acceleration']
        if acceleration is None or acceleration<=0:reasons.append('NO_ACCELERATION')
        if m['control_streak']<self.config.transfer_blocks:reasons.append('CONTROL_NOT_PERSISTENT')
        if flow['buy_absorption'] if side==1 else flow['sell_absorption']:reasons.append('OWN_ABSORPTION')
        watch=row['watch']; action='REENTRY' if watch else 'ENTRY'
        if watch:
            if watch['local']['ident']!=local['ident'] or watch['side']!=side:
                row['watch']=None
                self.decision(symbol,'LOCAL_INVALIDATED','ORIGINAL_LOCAL_LOST',ts); return
            floor=max(2*(self.config.fee_bps+self.config.slippage_bps),flow['price_scale_bps'])
            if watch['depth_bps']<floor:reasons.append('NO_CORRECTION_DEPTH')
            if (flow['price']-watch['extreme'])*side<=0:reasons.append('CORRECTION_NOT_RECOVERED')
        if reasons:
            state='CORRECTION' if watch and watch['depth_bps']>0 else 'EXITED_WAIT_CORRECTION' if watch else 'WAIT_ENTRY'
            self.decision(symbol,state,'|'.join(reasons),ts,flow=flow); return
        row['pending']={'action':action,'side':side,'ts':ts,'price':flow['price'],
                        'local_id':local['ident'],'cycle_id':watch['cycle_id'] if watch else None}
        self.decision(symbol,'REENTRY_READY' if watch else 'WAIT_ENTRY','AWAIT_STRICTLY_LATER_EXECUTION',ts,event=action+'_SIGNAL',flow=flow)

    def snapshot(self, now=None):
        now=time.time() if now is None else now
        port=self.portfolio(now)
        if port['equity'] is not None:
            self.s['max_equity']=max(self.s['max_equity'],port['equity'])
            self.s['max_drawdown']=max(self.s['max_drawdown'],1-port['equity']/self.s['max_equity'])
            port.update(max_equity=self.s['max_equity'],max_drawdown=self.s['max_drawdown'])
        tokens=[]
        for symbol in self.s['active']:
            m=self._memory(symbol); row=self._symbol(symbol)
            age=None if m['last_ts'] is None else now-m['last_ts']
            fresh=bool(m['connected'] and age is not None and -1<=age<=self.config.freshness_seconds
                       and m['flow'] and -1<=now-m['flow']['ts']<=self.config.freshness_seconds)
            if not fresh:self.decision(symbol,'STALE','NO_FRESH_EXECUTED_FLOW',now)
            public_row={k:copy.deepcopy(v) for k,v in row.items() if k not in ('h1','locals','pending')}
            tokens.append({**public_row,'symbol':symbol,'mark':m['mark'] if fresh else None,
                           'data_age':age,'flow':m['flow'] if fresh else None,'fresh':fresh,
                           'h1_current':bool(m['h1'].history and m['h1'].history[-1].end==math.floor(now/3600)*3600),
                           'state':row['state'],'local_age':now-row['local']['confirmed_time'] if row['local'] else None})
        positions=[]
        for symbol,p in self.s['positions'].items():
            m=self._memory(symbol); fresh=m['last_ts'] is not None and -1<=now-m['last_ts']<=self.config.freshness_seconds
            mark=m['mark'] if fresh else None
            net=None if mark is None else p['quantity']*(mark-p['entry'])*p['side']-p['entry_fee']-p['quantity']*mark*(self.config.fee_bps+self.config.slippage_bps)/10000
            positions.append({**copy.deepcopy(p),'mark':mark,'pnl':net,'pnl_percent':None if net is None else net/p['margin']*100,'holding_seconds':now-p['opened']})
        scanner_current=bool(self.s['scanner'] and now-self.s['scanner'].get('observed_at',0)<=2*self.config.scanner_seconds+15)
        online=bool(tokens and scanner_current and all(t['fresh'] and t['h1_current'] for t in tokens))
        self.save()
        return {'schema_version':1,'snapshot_at':now,'status':'ONLINE' if online else 'STALE',
                'session_id':self.s['session_id'],'run_id':self.run_id,'uptime':now-self.s['started'],
                'mode':'PAPER_ONLY','metadata':METADATA,'config':asdict(self.config),'portfolio':port,
                'tokens':tokens,'positions':positions,'closed':list(reversed(self.s['closed']))[:200],
                'closed_count':len(self.s['closed']),'events':self.store.recent_events(),
                'scanner':self.s['scanner'],'checkpoint_at':self.s['checkpoint_at']}

    def checkpoint(self):
        self.s['checkpoint_at']=time.time(); self.save()
        return self.store.export(self.s)
