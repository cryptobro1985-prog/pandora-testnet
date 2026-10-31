"""Run the complete active PAPER release suite; fail if integration DB is absent."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MODULES=tuple('tests.'+p.stem for p in sorted((ROOT/'tests').glob('test_*.py')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--list',action='store_true')
    args=parser.parse_args()
    if args.list:
        print('\n'.join(MODULES));return 0
    binding=os.getenv('PANDORA_TEST_DATABASE_URL_FILE')
    if not binding or not Path(binding).is_file():
        parser.error('PANDORA_TEST_DATABASE_URL_FILE must name an isolated test database URL file')
    if os.getenv('DATABASE_URL')!=Path(binding).read_text().strip():
        parser.error('DATABASE_URL must match the isolated test database binding')
    os.chdir(ROOT)
    suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report={'suite':'active_strategy1_release','modules':list(MODULES),'tests_run':result.testsRun,
            'failures':[str(case) for case,_ in result.failures],
            'errors':[str(case) for case,_ in result.errors],
            'skipped':[{'test':str(case),'reason':reason} for case,reason in result.skipped],
            'successful':result.wasSuccessful(),'live_exchange_verified':False,
            'note':'WebSocket integration uses a local server with synthetic Bybit-format frames.'}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    return int(not result.wasSuccessful() or bool(result.skipped))


if __name__=='__main__':raise SystemExit(main())
