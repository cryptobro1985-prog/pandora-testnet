import copy
import json
import unittest
from research.hype_local_v5.engine import Config, Engine
from research.hype_local_v5.features import FeatureBuilder


def bar(i, price, previous=None, buy=1.0, sell=9.0):
    previous = price if previous is None else previous
    return dict(start_ms=i*60_000, ts_ms=(i+1)*60_000, interval_ms=60_000,
                open=previous, high=max(previous, price)+.001,
                low=min(previous, price)-.001, close=price,
                buy_notional=buy, sell_notional=sell)


def warmup(engine):
    previous = 100.0
    for i in range(360):
        price = 100 + .01*(i+1)
        engine.update(bar(i, price, previous, buy=9., sell=1.))
        previous = price
    return previous


class CausalEngineTests(unittest.TestCase):
    def test_warmup_requires_six_complete_observed_hours(self):
        e = Engine(Config(model_family="A"))
        for i in range(359):
            e.update(bar(i, 100+i*.01))
        self.assertEqual(e.state, "WARMUP")
        self.assertIsNone(e.anchor)
        e.update(bar(359, 103.59))
        self.assertEqual(e.state, "ACTIVE_SWING")
        self.assertEqual(e.anchor["source"], "BOOTSTRAP_SEED")
        self.assertEqual(e.confirmed, [])

    def test_new_extreme_invalidates_candidate_before_any_confirmation(self):
        e = Engine(Config(model_family="A", accept_score=.99))
        price = warmup(e)
        e.update(bar(360, price-.1, price))
        self.assertIsNotNone(e.candidate)
        candidate_id = e.candidate["candidate_id"]
        # Both bounds crossed within a bar; their order cannot be invented.
        r = bar(361, price-1, price-.1)
        r["high"] = price+1
        events = e.update(r)
        self.assertTrue(any(x["event"] == "CANDIDATE_INVALIDATED" for x in events))
        self.assertFalse(any(x["event"] == "CONFIRMED_LOCAL" for x in events))
        self.assertEqual(e.candidates[candidate_id-1]["status"], "INVALIDATED")
        self.assertEqual(e.running["extreme_price"], price+1)
        self.assertIsNone(e.running["extreme_ts_ms"])

    def test_prefix_invariance_and_old_event_snapshots_immutable(self):
        config = Config(model_family="A", accept_score=.5)
        a, b = Engine(config), Engine(config)
        for e in (a, b):
            warmup(e)
            for i in range(360, 368):
                e.update(bar(i, 103.5-(i-360)*.1, 103.6-(i-360)*.1))
        self.assertEqual(a.events, b.events)
        saved = json.dumps(a.events, sort_keys=True)
        for i in range(368, 380):
            a.update(bar(i, 110+(i-368)*.1))
        self.assertEqual(json.dumps(a.events[:len(b.events)], sort_keys=True), saved)
        self.assertEqual(a.events[:len(b.events)], b.events)

    def test_missing_flow_abstains_but_price_model_can_run(self):
        e = Engine(Config(model_family="B", accept_score=.2))
        price = warmup(e)
        for i in range(360, 366):
            r = bar(i, price-.2*(i-359))
            r["buy_notional"] = r["sell_notional"] = None
            e.update(r)
        self.assertEqual(e.confirmed, [])
        self.assertEqual(e.candidate["status"], "WAIT_MISSING_DATA")
        self.assertIn("flow_imbalance_60s", e.candidate["missing_features"])

    def test_optional_families_never_impute_missing_microstructure(self):
        for family, missing in (("C", "oi_delta_300s"), ("D", "long_liq_notional_60s"),
                                ("E", "ask_replenishment_ratio_60s"), ("F", "ask_replenishment_ratio_60s")):
            e = Engine(Config(model_family=family, accept_score=.2))
            price = warmup(e)
            e.update(bar(360, price-.2, price))
            self.assertEqual(e.confirmed, [])
            self.assertIn(missing, e.candidate["missing_features"])

    def test_anchor_extension_does_not_emit_same_side_local(self):
        e = Engine(Config(model_family="A", accept_score=.99))
        warmup(e)
        old_anchor = e.anchor["price"]
        events = e.update(bar(360, old_anchor-1))
        self.assertEqual(e.seek_side, "HIGH")
        self.assertLess(e.anchor["price"], old_anchor)
        self.assertEqual(e.confirmed, [])
        self.assertEqual(len(e.episodes[0]["anchor_extensions"]), 1)
        self.assertTrue(any(x["event"] == "ANCHOR_EXTENSION" for x in events))

    def test_confirmed_locals_alternate_and_preserve_entry_price(self):
        e = Engine(Config(model_family="A", maturity_atr=.1, accept_score=.4, min_survival_seconds=60))
        p = warmup(e)
        for i in range(360, 370):
            q = 103.6-(i-359)*.2
            e.update(bar(i,q,p)); p=q
        for i in range(370, 385):
            q = p+.2
            e.update(bar(i,q,p));p=q
        for i in range(385, 400):
            q = p-.2
            e.update(bar(i,q,p));p=q
        self.assertGreaterEqual(len(e.confirmed), 2)
        sides = [x["side"] for x in e.confirmed]
        self.assertTrue(all(a != b for a,b in zip(sides,sides[1:])))
        for local in e.confirmed:
            self.assertGreater(local["confirmation_ts_ms"], local["extreme_available_ms"])
            self.assertNotEqual(local["confirmation_price"], local["extreme_price"])
            episode = e.episodes[local["episode_id"]-1]
            self.assertEqual(episode["first_accepted_candidate_id"],local["candidate_id"])
            self.assertFalse(local["score_is_probability"])

    def test_gap_abandons_unobserved_swing_and_rewarms(self):
        e = Engine(Config(model_family="A", accept_score=.99))
        p = warmup(e)
        e.update(bar(360,p-.1,p))
        self.assertIsNotNone(e.candidate)
        events = e.update(bar(363,p-.3))
        self.assertEqual(e.state,"WARMUP")
        self.assertIsNone(e.anchor)
        self.assertEqual(e.candidates[0]["invalidation_reason"],"DATA_GAP")
        self.assertTrue(any(x.get("reason")=="DATA_GAP_REWARMUP" for x in events))

    def test_reordered_or_invalid_prices_rejected(self):
        e=Engine()
        e.update(bar(0,100))
        with self.assertRaises(ValueError):e.update(bar(0,100))
        with self.assertRaises(ValueError):e.update(bar(1,float("nan")))
        with self.assertRaises(ValueError):Config(accept_score=0)
        with self.assertRaises(ValueError):Config(maturity_atr=float("nan"))
        with self.assertRaises(ValueError):Config(accept_score=float("nan"))
        with self.assertRaises(ValueError):Config(model_family="A", require_absorption=True)

    def test_delayed_bar_availability_does_not_create_physical_gaps(self):
        e=Engine(Config(model_family="A"))
        for i in range(360):
            r=bar(i,100+i*.01)
            r["bar_end_ms"]=r["ts_ms"]
            r["ts_ms"]+=5000
            e.update(r)
        self.assertIsNotNone(e.anchor)
        self.assertEqual(e.running["extreme_interval_end_ms"],360*60_000)
        self.assertEqual(e.running["extreme_available_ms"],360*60_000+5000)
        self.assertFalse(any(x.get("reason")=="DATA_GAP_REWARMUP" for x in e.events))

    def test_absorption_gate_does_not_invent_unobserved_stages(self):
        e=Engine(Config(model_family="B", accept_score=.2, require_absorption=True))
        p=warmup(e)
        for i in range(360,370):
            q=p-.2
            e.update(bar(i,q,p,buy=0,sell=10));p=q
        self.assertEqual(e.confirmed,[])
        stages={x["stage"] for x in e.candidate["stage_history"]}
        self.assertNotIn("CLIMAX",stages)
        self.assertNotIn("ABSORPTION",stages)
        self.assertNotIn("EARLY_CONTROL_TRANSFER",stages)

    def test_new_side_efficiency_uses_aggressive_notional_baseline(self):
        def components(efficiency):
            e=Engine(Config(model_family="B"))
            e.anchor={"side":"LOW"}
            e.running={"extreme_price":110.,"extreme_available_ms":0}
            e.candidate={"score":0.}
            f={"flow_imbalance_60s":-.8,"flow_imbalance_300s":-.5,
               "price_displacement_60s":-1.,"sell_efficiency_60s":efficiency,
               "sell_efficiency_300s":1.,"buy_efficiency_60s":0.,
               "buy_efficiency_300s":1.,"buy_notional_60s":0.,"buy_notional_300s":10.}
            return e._score(dict(ts_ms=60_000,close=109.),f,10.,1.,.1,60.)[1]
        strong,weak=components(2.),components(.5)
        self.assertGreater(strong["new_side_efficiency"],weak["new_side_efficiency"])
        self.assertEqual(strong["old_side_efficiency_decay"],0.)

    def test_absorption_stages_record_only_observed_feature_sources(self):
        e=Engine(Config(model_family="B", accept_score=.2, require_absorption=True))
        p=warmup(e)
        # Aggressive old-side activity spikes while price response per dollar
        # falls relative to its own five-minute baseline.
        e.update(bar(360,p+.005,p,buy=90.,sell=1.))
        e.update(bar(361,p+.004,p+.005,buy=90.,sell=1.))
        self.assertEqual(e.confirmed,[])
        e.update(bar(362,p-.1,p+.004,buy=1.,sell=10.))
        self.assertEqual(len(e.confirmed),1)
        history=e.confirmed[0]["stage_history"]
        stages={x["stage"] for x in history}
        self.assertTrue({"CLIMAX","ABSORPTION","EARLY_CONTROL_TRANSFER","CONFIRMED_LOCAL"}<=stages)
        self.assertTrue(all(x["source_ts_ms"]<=x["ts_ms"]<=e.confirmed[0]["confirmation_ts_ms"] for x in history))
        by_stage={x["stage"]:x["source_ts_ms"] for x in history}
        self.assertLess(by_stage["CLIMAX"],by_stage["ABSORPTION"])
        self.assertLess(by_stage["ABSORPTION"],by_stage["EARLY_CONTROL_TRANSFER"])

    def test_discovery_retention_flags_preserve_decisions_and_update_events(self):
        config=Config(model_family="A",maturity_atr=.1,accept_score=.4)
        full=Engine(config)
        lean=Engine(config,retain_trajectory=False,retain_events=False)
        for i in range(390):
            p=100+.01*i if i<360 else 103.6-.2*(i-359)
            row=bar(i,p)
            self.assertEqual(full.update(row),lean.update(row))
        self.assertEqual(full.confirmed,lean.confirmed)
        self.assertEqual(full.candidates,lean.candidates)
        self.assertEqual(lean.events,[])
        self.assertEqual(lean.trajectory,[])
        self.assertGreater(len(full.events),0)
        self.assertEqual(len(lean._history),0)

    def test_shared_causal_features_preserve_engine_prefix(self):
        full,shared=Engine(Config(model_family="A")),Engine(Config(model_family="A"))
        builder=FeatureBuilder()
        for i in range(390):
            row=bar(i,100+.01*i if i<360 else 103.6-.2*(i-359))
            snapshot=builder.update(row)
            saved=copy.deepcopy(snapshot)
            self.assertEqual(full.update(row),shared.update(row,observed_features=snapshot))
            self.assertEqual(snapshot,saved)
        self.assertEqual(full.candidates,shared.candidates)
        with self.assertRaises(ValueError):shared.update(bar(390,100))
        bad=Engine()
        with self.assertRaises(ValueError):bad.update(bar(0,100),observed_features={"ts_ms":0})


if __name__ == "__main__":
    unittest.main()
