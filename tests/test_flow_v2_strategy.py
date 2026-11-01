"""Synthetic acceptance evidence for the executed-flow state machine.

These verify causal behavior and persistence, not market profitability.
"""
from copy import deepcopy
import json

import math
import random
import unittest


def _both_sides(function):
    def run(self):
        for side in (1, -1):
            with self.subTest(side=side):
                function(self, side)
    return run

from pandora_flow_strategy import FlowConfig, FlowStrategy, _measure
from pandora_risk import RiskPolicy, signal_strength


class Tape:
    def __init__(self, side=1, received_shift=0, strategy=None):
        self.strategy = strategy or FlowStrategy()
        self.side = side
        self.received_shift = received_shift
        self.sequence = self.strategy.tokens.get('PUMP', {}).get('last_sequence', 0)
        self.position = None
        self.price = 100.
        self.decisions = []

    def trade(self, price, side, notional=100., dt=1., **extra):
        self.sequence += 1
        self.price = price
        event = dict(id='t'+str(self.sequence), sequence=self.sequence,
                     exchange_epoch=1000+self.sequence*dt,
                     received_epoch=1000+self.sequence*dt+self.received_shift,
                     price=price, notional=notional, aggressor_side=side)
        event.update(extra)
        result = self.strategy.ingest('PUMP', event, position=self.position)
        self.decisions.append(result)
        return result

    def trend(self, count, direction=None, step=.2, notional=100.):
        direction = direction or self.side
        return [self.trade(self.price+direction*step, direction, notional) for _ in range(count)]

    def open(self, side=None):
        side = side or self.side
        self.position = dict(side=side, entry=self.price)
        self.strategy.on_open('PUMP', side, self.price)

    def close(self):
        self.strategy.on_close('PUMP', self.position['side'], self.price)
        self.position = None

    def established(self):
        self.trend(10)
        self.open()
        self.trend(5)
        return self

    def micro_pullback_and_resume(self):
        result = self.trend(3, -self.side, step=.015)
        result += self.trend(4, self.side, step=.1)
        return result


