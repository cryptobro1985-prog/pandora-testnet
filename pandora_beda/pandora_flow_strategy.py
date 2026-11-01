"""Executed-trade state machine for the ``pandora_flow_v2`` PAPER experiment.

Only accepted, independent executions advance proofs. Exchange timestamps select
measurement samples; receive/poll timestamps never confirm a direction. Three
executions are the named minimum for persistence (the old two-print minimum
cannot distinguish an initial print from an independently maintained response).
Execution acknowledgements, rather than recommendations, change position state.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from bisect import bisect_left
from collections import deque
from decimal import Decimal
import math

from pandora_flow import MIN_CONTROL_IMBALANCE, WINDOWS
from pandora_risk import RiskPolicy

EXPERIMENT_ID = 'pandora_flow_v2'


@dataclass(frozen=True)
class FlowConfig:
    min_control_events: int = 3
    minimum_control_imbalance: float = MIN_CONTROL_IMBALANCE
    # Existing measurement horizons, without a completed-window requirement.
    fast_seconds: int = 5
    sustained_seconds: int = 15
    confirmation_seconds: int = 30
    context_seconds: int = 60
    history_seconds: int = 600
    # Bound persisted tape and per-event work on very busy symbols. All proofs
    # also retain their own acknowledgement/structure boundaries.
    max_history_events: int = 4096
    freshness_limit_seconds: float = 60.

    def __post_init__(self):
        if self.min_control_events < 3:
            raise ValueError('control requires at least three independent events')
        if self.max_history_events < self.min_control_events:
            raise ValueError('history must retain enough independent executions')
        if not 0 < self.minimum_control_imbalance < 1:
            raise ValueError('invalid control imbalance')
        if min(self.fast_seconds, self.sustained_seconds, self.confirmation_seconds,
               self.context_seconds, self.history_seconds, self.freshness_limit_seconds) <= 0:
            raise ValueError('measurement horizons must be positive')


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _side(value):
    if value in (1, 'B', 'BUY', 'Buy', 'buy', 'LONG', 'long'):
        return 1
    if value in (-1, 'A', 'SELL', 'Sell', 'sell', 'SHORT', 'short'):
        return -1
    return 0


def _position_side(position):
    return _side((position or {}).get('side'))


def _name(side):
    return 'LONG' if side == 1 else 'SHORT' if side == -1 else 'FLAT'


def _measure(sample, epoch, seconds, previous=()):
    """Same executed-volume/causal-response definitions as pandora_flow.

    Computing the metrics here avoids that legacy summarizer's completed-window
    directional gates and its reconstruction of time-based dominance duration.
    """
    buy = sell = buy_quantity = sell_quantity = 0.
    buy_count = sell_count = 0
    buy_response = sell_response = 0.
    buy_response_count = sell_response_count = 0
    recent_buy = recent_sell = old_buy = old_sell = 0.
    high = low = previous_price = None
    midpoint = epoch-seconds/2
    for row in sample:
        price, volume, side = row['price'], row['notional'], row['side']
        change = price/previous_price-1 if previous_price is not None else 0.
        if side == 1:
            buy += volume
            buy_quantity += volume/price
            buy_count += 1
            buy_response += change
            buy_response_count += change > 0
            if row['exchange_epoch'] >= midpoint:
                recent_buy += volume
            else:
                old_buy += volume
        else:
            sell += volume
            sell_quantity += volume/price
            sell_count += 1
            sell_response -= change
            sell_response_count += change < 0
            if row['exchange_epoch'] >= midpoint:
                recent_sell += volume
            else:
                old_sell += volume
        high = price if high is None else max(high, price)
        low = price if low is None else min(low, price)
        previous_price = price
    count = len(sample)
    total = buy+sell
    elapsed = max(.001, min(seconds, epoch-sample[0]['exchange_epoch'])) if sample else .001
    move = sample[-1]['price']/sample[0]['price']-1 if count>1 else 0.
    recent_volume, old_volume = recent_buy+recent_sell, old_buy+old_sell
    recent_imbalance = (recent_buy-recent_sell)/recent_volume if recent_volume else 0.
    old_imbalance = (old_buy-old_sell)/old_volume if old_volume else 0.
    return dict(buy_volume=buy, sell_volume=sell, buy_notional=buy,
                sell_notional=sell, buy_quantity=buy_quantity, sell_quantity=sell_quantity,
                buy_trade_count=buy_count, sell_trade_count=sell_count,
                trade_count=count, imbalance=(buy-sell)/total if total else 0.,
                buy_sell_ratio=buy/sell if sell else None,
                volume_velocity=total/elapsed, trade_velocity=count/elapsed,
                volume_change=total-sum(r['notional'] for r in previous),
                volume_acceleration=(recent_volume-old_volume)/(seconds/2),
                imbalance_change=recent_imbalance-old_imbalance,
                price_return=move, price_high=high, price_low=low,
                price_range_fraction=(high-low)/sample[-1]['price'] if count else 0.,
                buy_price_response=buy_response, sell_price_response=sell_response,
                buy_response_event_count=buy_response_count,
                sell_response_event_count=sell_response_count,
                buy_absorbed=buy>sell and (move<=0 or buy_response<=0),
                sell_absorbed=sell>buy and (move>=0 or sell_response<=0),
                observed_seconds=min(seconds, max(0., epoch-sample[0]['exchange_epoch'])) if sample else 0.)


class _MeasurementCache:
    """Transient prefix sums and extrema, rebuilt from durable tape on restore.

    Decimal prefix arithmetic avoids cancellation changing a 60/40 boundary
    after a restart. Converting each independently computed response once also
    keeps restore and uninterrupted sums equal. No cache is decision evidence.
    """
    def __init__(self, events, horizons):
        self.rows, self.epochs = [], []
        self.sums = [(Decimal(0),)*10]
        self.responses = []
        self.extrema = {seconds: (deque(), deque()) for seconds in horizons}
        for event in events:
            self.append(event)

    def append(self, event):
        index = len(self.rows)
        price, volume, side = event['price'], event['notional'], event['side']
        change = price/self.rows[-1]['price']-1 if self.rows else 0.
        volume, quantity, change = Decimal(str(volume)), Decimal(str(volume/price)), Decimal(str(change))
        zero, one = Decimal(0), Decimal(1)
        values = ((volume,zero,quantity,zero,one,zero,change,zero,one if change>0 else zero,zero)
                  if side == 1 else
                  (zero,volume,zero,quantity,zero,one,zero,-change,zero,one if change<0 else zero))
        self.sums.append(tuple(a+b for a,b in zip(self.sums[-1], values)))
        self.responses.append((values[6], values[7], values[8], values[9]))
        self.rows.append(event)
        self.epochs.append(event['exchange_epoch'])
        for high, low in self.extrema.values():
            while high and self.rows[high[-1]]['price'] <= price:
                high.pop()
            while low and self.rows[low[-1]]['price'] >= price:
                low.pop()
            high.append(index)
            low.append(index)

    def _start(self, epoch, seconds, retained_start):
        start = max(retained_start, bisect_left(self.epochs, epoch-seconds))
        # Match the measurement predicate exactly at floating-point boundaries.
        while start > retained_start and epoch-self.epochs[start-1] <= seconds:
            start -= 1
        while start < len(self.rows) and epoch-self.epochs[start] > seconds:
            start += 1
        return start

    def measure(self, seconds, epoch, retained_start):
        start = self._start(epoch, seconds, retained_start)
        half = self._start(epoch, seconds/2, retained_start)
        prior = self._start(epoch, 2*seconds, retained_start)
        latest, beginning = self.sums[-1], self.sums[start]
        values = [float(a-b) for a,b in zip(latest, beginning)]
        buy, sell, buy_quantity, sell_quantity, buy_count, sell_count, buy_response, sell_response, buy_response_count, sell_response_count = values
        if start < len(self.rows):
            buy_response = float(latest[6]-beginning[6]-self.responses[start][0])
            sell_response = float(latest[7]-beginning[7]-self.responses[start][1])
            buy_response_count = int(latest[8]-beginning[8]-self.responses[start][2])
            sell_response_count = int(latest[9]-beginning[9]-self.responses[start][3])
        recent_buy, recent_sell = (float(latest[i]-self.sums[half][i]) for i in (0,1))
        old_buy, old_sell = (float(self.sums[half][i]-beginning[i]) for i in (0,1))
        previous_volume = sum(float(beginning[i]-self.sums[prior][i]) for i in (0,1))
        total, count = buy+sell, len(self.rows)-start
        recent_volume, old_volume = recent_buy+recent_sell, old_buy+old_sell
        move = self.rows[-1]['price']/self.rows[start]['price']-1 if count>1 else 0.
        observed = min(seconds, max(0., epoch-self.epochs[start])) if count else 0.
        elapsed = max(.001, observed)
        high_queue, low_queue = self.extrema[seconds]
        for queue in (high_queue, low_queue):
            while queue and queue[0] < start:
                queue.popleft()
        high = self.rows[high_queue[0]]['price'] if high_queue else None
        low = self.rows[low_queue[0]]['price'] if low_queue else None
        return dict(buy_volume=buy,sell_volume=sell,buy_notional=buy,sell_notional=sell,
                    buy_quantity=buy_quantity,sell_quantity=sell_quantity,
                    buy_trade_count=int(buy_count),sell_trade_count=int(sell_count),trade_count=count,
                    imbalance=(buy-sell)/total if total else 0.,buy_sell_ratio=buy/sell if sell else None,
                    volume_velocity=total/elapsed,trade_velocity=count/elapsed,
                    volume_change=total-previous_volume,
                    volume_acceleration=(recent_volume-old_volume)/(seconds/2),
                    imbalance_change=((recent_buy-recent_sell)/recent_volume if recent_volume else 0.)-((old_buy-old_sell)/old_volume if old_volume else 0.),
                    price_return=move,price_high=high,price_low=low,
                    price_range_fraction=(high-low)/self.rows[-1]['price'] if count else 0.,
                    buy_price_response=buy_response,sell_price_response=sell_response,
                    buy_response_event_count=buy_response_count,
                    sell_response_event_count=sell_response_count,
                    buy_absorbed=buy>sell and (move<=0 or buy_response<=0),
                    sell_absorbed=sell>buy and (move>=0 or sell_response<=0),
                    observed_seconds=observed)


class FlowStrategy:
    def __init__(self, state=None, config=None):
        self.config = config if isinstance(config, FlowConfig) else FlowConfig(**(config or {}))
        self.tokens = {}
        self._measurement_caches = {}
        if state is not None:
            self.restore(state)

    def restore(self, state):
        """Restore the whole causal history/proofs; do not seed fresh evidence."""
        if state.get('experiment_id', EXPERIMENT_ID) != EXPERIMENT_ID:
            raise ValueError('flow state belongs to a different experiment')
        if state.get('config'):
            self.config = FlowConfig(**state['config'])
        self.tokens = deepcopy(state.get('tokens') or {})
        self._measurement_caches = {}
        return self

    def to_dict(self):
        return dict(experiment_id=EXPERIMENT_ID, version=2,
                    config=asdict(self.config), tokens=deepcopy(self.tokens))

    def _token(self, symbol):
        return self.tokens.setdefault(symbol, dict(
            symbol=symbol, events=[], last_sequence=0, event_count=0,
            last_exchange_epoch=None, last_receive_epoch=None,
            flow_regime='NEUTRAL', position_state='FLAT', actual_side=0,
            sequence_valid=True, data_fresh=False, uncertainty_reason=None,
            dominance_side=0, dominance_persistence_events=0,
            pressure_state={}, exit_latched=False, close_ack=None,
            reentry_count=0, last_decision=None))

    def _control(self, measurement):
        imbalance = measurement['imbalance']
        side = 1 if imbalance >= self.config.minimum_control_imbalance else -1 if imbalance <= -self.config.minimum_control_imbalance else 0
        prefix = 'buy' if side == 1 else 'sell'
        return side if (side and measurement[prefix+'_trade_count'] >= self.config.min_control_events
                        # Three prints need two independent causal advances;
                        # old flat prints plus one spike are not continuation.
                        and measurement[prefix+'_response_event_count'] >= self.config.min_control_events-1
                        and measurement[prefix+'_price_response'] > 0
                        and measurement['price_return']*side > 0
                        and not measurement[prefix+'_absorbed']) else 0

    def _metrics(self, token):
        events = token['events']
        if not events:
            return {}
        epoch = events[-1]['exchange_epoch']
        horizons = sorted(set(WINDOWS + (self.config.fast_seconds,
                              self.config.sustained_seconds, self.config.confirmation_seconds,
                              self.config.context_seconds)))
        windows = {}
        cache = self._measurement_caches.get(token['symbol'])
        if (cache is None or not cache.rows or cache.rows[-1]['sequence'] > events[-1]['sequence']
                or (cache.rows[-1]['sequence'] != events[-1]['sequence']
                    and (len(events)<2 or cache.rows[-1]['sequence'] != events[-2]['sequence']))
                or len(cache.rows) >= 2*self.config.max_history_events):
            cache = _MeasurementCache(events, horizons)
            self._measurement_caches[token['symbol']] = cache
        elif cache.rows[-1]['sequence'] != events[-1]['sequence']:
            cache.append(events[-1])
        retained_start = max(0, len(cache.rows)-len(events))
        for seconds in horizons:
            windows[str(seconds)] = cache.measure(seconds, epoch, retained_start)
        fast = self._control(windows[str(self.config.fast_seconds)])
        medium = self._control(windows[str(self.config.sustained_seconds)])
        confirmation = self._control(windows[str(self.config.confirmation_seconds)])
        sustained = medium if medium and medium == confirmation else 0
        context_window = windows[str(self.config.context_seconds)]
        context = self._control(context_window)
        flow = deepcopy(context_window)
        flow.update(windows=windows, fast_control_side=fast,
                    sustained_control_side=sustained, context_control_side=context,
                    control_side=sustained if sustained == fast else 0,
                    exit_control_side=sustained,
                    dominance_side=token['dominance_side'],
                    dominance_persistence_events=token['dominance_persistence_events'],
                    minimum_control_imbalance=self.config.minimum_control_imbalance,
                    minimum_control_events=self.config.min_control_events,
                    evidence_ready=len(events)>=self.config.min_control_events,
                    latest_trade_epoch=token['last_exchange_epoch'],
                    latest_exchange_epoch=token['last_exchange_epoch'],
                    latest_receive_epoch=token['last_receive_epoch'],
                    latest_sequence=token['last_sequence'],
                    execution_sequence=token['last_sequence'],
                    flow_imbalance=context_window['imbalance'],
                    decision_event_epoch=token['last_exchange_epoch'],
                    trade_data_fresh=token['data_fresh'],
                    sequence_valid=token['sequence_valid'],
                    latest_trade_age_seconds=0.,
                    freshness_limit_seconds=self.config.freshness_limit_seconds,
                    price_direction=1 if context_window['price_return']>0 else -1 if context_window['price_return']<0 else 0)
        for prefix in ('buy', 'sell'):
            flow[prefix+'_absorbed'] = any(windows[str(seconds)][prefix+'_absorbed']
                                          for seconds in (self.config.fast_seconds, self.config.sustained_seconds))
        return flow

    def _analysis(self, token, flow, side):
        window = (flow.get('windows') or {}).get(str(self.config.confirmation_seconds)) or {}
        pressure = deepcopy(token.get('pressure_state') or {})
        return dict(ready=bool(side), anchor_confirmed=bool(side), entry_side=side,
                    entry_blocked=not bool(side), source='executed_flow_price_geometry',
                    pivot_price=window.get('price_low' if side == 1 else 'price_high'),
                    pressure_state=pressure)

    def _regime(self, flow):
        strong = flow.get('control_side', 0)
        if strong:
            return 'BUY_CONTROL' if strong == 1 else 'SELL_CONTROL'
        window = (flow.get('windows') or {}).get(str(self.config.sustained_seconds)) or {}
        imbalance = window.get('imbalance', 0.)
        if imbalance >= self.config.minimum_control_imbalance:
            return 'BUY_WEAKENING'
        if imbalance <= -self.config.minimum_control_imbalance:
            return 'SELL_WEAKENING'
        return 'NEUTRAL'

    def _sync_position(self, symbol, position):
        token = self._token(symbol)
        side = _position_side(position)
        if side and token.get('actual_side') != side:
            self.on_open(symbol, side, float(position['entry']))
        elif not side and token.get('actual_side'):
            # Reconcile an execution committed by the money engine before a
            # restart. Flat acknowledgement starts a new proof boundary.
            price = token['events'][-1]['price'] if token['events'] else 0.
            self.on_close(symbol, token['actual_side'], price)
        return token, side

    def _advance_structure(self, token, side, price, flow, costs):
        state = token.setdefault('pressure_state', {})
        x = side*price
        best = state.get('best', x)
        noise = max(0., state.get('noise', 0.))
        candidate = state.get('candidate')
        if x >= best:
            if candidate:
                # The latest defended pullback describes the current auction.
                # Keeping the lifetime maximum can make an old violent swing
                # prevent every later, genuinely confirmed exit.
                noise = max(0., best-candidate['counter_extreme'])
                state['barrier'] = candidate['counter_extreme']
            state.update(best=x, noise=noise, candidate=None, phase='HOLDING')
            state.update(counter_control_side=0, counter_trade_count=0,
                         material_counter_move=False)
            token['exit_latched'] = False
            return False
        if token.get('exit_latched'):
            recovery_rows = [r for r in token['events']
                             if r['sequence'] > state.get('confirmation_sequence', token['last_sequence'])]
            recovery = _measure(recovery_rows, token['last_exchange_epoch'], self.config.history_seconds)
            if self._control(recovery) == side:
                # A fresh independent resumption invalidates an unexecuted
                # CLOSE even if the former favorable extreme is not revisited.
                token['exit_latched'] = False
                if candidate:
                    state['barrier'] = candidate['counter_extreme']
                state.update(candidate=None, phase='HOLDING',
                             recovery_sequence=token['last_sequence'])
                return False
        if candidate is None:
            candidate = dict(counter_extreme=x, retest_best=None,
                             start_sequence=token['last_sequence'],
                             start_event_count=token['event_count'],
                             anchor_price=best*side)
            state['candidate'] = candidate
        old_counter = candidate['counter_extreme']
        leg_events = [r for r in token['events'] if r['sequence'] >= candidate['start_sequence']]
        # Include the favorable extreme as the causal response anchor, without
        # attributing its executed volume to the new counter leg.
        leg = _measure(leg_events, token['last_exchange_epoch'], self.config.history_seconds)
        leg['price_return'] = price/candidate['anchor_price']-1
        leg_control = self._control(leg)
        material = best-x > max(noise, price*costs)
        break_barrier = state.get('barrier') is not None and x < state['barrier']
        failed_retest = (candidate.get('retest_best') is not None
                         and candidate['retest_best'] < best and x < old_counter)
        sustained = flow.get('sustained_control_side', 0)
        context = flow.get('context_control_side', 0)
        # An intact broader auction defends a transient fast counter spike.
        # Older volume can be superseded by an independently confirmed break
        # of a previously defended price boundary or a failed continuation.
        transferred = (sustained == -side or (leg_control == -side and
                       (break_barrier or failed_retest or context != side)))
        confirmed = material and transferred and leg_control == -side
        if sustained == side and leg_control == side:
            token['exit_latched'] = False
        if confirmed:
            token['exit_latched'] = True
            state['confirmation_sequence'] = token['last_sequence']
            state['confirmation_basis'] = 'defended_boundary_break' if break_barrier else 'failed_continuation' if failed_retest else 'sustained_executed_takeover'
        if flow.get('fast_control_side') == side and x > old_counter:
            candidate['retest_best'] = max(x, candidate.get('retest_best') or x)
        candidate['counter_extreme'] = min(x, old_counter)
        state.update(best=best, noise=noise,
                     phase='COUNTER_MOVE_CONFIRMED' if token['exit_latched'] else 'WEAKENING_OBSERVE',
                     material_counter_move=material, counter_control_side=leg_control,
                     counter_trade_count=leg['sell_trade_count' if side == 1 else 'buy_trade_count'],
                     cost_noise_floor=max(noise, price*costs))
        return token['exit_latched']

    def _post_close_control(self, token):
        close = token.get('close_ack')
        if not close:
            return 0, None
        rows = [r for r in token['events'] if r['sequence'] > close['sequence']
                and token['last_exchange_epoch']-r['exchange_epoch'] <= self.config.confirmation_seconds]
        if len(rows) < self.config.min_control_events:
            return 0, None
        evidence = _measure(rows, token['last_exchange_epoch'], self.config.history_seconds)
        side = self._control(evidence)
        close['post_close_event_count'] = len(rows)
        close['post_close_control_side'] = side
        return side, evidence

    def _decide(self, token, side, selected_entry, policy, new_event, metrics=None):
        flow = metrics if metrics is not None else self._metrics(token)
        regime = self._regime(flow)
        token['flow_regime'] = regime
        before = token['position_state']
        action, wanted, reason = 'WAIT', 0, 'Independent executed control and causal price response are not confirmed.'
        costs = 2*(policy.fee+policy.slippage)
        if not token.get('data_fresh') or not token.get('sequence_valid') or not token['events']:
            action = 'DATA_UNCERTAIN'
            reason = token.get('uncertainty_reason') or 'Fresh, sequenced executed trades are required; stale evidence cannot confirm direction.'
        elif side:
            price = token['events'][-1]['price']
            close = self._advance_structure(token, side, price, flow, costs) if new_event else token.get('exit_latched', False)
            wanted = side
            action = 'CLOSE' if close else 'HOLD'
            reason = 'Independent opposite executions transferred control beyond observed noise and execution costs.' if close else 'Existing position retains broader flow or the counter move is within observed noise and execution costs.'
            token['position_state'] = _name(side)+'_EXIT_CONFIRMING' if close else _name(side)
        elif not selected_entry:
            reason = 'Symbol is outside the active entry set; only existing exposure is managed.'
        else:
            wanted = flow.get('control_side', 0)
            close = token.get('close_ack')
            if close:
                # Only newly executed trades after the actual close count.
                wanted, evidence = self._post_close_control(token)
                if flow.get('fast_control_side') == -wanted:
                    wanted = 0
                if wanted and wanted == close['side'] and not close.get('counter_control_seen'):
                    wanted = 0
                    reason = 'Reentry requires a real opposite-flow pullback before independent resumption.'
                elif not wanted:
                    reason = 'Reversal or reentry needs independent new executions after the actual close.'
                if wanted and evidence:
                    price = token['events'][-1]['price']
                    # A resumed auction can reenter below the former exit;
                    # require meaningful new causal movement, not recovery of
                    # an old price level or a fixed profit/loss percentage.
                    # Signed responses can accumulate through spread bounces
                    # while net displacement is negligible. Costs must be
                    # covered by actual directional progress, not their sum.
                    distance = wanted*evidence['price_return']
                    observed_noise = close.get('noise', 0.)/price
                    if distance <= max(costs, observed_noise):
                        wanted = 0
                        reason = 'Post-close movement remains within observed noise and round-trip execution costs.'
            if wanted and not close:
                recent=flow['windows'][str(self.config.fast_seconds)]
                if wanted*recent['price_return']<=costs:
                    wanted=0
                    reason='Observed directional progress does not cover round-trip fees and slippage.'
            if wanted:
                action = 'REENTRY' if close and wanted == close['side'] else 'OPEN'
                if close:
                    flow.update(control_side=wanted, sustained_control_side=wanted,
                                control_basis='post_actual_close_independent_executions')
                    regime = 'BUY_CONTROL' if wanted == 1 else 'SELL_CONTROL'
                reason = ('Independent flow resumed after a real counter-flow pullback.' if action == 'REENTRY'
                          else 'Independent executed control and causal price response confirm '+_name(wanted).lower()+'.')
        token['flow_regime'] = regime
        result = dict(symbol=token['symbol'], action=action, side=wanted,
                      reason=reason, flow_regime=regime, position_state=token['position_state'],
                      state_before=before, state_after=token['position_state'],
                      flow=flow, analysis=self._analysis(token, flow, wanted),
                      new_event=bool(new_event), sequence=token['last_sequence'],
                      action_id=f"{EXPERIMENT_ID}:{token['symbol']}:{token['last_sequence']}:{action}:{wanted}",
                      exchange_epoch=token['last_exchange_epoch'], received_epoch=token['last_receive_epoch'],
                      data_quality='VALID_TAPE' if token.get('data_fresh') and token.get('sequence_valid') else 'DATA_UNCERTAIN')
        token['last_decision'] = deepcopy(result)
        return result

    def ingest(self, symbol, event, *, position=None, selected_entry=True, policy=None, data_fresh=True):
        token, side = self._sync_position(symbol, position)
        policy = policy or RiskPolicy()
        epoch = _number(event.get('exchange_epoch'))
        received = _number(event.get('received_epoch', event.get('receive_epoch', epoch)))
        price = _number(event.get('price'))
        notional = _number(event.get('notional'))
        size = _number(event.get('size', event.get('quantity')))
        if notional is None and price is not None and size is not None:
            notional = price*size
        aggressor = _side(event.get('aggressor_side', event.get('side')))
        identity = str(event.get('id', event.get('event_id', event.get('trade_id', event.get('tid', '')))))
        sequence = _number(event.get('sequence'))
        if (not identity or epoch is None or received is None or price is None or price<=0
                or notional is None or notional<=0 or not aggressor or sequence is None
                or sequence != int(sequence) or sequence<=0):
            token.update(sequence_valid=False, data_fresh=False,
                         uncertainty_reason='Invalid executed trade or missing independent identity/sequence.')
            return self._decide(token, side, selected_entry, policy, False)
        sequence = int(sequence)
        if sequence <= token['last_sequence'] or any(r['id']==identity for r in token['events']):
            # Replayed/polled trades are observation only and cannot create an
            # execution recommendation for a caller that honors new_event.
            return self._decide(token, side, selected_entry, policy, False)
        if token['last_exchange_epoch'] is not None and epoch < token['last_exchange_epoch']:
            token.update(sequence_valid=False, data_fresh=False,
                         uncertainty_reason='Out-of-order exchange event; fresh ordered tape is required.')
            return self._decide(token, side, selected_entry, policy, False)
        row = dict(id=identity, sequence=sequence, exchange_epoch=epoch,
                   received_epoch=received, price=price, notional=notional, side=aggressor)
        token['events'].append(row)
        token['events'] = [r for r in token['events'] if epoch-r['exchange_epoch'] <= self.config.history_seconds][-self.config.max_history_events:]
        token.update(last_sequence=sequence, last_exchange_epoch=epoch,
                     last_receive_epoch=received, event_count=token['event_count']+1,
                     sequence_valid=True, data_fresh=bool(data_fresh),
                     uncertainty_reason=None if data_fresh else 'Executed tape is stale; no new directional decision is allowed.')
        measurements = self._metrics(token)
        imbalance = measurements.get('imbalance', 0.)
        dominant = 1 if imbalance >= self.config.minimum_control_imbalance else -1 if imbalance <= -self.config.minimum_control_imbalance else 0
        if dominant != token.get('dominance_side'):
            token['dominance_persistence_events'] = 0
        if dominant and aggressor == dominant:
            token['dominance_persistence_events'] += 1
        token['dominance_side'] = dominant
        close = token.get('close_ack')
        if close and measurements.get('sustained_control_side') == -close['side']:
            close['counter_control_seen'] = True
        measurements.update(dominance_side=token['dominance_side'],
                            dominance_persistence_events=token['dominance_persistence_events'])
        return self._decide(token, side, selected_entry, policy, True, measurements)

    def evaluate(self, symbol, *, position=None, selected_entry=True, policy=None, data_fresh=None):
        """Read the recommendation without growing any execution proof."""
        token = self._token(symbol)
        # A monitoring call must not acknowledge execution or refresh tape.
        if data_fresh is False:
            return self.mark_data_uncertain(symbol, position=position,
                                            selected_entry=selected_entry, policy=policy)
        saved = deepcopy(token)
        result = self._decide(token, _position_side(position), selected_entry, policy or RiskPolicy(), False)
        self.tokens[symbol] = saved
        return result

    def on_open(self, symbol, side, price):
        token = self._token(symbol)
        side, price = _side(side), _number(price)
        if not side or price is None or price<=0:
            raise ValueError('actual open requires a valid side and price')
        if (token.get('actual_side') == side and (token.get('open_ack') or {}).get('sequence') == token['last_sequence']
                and (token.get('open_ack') or {}).get('price') == price):
            return
        close = token.get('close_ack')
        if close and close['side'] == side:
            token['reentry_count'] += 1
        token.update(actual_side=side, position_state=_name(side), exit_latched=False,
                     pressure_state=dict(best=side*price, noise=0., candidate=None, phase='HOLDING'),
                     open_ack=dict(side=side, price=price, sequence=token['last_sequence']))

    def on_close(self, symbol, side, price):
        token = self._token(symbol)
        side, price = _side(side), _number(price)
        if not side or price is None or price<=0:
            raise ValueError('actual close requires a valid side and price')
        if token.get('actual_side') == 0 and (token.get('close_ack') or {}).get('sequence') == token['last_sequence']:
            return
        flow = self._metrics(token)
        token.update(actual_side=0, position_state='FLAT_AFTER_'+_name(side),
                     close_ack=dict(side=side, price=price, sequence=token['last_sequence'],
                                    closed_event_sequence=token['last_sequence'],
                                    event_count=token['event_count'],
                                    noise=(token.get('pressure_state') or {}).get('noise', 0.),
                                    counter_control_seen=bool(token.get('exit_latched') or flow.get('sustained_control_side') == -side),
                                    post_close_event_count=0, post_close_control_side=0),
                     exit_latched=False)

    def get_state(self, symbol):
        return deepcopy(self._token(symbol))

    def reset_observation(self, symbol, reason, sequence=None):
        """A transport gap invalidates proofs without erasing actual exposure.

        Keep learned price geometry, acknowledged fills and cycle counts. Tape
        after the gap must independently prove control; a prior CLOSE latch
        cannot be executed from incomplete observation.
        """
        token = self._token(symbol)
        self._measurement_caches.pop(symbol, None)
        token.update(events=[], dominance_side=0, dominance_persistence_events=0,
                     flow_regime='NEUTRAL', sequence_valid=False, data_fresh=False,
                     uncertainty_reason=reason, exit_latched=False, last_decision=None)
        if sequence is not None:
            token['last_sequence'] = int(sequence)
        if token.get('actual_side'):
            token['position_state'] = _name(token['actual_side'])
        return deepcopy(token)

    def mark_data_uncertain(self, symbol, *, position=None, selected_entry=True, policy=None,
                            reason='Executed trade stream is stale or unavailable.'):
        token = self._token(symbol)
        token.update(data_fresh=False, uncertainty_reason=reason)
        return self._decide(token, _position_side(position), selected_entry, policy or RiskPolicy(), False)

    def data_loss_protection(self, symbol, mark, *, position, mark_fresh, policy=None):
        """Separate loss-of-tape policy using a fresh independent mark.

        Staleness alone never closes. A fresh mark must break the observed
        counter-move boundary by execution costs/learned noise. This references
        the causal auction, rather than a fixed loss or profit percentage, and
        never recommends opening an opposite direction.
        """
        token = self._token(symbol)
        side = _position_side(position)
        price = _number(mark)
        policy = policy or RiskPolicy()
        state = token.get('pressure_state') or {}
        best = state.get('best')
        boundary = state.get('barrier')
        candidate = state.get('candidate') or {}
        if boundary is None:
            boundary = candidate.get('counter_extreme', best)
        costs = 2*(policy.fee+policy.slippage)
        floor = max(float(state.get('noise', 0.)), (price or 0.)*costs)
        valid = bool(side and price is not None and price>0 and mark_fresh
                     and not token.get('data_fresh') and boundary is not None)
        breached = valid and side*price < boundary-floor
        return dict(symbol=symbol, action='CLOSE' if breached else 'DATA_UNCERTAIN',
                    side=side, new_event=False, protective=True,
                    action_id=f"{EXPERIMENT_ID}:{symbol}:data_loss:{token['last_sequence']}",
                    reference_price=side*boundary if boundary is not None and side else None,
                    cost_noise_floor=floor,
                    reason='Fresh independent mark broke the last flow-observed adverse boundary during data loss.' if breached else 'Data loss blocks direction; protection requires a fresh mark beyond the observed adverse boundary.',
                    data_quality='DATA_UNCERTAIN')
