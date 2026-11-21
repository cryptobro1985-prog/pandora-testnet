from dataclasses import dataclass
from math import isfinite

"""Research-only supplemental liquidation clearance gate. NOT a Bybit liquidation model."""
@dataclass(frozen=True)
class State:
    side:str; entry:float; stop:float; liquidation:float; gap:float
    clearance:float; mark:float; mark_basis_buffer:float
    age_seconds:float; max_age_seconds:float
    authenticated:bool; isolated:bool; other_positions:int

def gate(s):
    vals=[s.entry,s.stop,s.liquidation,s.gap,s.clearance,s.mark,s.mark_basis_buffer,s.age_seconds,s.max_age_seconds]
    if not all(isfinite(x) for x in vals) or min(s.entry,s.stop,s.liquidation,s.mark,s.max_age_seconds)<=0 or min(s.gap,s.clearance,s.mark_basis_buffer,s.age_seconds)<0:
        return 'BLOCK_INVALID'
    if s.side not in ('LONG','SHORT') or not s.authenticated or s.age_seconds>s.max_age_seconds:
        return 'BLOCK_PROVENANCE'
    if not s.isolated or s.other_positions!=0:
        return 'BLOCK_ACCOUNT_UNMODELED'
    sign=1 if s.side=='LONG' else -1
    adverse=sign*(s.entry-s.stop)/s.entry
    liqdist=sign*(s.entry-s.liquidation)/s.entry
    mark_basis=abs(s.mark-s.entry)/s.entry
    if adverse<=0 or liqdist<=0: return 'BLOCK_GEOMETRY'
    if liqdist <= adverse+s.gap+s.clearance+mark_basis+s.mark_basis_buffer:
        return 'BLOCK_CLEARANCE'
    return 'PROVISIONAL_CLEARANCE_ONLY'

if __name__=='__main__':
    import unittest
    class T(unittest.TestCase):
        def c(self,side='LONG',**kw):
            d=dict(side=side,entry=100,stop=99 if side=='LONG' else 101,
                liquidation=96.99 if side=='LONG' else 103.01,gap=.02,
                clearance=.005,mark=100,mark_basis_buffer=.001,
                age_seconds=1,max_age_seconds=5,authenticated=True,
                isolated=True,other_positions=0)
            d.update(kw);return State(**d)
        def test_near_liq_long(self):self.assertEqual(gate(self.c()),'BLOCK_CLEARANCE')
        def test_near_liq_short(self):self.assertEqual(gate(self.c('SHORT')),'BLOCK_CLEARANCE')
        def test_distant_long(self):self.assertEqual(gate(self.c(liquidation=95)),'PROVISIONAL_CLEARANCE_ONLY')
        def test_distant_short(self):self.assertEqual(gate(self.c('SHORT',liquidation=105)),'PROVISIONAL_CLEARANCE_ONLY')
        def test_stale(self):self.assertEqual(gate(self.c(age_seconds=6)),'BLOCK_PROVENANCE')
        def test_missing_auth(self):self.assertEqual(gate(self.c(authenticated=False)),'BLOCK_PROVENANCE')
        def test_cross(self):self.assertEqual(gate(self.c(isolated=False)),'BLOCK_ACCOUNT_UNMODELED')
        def test_other_position(self):self.assertEqual(gate(self.c(other_positions=1)),'BLOCK_ACCOUNT_UNMODELED')
        def test_mark_basis(self):self.assertEqual(gate(self.c(liquidation=96.4,mark=100.5)),'BLOCK_CLEARANCE')
    unittest.main(verbosity=2)