class FlowV2StrategyTests(unittest.TestCase):
    @_both_sides
    def test_acceptance_2_continuing_70_30_pump_uses_executed_direction(self, side):
        tape = Tape(side)
        results = []
        for index in range(10):
            results.append(tape.trade(100+side*index*.2, -side if index in (2, 5, 8) else side))
        assert results[-1]['action'] == 'OPEN'
        assert results[-1]['side'] == side
        assert results[-1]['flow']['buy_notional' if side == 1 else 'sell_notional'] == 700
        assert all(r['side'] != -side for r in results if r['action'] == 'OPEN')
        tape.open()
        assert tape.trend(3)[-1]['action'] == 'HOLD'


    @_both_sides
    def test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold(self, side):
        tape = Tape(side).established()
        results = tape.micro_pullback_and_resume()
        assert all(r['action'] == 'HOLD' for r in results)
        assert tape.strategy.tokens['PUMP']['pressure_state']['noise'] > 0
        assert tape.strategy.tokens['PUMP']['actual_side'] == side


    @_both_sides
    def test_acceptance_4_6_exhaustion_closes_then_requires_new_executions(self, side):
        tape = Tape(side).established()
        tape.micro_pullback_and_resume()
        # Aggressive volume remains high while price stops responding.
        stagnant = [tape.trade(tape.price, side, 120) for _ in range(7)]
        prefix = 'buy' if side == 1 else 'sell'
        assert stagnant[-1]['flow'][prefix+'_absorbed']
        assert stagnant[-1]['flow_regime'] == ('BUY_WEAKENING' if side == 1 else 'SELL_WEAKENING')
        closes = []
        for _ in range(30):
            result = tape.trend(1, -side, .25, 180)[-1]
            if result['action'] == 'CLOSE':
                closes.append(result)
                break
        assert closes, 'real sustained takeover must close without a completed horizon'
        assert tape.strategy.tokens['PUMP']['actual_side'] == side, 'recommendation is not an execution'
        tape.close()
        closed_sequence = tape.sequence
        first = tape.trend(1, -side, .25, 180)[-1]
        second = tape.trend(1, -side, .25, 180)[-1]
        third = tape.trend(1, -side, .25, 180)[-1]
        assert first['action'] == second['action'] == 'WAIT'
        assert third['action'] == 'OPEN' and third['side'] == -side
        assert third['flow_regime'] == ('SELL_CONTROL' if side == 1 else 'BUY_CONTROL')
        assert tape.strategy.tokens['PUMP']['close_ack']['closed_event_sequence'] == closed_sequence
        assert tape.strategy.tokens['PUMP']['actual_side'] == 0


    def test_acceptance_7_receive_wall_clock_changes_do_not_change_decisions(self):
        tapes = [Tape(received_shift=shift) for shift in (0, 900_000, -900_000)]
        for tape in tapes:
            tape.established()
            tape.micro_pullback_and_resume()
            tape.trend(20, -1, .25, 180)
        signatures = [[(d['action'], d['side'], d['flow_regime'], d['flow']['dominance_persistence_events'])
                       for d in tape.decisions] for tape in tapes]
        assert signatures[0] == signatures[1] == signatures[2]


    def test_acceptance_8_repeated_polling_cannot_increase_any_proof(self):
        tape = Tape().established()
        tape.trend(2, -1, .3, 180)
        before = tape.strategy.to_dict()
        for _ in range(100):
            result = tape.strategy.evaluate('PUMP', position=tape.position)
            assert not result['new_event']
        assert tape.strategy.to_dict() == before
        duplicate = deepcopy(tape.strategy.tokens['PUMP']['events'][-1])
        duplicate['aggressor_side'] = duplicate.pop('side')
        for _ in range(100):
            assert not tape.strategy.ingest('PUMP', duplicate, position=tape.position)['new_event']
        after = tape.strategy.tokens['PUMP']
        assert after['event_count'] == before['tokens']['PUMP']['event_count']
        assert after['dominance_persistence_events'] == before['tokens']['PUMP']['dominance_persistence_events']
        assert after['pressure_state'] == before['tokens']['PUMP']['pressure_state']


    @_both_sides
    def test_acceptance_9_costs_prevent_churn_with_even_strong_counter_volume(self, side):
        tape = Tape(side).established()
        before = tape.price
        results = [tape.trade(before-side*.0005*(index+1), -side, 10_000)
                   for index in range(40)]
        assert all(r['action'] == 'HOLD' for r in results)
        assert all(r['flow']['sustained_control_side'] == -side for r in results[-5:])
        assert abs(tape.price-before)/before < 2*(RiskPolicy().fee+RiskPolicy().slippage)


    @_both_sides
    def test_acceptance_14_15_absorbed_volume_never_confirms_control(self, side):
        tape = Tape(side)
        results = [tape.trade(100., side, 10_000) for _ in range(20)]
        assert all(d['action'] == 'WAIT' for d in results)
        assert results[-1]['flow_regime'] == ('BUY_WEAKENING' if side == 1 else 'SELL_WEAKENING')
        assert results[-1]['flow']['buy_absorbed' if side == 1 else 'sell_absorbed']
        assert results[-1]['flow']['sustained_control_side'] == 0


    def test_acceptance_16_stale_state_blocks_entries_reversal_but_is_not_an_exit(self):
        tape = Tape().established()
        decision = tape.strategy.mark_data_uncertain('PUMP', position=tape.position)
        assert decision['action'] == 'DATA_UNCERTAIN'
        assert not decision['flow']['trade_data_fresh']
        assert tape.strategy.tokens['PUMP']['actual_side'] == 1
        before = tape.strategy.to_dict()
        for _ in range(100):
            assert tape.strategy.evaluate('PUMP', position=tape.position)['action'] == 'DATA_UNCERTAIN'
        assert tape.strategy.to_dict() == before
        assert tape.strategy.data_loss_protection('PUMP', tape.price, position=tape.position,
                                                 mark_fresh=True)['action'] == 'DATA_UNCERTAIN'
        assert tape.strategy.data_loss_protection('PUMP', tape.price-2, position=tape.position,
                                                 mark_fresh=False)['action'] == 'DATA_UNCERTAIN'
        protected = tape.strategy.data_loss_protection('PUMP', tape.price-2, position=tape.position, mark_fresh=True)
        assert protected['action'] == 'CLOSE' and protected['side'] == 1
        assert tape.strategy.tokens['PUMP']['actual_side'] == 1
        restored = tape.trend(1)[-1]
        assert restored['flow']['trade_data_fresh'] and restored['action'] == 'HOLD'
        flat = Tape()
        flat.trend(3)
        assert flat.strategy.mark_data_uncertain('PUMP')['action'] == 'DATA_UNCERTAIN'


    def test_restart_restores_every_execution_proof_and_close_ack(self):
        tape = Tape().established()
        tape.micro_pullback_and_resume()
        for _ in range(30):
            if tape.trend(1, -1, .3, 200)[-1]['action'] == 'CLOSE':
                break
        tape.close()
        tape.trend(2, -1, .3, 200)
        state = json.loads(json.dumps(tape.strategy.to_dict()))
        restored = FlowStrategy(state=state)
        assert restored.to_dict() == state
        other = Tape(strategy=restored)
        other.price = tape.price
        expected = tape.trend(1, -1, .3, 200)[-1]
        actual = other.trend(1, -1, .3, 200)[-1]
        assert actual == expected
        assert actual['action'] == 'OPEN'


    def test_reentry_requires_real_counter_cycle_and_has_no_count_limit(self):
        tape = Tape().established()
        tape.micro_pullback_and_resume()
        for _ in range(30):
            if tape.trend(1, -1, .3, 200)[-1]['action'] == 'CLOSE':
                break
        tape.close()
        # A real pullback preceded the close; new buying proves resumption.
        result = tape.trend(3, 1, .3, 200)[-1]
        assert result['action'] == 'REENTRY' and result['side'] == 1
        tape.strategy.tokens['PUMP']['reentry_count'] = 1000
        tape.open()
        assert tape.strategy.tokens['PUMP']['reentry_count'] == 1001
        tape.strategy.on_open('PUMP', 1, tape.price)
        assert tape.strategy.tokens['PUMP']['reentry_count'] == 1001


    def test_one_print_no_matter_how_large_cannot_supply_control(self):
        tape = Tape()
        tape.trade(100., -1)
        result = tape.trade(110., 1, 1_000_000)
        assert result['action'] == 'WAIT'
        assert not result['flow']['sustained_control_side']


    def test_bare_majority_is_not_control(self):
        tape = Tape()
        for index in range(10):
            result = tape.trade(100+index*.2, 1 if index%2 else -1,
                                51 if index%2 else 49)
        assert result['action'] == 'WAIT'
        assert result['flow']['sustained_control_side'] == 0


    def test_same_exchange_timestamp_executions_are_independent_by_id_and_sequence(self):
        tape = Tape()
        for price in (100, 100.2, 100.4):
            result = tape.trade(price, 1, exchange_epoch=1000)
        assert result['action'] == 'OPEN'
        assert result['flow']['windows']['15']['observed_seconds'] == 0


    def test_sequence_identity_and_malformed_data_fail_without_extra_confirmation(self):
        tape = Tape()
        tape.trend(2)
        token = tape.strategy.tokens['PUMP']
        before_count = token['event_count']
        result = tape.trade(101, 1, id='t2')
        assert not result['new_event']
        assert token['event_count'] == before_count
        result = tape.trade(101, 1, exchange_epoch=999)
        assert result['action'] == 'DATA_UNCERTAIN'
        result = tape.trade(float('nan'), 1)
        assert result['action'] == 'DATA_UNCERTAIN'
        assert not result['flow']['sequence_valid']


    def test_entry_set_rotation_cannot_close_actual_managed_position(self):
        tape = Tape().established()
        result = tape.strategy.evaluate('PUMP', position=tape.position, selected_entry=False)
        assert result['action'] == 'HOLD'
        flat = Tape()
        flat.trend(3)
        assert flat.strategy.evaluate('PUMP', selected_entry=False)['action'] == 'WAIT'


    def test_flow_geometry_preserves_risk_sizing_structure_contribution(self):
        tape = Tape()
        result = tape.trend(3)[-1]
        assert result['analysis']['source'] == 'executed_flow_price_geometry'
        assert result['analysis']['entry_side'] == 1
        assert result['analysis']['anchor_confirmed']
        stripped = dict(result['analysis'], anchor_confirmed=False)
        assert math.isclose(signal_strength(1, result['analysis'], result['flow']),
                            signal_strength(1, stripped, result['flow'])+.25)
        assert result['analysis']['pivot_price'] == min(r['price'] for r in tape.strategy.tokens['PUMP']['events'])


    def test_observation_gap_invalidates_tape_but_preserves_position_and_geometry(self):
        tape = Tape().established()
        tape.micro_pullback_and_resume()
        before = tape.strategy.get_state('PUMP')
        after = tape.strategy.reset_observation('PUMP', 'transport gap', sequence=tape.sequence)
        assert after['events'] == []
        assert after['actual_side'] == before['actual_side'] == 1
        assert after['pressure_state'] == before['pressure_state']
        assert after['open_ack'] == before['open_ack']
        assert tape.strategy.evaluate('PUMP', position=tape.position)['action'] == 'DATA_UNCERTAIN'
        assert tape.trend(1)[-1]['action'] == 'HOLD'
        assert tape.strategy.tokens['PUMP']['dominance_persistence_events'] == 1


    def test_bounded_tape_and_named_configuration(self):
        strategy = FlowStrategy(config=FlowConfig(max_history_events=6))
        tape = Tape(strategy=strategy)
        tape.trend(20)
        assert len(strategy.tokens['PUMP']['events']) == 6
        with unittest.TestCase().assertRaises(ValueError):
            FlowConfig(min_control_events=2)
        with unittest.TestCase().assertRaises(ValueError):
            FlowStrategy(state={'experiment_id': 'old'})


    def test_incremental_measurements_match_direct_tape_and_restart_with_expiration(self):
        randomizer = random.Random(7)
        strategy = FlowStrategy(config=FlowConfig(max_history_events=35))
        epoch = 1000.
        price = 100.
        for sequence in range(1, 180):
            epoch += randomizer.choice((0., .25, .5, 1., 5., 15.))
            price += randomizer.choice((-.2, -.01, 0., .01, .2))
            event = dict(id=str(sequence), sequence=sequence, exchange_epoch=epoch,
                         received_epoch=epoch+10_000, price=price,
                         notional=randomizer.choice((.01, .1, 50., 100., 1000.)),
                         aggressor_side=randomizer.choice((1, -1)))
            actual = strategy.ingest('PUMP', event)
            events = strategy.tokens['PUMP']['events']
            for horizon, metric in actual['flow']['windows'].items():
                seconds = int(horizon)
                sample = [r for r in events if epoch-r['exchange_epoch'] <= seconds]
                previous = [r for r in events if seconds < epoch-r['exchange_epoch'] <= 2*seconds]
                direct = _measure(sample, epoch, seconds, previous)
                for key, expected in direct.items():
                    observed = metric[key]
                    if isinstance(expected, float):
                        assert math.isclose(expected, observed, rel_tol=1e-10, abs_tol=1e-12), (sequence, horizon, key, expected, observed)
                    else:
                        assert observed == expected, (sequence, horizon, key)
            if sequence % 17 == 0:
                restored = FlowStrategy(state=json.loads(json.dumps(strategy.to_dict())))
                expected = strategy.evaluate('PUMP')
                actual = restored.evaluate('PUMP')
                assert actual == expected


    @_both_sides
    def test_old_flat_prints_plus_one_price_spike_are_not_continuation(self, side):
        tape = Tape(side)
        for _ in range(5):
            tape.trade(100., side)
        result = tape.trade(100+side*10, side, 10_000)
        assert result['action'] == 'WAIT'
        assert result['flow']['windows']['5']['buy_response_event_count' if side == 1 else 'sell_response_event_count'] == 1
        assert tape.trade(100+side*10.2, side, 10_000)['action'] == 'OPEN'

    def test_pending_close_survives_neutral_then_fresh_own_control_invalidates(self):
        tape = Tape().established()
        tape.micro_pullback_and_resume()
        for _ in range(30):
            if tape.trend(1, -1, .3, 200)[-1]['action'] == 'CLOSE':
                break
        assert tape.decisions[-1]['action'] == 'CLOSE'
        close_price = tape.price
        assert tape.trade(close_price, 1, .001)['action'] == 'CLOSE'
        results = tape.trend(3, 1, .05, 10_000)
        assert results[-1]['action'] == 'HOLD'
        assert tape.price < tape.strategy.tokens['PUMP']['pressure_state']['best']
        assert tape.strategy.tokens['PUMP']['actual_side'] == 1
