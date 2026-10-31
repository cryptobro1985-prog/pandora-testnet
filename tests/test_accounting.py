import contextlib
import unittest

from accounting import paper_pnl
from engine_store import EngineStore


class AccountingTests(unittest.TestCase):
    def test_long_charges_actual_entry_and_exit_notionals(self):
        # Entry quantity10; entry$1000, exit$1100, fees$2.10.
        self.assertAlmostEqual(paper_pnl(1000, 100, 110, 1, .001), 97.9)

    def test_short_charges_actual_entry_and_exit_notionals(self):
        # The winning short closes with smaller USD notional, not a flat$2fee.
        self.assertAlmostEqual(paper_pnl(1000, 100, 90, -1, .001), 98.1)

    def test_losing_long_and_short_are_symmetric_before_fees(self):
        self.assertAlmostEqual(paper_pnl(1000, 100, 90, 1, .001), -101.9)
        self.assertAlmostEqual(paper_pnl(1000, 100, 110, -1, .001), -102.1)

    def test_unchanged_price_loses_exactly_round_trip_fees(self):
        for side in (-1, 1):
            self.assertAlmostEqual(paper_pnl(1000, 100, 100, side, .00045), -.9)

    def test_quantity_and_zero_fee_cases(self):
        self.assertEqual(paper_pnl(0, 100, 110, 1), 0)
        self.assertEqual(paper_pnl(1000, 100, 110, 1, 0), 100)

    def test_invalid_inputs_and_overflow_are_rejected(self):
        for values in ((-1,100,110,1,.001), (1,0,110,1,.001), (1,100,0,1,.001),
                       (1,100,110,0,.001), (1,100,110,1,-.001),
                       (1,float("nan"),110,1,.001), (1,100,float("inf"),1,.001),
                       (float("inf"),100,110,1,.001), (1,100,110,1,float("nan")),
                       (1e308,1e-308,1e308,1,.001), (None,100,110,1,.001)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    paper_pnl(*values)


class TransactionTimeoutTests(unittest.TestCase):
    class Connection:
        def __init__(self):
            self.statements = []
            self.in_transaction = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @contextlib.contextmanager
        def transaction(self):
            self.in_transaction = True
            try:
                yield self
            finally:
                self.in_transaction = False

        def execute(self, sql, args=None):
            self.statements.append((sql, self.in_transaction))
            return self

        def fetchone(self):
            return {"owner": "fixture"}

    def test_claim_sets_local_timeouts_inside_transaction_before_lease_write(self):
        conn = self.Connection()
        store = EngineStore(lambda: conn)
        self.assertTrue(store.claim())
        self.assertEqual(conn.statements[0], ("SET LOCAL lock_timeout = '2s'", True))
        self.assertEqual(conn.statements[1], ("SET LOCAL statement_timeout = '5s'", True))
        self.assertIn("INSERT INTO engine_lease", conn.statements[2][0])
        self.assertTrue(conn.statements[2][1])

    def test_fence_applies_timeouts_before_row_lock(self):
        conn = self.Connection()
        store = EngineStore(lambda: conn)
        with conn.transaction():
            store.fence(conn)
        self.assertEqual(conn.statements[0][0], "SET LOCAL lock_timeout = '2s'")
        self.assertEqual(conn.statements[1][0], "SET LOCAL statement_timeout = '5s'")
        self.assertIn("FOR SHARE", conn.statements[2][0])


if __name__ == "__main__":
    unittest.main()
