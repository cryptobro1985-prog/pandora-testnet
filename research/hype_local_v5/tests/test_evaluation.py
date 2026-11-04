"""Research-validation tests; synthetic prices are never market evidence."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from research.hype_local_v5.labels import completed_hours, structural_labels, HOUR
from research.hype_local_v5.evaluation import evaluate, wilson
from research.hype_local_v5.pipeline import coverage, check_coverage, evaluate_oos, digest, write_json


def hourly():
    rows=[]
    for i,p in enumerate([10,11,12,13,14,15,20,14,13,12,11,5,10,11,12]):
        rows.append(dict(start_ms=i*HOUR,ts_ms=(i+1)*HOUR,interval_ms=HOUR,
            open=p,high=p+.5,low=p-.5,close=p))
    return rows


class LabelTests(unittest.TestCase):
    def test_requires_full_hour_and_no_gap(self):
        rows=[dict(start_ms=0,ts_ms=60000,open=10,high=11,low=9,close=10)]
        self.assertEqual(completed_hours(rows),[])
        rows=hourly();rows[4]['gap']=True
        self.assertEqual(len(completed_hours(rows)),len(rows)-1)

    def test_delayed_availability_is_not_extra_market_duration(self):
        rows=hourly()
        for row in rows:
            row['bar_end_ms']=row['ts_ms']
            row['ts_ms']+=60000
        self.assertEqual(len(completed_hours(rows)),len(rows))
        self.assertLessEqual(coverage(rows,0,15*HOUR)['covered_fraction'],1)
        self.assertEqual(structural_labels(rows)[0][0]['label_available_ms'],9*HOUR+60000)

    def test_label_future_is_explicit_and_pivots_alternate(self):
        labels,_=structural_labels(hourly())
        self.assertEqual([x['side'] for x in labels],['HIGH','LOW'])
        self.assertEqual(labels[0]['label_available_ms'],9*HOUR)
        self.assertEqual(labels[0]['extreme_price'],20.5)

    def test_missing_hour_does_not_become_contiguous_by_index(self):
        rows=hourly(); del rows[2]
        labels,excluded=structural_labels(rows)
        self.assertFalse(any(x['hour_ms']==6*HOUR for x in labels))
        self.assertTrue(any(x['reason']=='missing_hour' for x in excluded))

    def test_ambiguous_same_hour_pivots_excluded(self):
        rows=hourly();rows[6]['low']=1
        _,excluded=structural_labels(rows)
        self.assertIn('ambiguous_high_low_order',[x['reason'] for x in excluded])


class EvaluationTests(unittest.TestCase):
    def event(self,**kwargs):
        value=dict(candidate_id=1,episode_id=1,side='HIGH',candidate_ts_ms=7*HOUR,
            confirmation_ts_ms=7*HOUR+60000,confirmation_price=20,
            extreme_price=20.5,extreme_interval_start_ms=6*HOUR,
            extreme_interval_end_ms=7*HOUR,features={'retracement_fraction':.1})
        value.update(kwargs);return value

    def test_first_acceptance_not_best_later_candidate(self):
        rows=hourly();labels,_=structural_labels(rows)
        wrong=self.event(extreme_price=19)
        engine=SimpleNamespace(confirmed=[wrong],candidates=[wrong])
        result=evaluate(engine,rows,labels,0,13*HOUR)
        self.assertEqual(result['metrics']['true'],0)
        self.assertEqual(result['metrics']['missed'],1)
        self.assertEqual(result['metrics']['first_accepted_precision'],0)

    def test_one_to_one_match_and_interval_delay(self):
        event=self.event(); other=self.event(candidate_id=2,episode_id=2)
        engine=SimpleNamespace(confirmed=[event,other],candidates=[event,other])
        labels,_=structural_labels(hourly())
        result=evaluate(engine,hourly(),labels,0,13*HOUR)
        self.assertEqual(result['metrics']['true'],1)
        self.assertEqual(result['metrics']['false'],0)
        self.assertEqual(result['metrics']['engine_episode_accepted'],2)
        self.assertEqual(result['accepted'][0]['delay_min_lower'],1)
        self.assertEqual(result['accepted'][0]['delay_min_upper'],61)

    def test_later_true_signal_cannot_erase_first_false_in_reference_swing(self):
        first=self.event(extreme_price=19,confirmation_ts_ms=5*HOUR)
        later=self.event(candidate_id=2,episode_id=3)
        engine=SimpleNamespace(confirmed=[first,later],candidates=[first,later])
        labels,_=structural_labels(hourly())
        result=evaluate(engine,hourly(),labels,0,13*HOUR)
        self.assertEqual(result['metrics']['first_accepted_precision'],0)
        self.assertEqual(result['metrics']['engine_episode_precision'],.5)
        self.assertEqual(result['metrics']['missed'],1)

    def test_zero_decisions_not_perfect_precision(self):
        engine=SimpleNamespace(confirmed=[],candidates=[])
        result=evaluate(engine,hourly(),[],0,13*HOUR)
        self.assertIsNone(result['metrics']['first_accepted_precision'])
        self.assertEqual(wilson(0,0),[None,None])
        self.assertLess(wilson(10,10)[0],1)

    def test_left_boundary_candidate_is_censored(self):
        event=self.event()
        engine=SimpleNamespace(confirmed=[event],candidates=[event])
        result=evaluate(engine,hourly(),[],7*HOUR,13*HOUR)
        self.assertEqual(result['metrics']['accepted'],0)
        self.assertEqual(result['metrics']['censored_accepted'],1)

    def test_reference_unknown_is_censored(self):
        event=self.event()
        engine=SimpleNamespace(confirmed=[event],candidates=[event])
        result=evaluate(engine,hourly(),[],0,13*HOUR,[{'hour_ms':6*HOUR,'reason':'ambiguous_high_low_order'}])
        self.assertEqual(result['metrics']['accepted'],0)
        self.assertEqual(result['censored'][0]['evaluation_status'],'reference_unknown_censored')

    def test_censored_first_signal_cannot_be_replaced_by_later_success(self):
        first=self.event(extreme_interval_start_ms=2*HOUR,extreme_interval_end_ms=3*HOUR,
                         confirmation_ts_ms=5*HOUR)
        later=self.event(candidate_id=2,episode_id=3)
        engine=SimpleNamespace(confirmed=[first,later],candidates=[first,later])
        labels,_=structural_labels(hourly())
        result=evaluate(engine,hourly(),labels,4*HOUR,13*HOUR)
        self.assertEqual(result['metrics']['reference_censored'],1)
        self.assertEqual(result['metrics']['accepted'],0)

    def test_exact_extreme_timestamp_matches_its_label_interval(self):
        event=self.event(extreme_interval_start_ms=6*HOUR+1000,extreme_interval_end_ms=6*HOUR+1000)
        engine=SimpleNamespace(confirmed=[event],candidates=[event])
        labels,_=structural_labels(hourly())
        self.assertEqual(evaluate(engine,hourly(),labels,0,13*HOUR)['metrics']['true'],1)

    def test_future_price_cannot_change_emitted_signal(self):
        event=self.event();before=copy.deepcopy(event)
        engine=SimpleNamespace(confirmed=[event],candidates=[event])
        evaluate(engine,hourly(),[],0,13*HOUR)
        self.assertEqual(event,before)


class PipelineTests(unittest.TestCase):
    def test_insufficient_history_refuses_market_evaluation(self):
        with self.assertRaisesRegex(ValueError,'insufficient'):
            check_coverage(hourly(),0,30*24*HOUR)

    def test_manifest_tamper_refuses_oos_before_loading(self):
        with TemporaryDirectory() as temp:
            p=Path(temp)/'selection.json'
            value={'status':'selected_for_oos','selected_config':{}}
            value['selection_sha256']=digest(value)
            value['selected_config']={'accept_score':0.01}
            write_json(p,value)
            with self.assertRaisesRegex(ValueError,'changed'):
                evaluate_oos([],Path(temp)/'out',p,[])
            self.assertFalse((Path(temp)/'out'/'OOS_CONSUMED.json').exists())


if __name__=='__main__':unittest.main()
