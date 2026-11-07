"""End-to-end on EXPLICIT synthetic inputs; not a trading backtest."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research.hype_local_v5 import pipeline

HOUR=3_600_000


class PipelineIntegrationTests(unittest.TestCase):
    def test_discovery_sealed_oos_and_output_relocation_cannot_repeat(self):
        rows=[]
        previous=100.
        for minute in range(48*60):
            price=100+5*math.sin(2*math.pi*minute/600)
            rising=price>previous
            rows.append(dict(start_ms=minute*60000,ts_ms=(minute+1)*60000,
                bar_end_ms=(minute+1)*60000,interval_ms=60000,
                open=previous,close=price,high=max(previous,price)+.001,
                low=min(previous,price)-.001,buy_notional=90. if rising else 10.,
                sell_notional=10. if rising else 90.))
            previous=price
        manifest=[{'source':'EXPLICIT_SYNTHETIC_UNIT_TEST_ONLY'}]
        with TemporaryDirectory() as temp, patch.multiple(pipeline,
                WARMUP=0,DISCOVERY=6*HOUR,OOS=36*HOUR,END=48*HOUR,
                FOLDS=[(12*HOUR,24*HOUR),(24*HOUR,36*HOUR)]):
            root=Path(temp)
            selection=pipeline.discover(rows,root/'discovery',manifest)
            self.assertEqual(selection['status'],'selected_for_oos')
            result=pipeline.evaluate_oos(rows,root/'final',root/'discovery'/'selection.json',manifest)
            self.assertIn('first_accepted_precision',result)
            self.assertTrue((root/'final'/'oos'/'first_accepted_candidates.csv').is_file())
            self.assertTrue((root/'final'/'oos'/'confidence_trajectories.json').is_file())
            with self.assertRaises(FileExistsError):
                pipeline.evaluate_oos(rows,root/'different-output',root/'discovery'/'selection.json',manifest)
            self.assertEqual(len(list((root/'discovery').glob('OOS_CONSUMED_*.json'))),1)


if __name__=='__main__':unittest.main()
