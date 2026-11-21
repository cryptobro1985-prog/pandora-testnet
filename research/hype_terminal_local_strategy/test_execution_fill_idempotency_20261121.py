import unittest
from execution_fill_idempotency_20261121 import FillRiskJournal

class FillTests(unittest.TestCase):
    def test_duplicate_close(self):
        b=FillRiskJournal(100);self.assertTrue(b.accept('A',.5))
        b.fill('open1','A','open',.2,'2026-11-21T10:00Z',100)
        b.cancel_pending('A')
        self.assertTrue(b.fill('close1','A','close',.1,'2026-11-21T10:01Z',101))
        self.assertFalse(b.fill('close1','A','close',.1,'2026-11-21T10:01Z',101))
        self.assertAlmostEqual(b.committed(),.1)
    def test_conflict(self):
        b=FillRiskJournal(100);b.accept('A',.5);b.fill('f','A','open',.2,'t',100)
        with self.assertRaises(ValueError):b.fill('f','A','open',.3,'t',100)
        self.assertTrue(b.blocked)
    def test_overclose(self):
        b=FillRiskJournal(100);b.accept('A',.5);b.fill('f','A','open',.2,'t',100)
        with self.assertRaises(ValueError):b.fill('g','A','close',.3,'t2',101)
        self.assertAlmostEqual(b.committed(),.5)
    def test_mtm(self):
        b=FillRiskJournal(100);b.accept('A',.5);b.mark_equity(40)
        self.assertFalse(b.accept('B',.01))
    def test_cancel(self):
        b=FillRiskJournal(100);b.accept('A',.5)
        b.fill('f','A','open',.2,'t',100);b.cancel_pending('A')
        self.assertAlmostEqual(b.committed(),.2)

if __name__=='__main__':unittest.main()
