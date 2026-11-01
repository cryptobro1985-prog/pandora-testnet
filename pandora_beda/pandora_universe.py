"""Persisted hourly entry universe, independent from continuous discovery.

The clock only chooses the symbols eligible for new entries. Rotation emits
metadata events; it never emits a trading instruction or closes a position.
"""
import copy
import math
import threading
import time


class HourlyUniverse:
    INTERVAL_SECONDS = 3600
    SELECTION_REASON = 'highest_live_movement_and_volume_activity_rank_at_hourly_refresh'

    def __init__(self, top=5, state=None):
        if not 1 <= int(top) <= 5:
            raise ValueError('hourly universe must contain between one and five symbols')
        self.top = int(top)
        self.lock = threading.RLock()
        self.last_refresh_at = None
        self.next_refresh_at = None
        self.selected = []
        self.managed_symbols = []
        self.states = {}
        if state:
            self.restore(state)

    @staticmethod
    def _epoch(epoch):
        stamp = time.time() if epoch is None else float(epoch)
        if not math.isfinite(stamp) or stamp < 0:
            raise ValueError('invalid universe timestamp')
        return stamp

    @staticmethod
    def _symbols(symbols):
        return list(dict.fromkeys(str(symbol) for symbol in symbols if symbol))

    @property
    def entry_symbols(self):
        with self.lock:
            return tuple(row['symbol'] for row in self.selected)

    @property
    def current_entry_set(self):
        return self.entry_symbols

    def due(self, epoch=None):
        stamp = self._epoch(epoch)
        with self.lock:
            return self.next_refresh_at is None or stamp >= self.next_refresh_at

    @staticmethod
    def _ranked_rows(discovery):
        # ranked_rows is the complete cross section, before the scanner's legacy
        # subscription warmup/hysteresis. top_movers supports older checkpoints.
        rows = discovery.get('ranked_rows')
        if rows is None:
            rows = discovery.get('top_movers')
        if rows is None:
            rows = discovery.get('selected') or []
        return [row for row in rows if isinstance(row, dict) and row.get('symbol')
                and row.get('eligible', True) and not row.get('fading', False)]

    def _track_positions(self, held):
        selected = set(self.entry_symbols)
        self.managed_symbols = [symbol for symbol in self._symbols(held) if symbol not in selected]
        for symbol in list(self.states):
            if symbol not in selected and symbol not in self.managed_symbols:
                self.states[symbol] = 'ROTATE_OUT'
        for symbol in selected:
            self.states[symbol] = 'SELECTED'
        for symbol in self.managed_symbols:
            self.states[symbol] = 'MANAGED_POSITION'

    def update(self, discovery, held=(), epoch=None):
        """Observe discovery and commit its top ranks only when refresh is due.

        Pass the live open-position symbols on each update. A disconnected or
        empty discovery does not consume the hourly refresh; the previous entry
        set remains visible until fresh ranking is available.
        """
        stamp = self._epoch(epoch)
        discovery = discovery or {}
        events = []
        with self.lock:
            refresh_due = self.due(stamp)
            rows = self._ranked_rows(discovery)
            ready = discovery.get('observations_ready', bool(rows)) is True
            refreshed = bool(refresh_due and ready and rows)
            if refreshed:
                previous = self.entry_symbols
                chosen = []
                seen = set()
                for row in rows:
                    symbol = str(row['symbol'])
                    if symbol in seen:
                        continue
                    seen.add(symbol)
                    selected = copy.deepcopy(row)
                    selected.update(symbol=symbol, rank=row.get('rank', len(chosen) + 1),
                                    selected_at=stamp, refresh_timestamp=stamp,
                                    reason=self.SELECTION_REASON,
                                    selection_reason=self.SELECTION_REASON)
                    selected.setdefault('current_price', selected.get('last'))
                    selected.setdefault('volume_24h', selected.get('volume24h'))
                    selected.setdefault('turnover_24h', selected.get('turnover24h'))
                    chosen.append(selected)
                    if len(chosen) == self.top:
                        break
                self.selected = chosen
                self.last_refresh_at = stamp
                # UTC hours are epoch-aligned; a delayed refresh skips missed
                # boundaries instead of opening a new one-hour restart cycle.
                self.next_refresh_at = (math.floor(stamp / self.INTERVAL_SECONDS) + 1) * self.INTERVAL_SECONDS
                for row in self.selected:
                    row['next_hourly_refresh'] = self.next_refresh_at
                current = self.entry_symbols
                for symbol in previous:
                    if symbol not in current:
                        events.append(dict(action='TOKEN_ROTATED', symbol=symbol,
                                           reason='hourly_entry_universe_refresh'))
                for symbol in current:
                    if symbol not in previous:
                        events.append(dict(action='TOKEN_SELECTED', symbol=symbol,
                                           reason=self.SELECTION_REASON))
                events.append(dict(action='UNIVERSE_REFRESHED', at=stamp,
                                   selected_symbols=list(current),
                                   next_refresh_at=self.next_refresh_at,
                                   reason='hourly_entry_universe_refresh'))
            self._track_positions(held)
            for event in events:
                if event.get('symbol'):
                    event['state'] = self.states[event['symbol']]
            result = copy.deepcopy(discovery)
            result.pop('ranked_rows', None)
            result['discovery_candidate_symbols'] = list(discovery.get('candidate_symbols') or [])
            result.update(self._snapshot(stamp))
            result.update(events=events, universe_refreshed=refreshed,
                          hourly_refresh_due=self.due(stamp),
                          observations_ready=ready,
                          selection_frozen=bool(discovery.get('selection_frozen') or (refresh_due and not refreshed)),
                          scan_seconds=1,
                          basis='hourly_entry_set_from_continuous_market_wide_discovery')
            return result

    def refresh(self, discovery, held=(), epoch=None):
        """Alias for update; calling this early never advances the hourly cycle."""
        return self.update(discovery, held=held, epoch=epoch)

    def _snapshot(self, stamp):
        symbols = list(self.entry_symbols)
        return dict(schema_version=1, at=stamp, top=self.top,
                    last_refresh_at=self.last_refresh_at,
                    next_refresh_at=self.next_refresh_at,
                    next_hourly_refresh=self.next_refresh_at,
                    selected=copy.deepcopy(self.selected), selected_symbols=symbols,
                    current_entry_set=symbols,
                    managed_symbols=list(self.managed_symbols),
                    retained_open_positions=list(self.managed_symbols),
                    tracking_symbols=self._symbols(symbols + self.managed_symbols),
                    # The market-wide ticker scanner remains continuous. The
                    # heavier public-trade/bootstrap pool follows entry + held.
                    candidate_symbols=symbols, states=dict(self.states))

    def snapshot(self, held=None, epoch=None):
        with self.lock:
            if held is not None:
                self._track_positions(held)
            return self._snapshot(self._epoch(epoch))

    def to_dict(self):
        """JSON-compatible state for the existing PostgreSQL checkpoint."""
        with self.lock:
            return self._snapshot(self.last_refresh_at)

    def restore(self, state):
        """Restore schedule and metadata without selecting or advancing a clock."""
        state = copy.deepcopy(state or {})
        with self.lock:
            self.last_refresh_at = state.get('last_refresh_at')
            self.next_refresh_at = state.get('next_refresh_at', state.get('next_hourly_refresh'))
            if self.last_refresh_at is not None:
                self.last_refresh_at = self._epoch(self.last_refresh_at)
                if self.next_refresh_at is None:
                    self.next_refresh_at = (math.floor(self.last_refresh_at / self.INTERVAL_SECONDS) + 1) * self.INTERVAL_SECONDS
            if self.next_refresh_at is not None:
                self.next_refresh_at = self._epoch(self.next_refresh_at)
            self.selected = [row for row in state.get('selected', [])
                             if isinstance(row, dict) and row.get('symbol')][:self.top]
            self.states = dict(state.get('states') or {})
            self._track_positions(state.get('managed_symbols', state.get('retained_open_positions', [])))
