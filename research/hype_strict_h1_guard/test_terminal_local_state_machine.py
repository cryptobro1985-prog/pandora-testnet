from research.hype_strict_h1_guard.terminal_local_state_machine import K2Pivot, TerminalLocalTracker

def p(side, price, t):
    return K2Pivot(side=side, price=price, extreme_ts_ms=t, confirmed_ts_ms=t+120_000)

def test_terminal_collapse():
    t=TerminalLocalTracker()
    assert t.ingest(p("LOW",100,0))["event"]=="PIVOT_PROVISIONAL"
    assert t.ingest(p("LOW",99,1_000_000))["event"]=="PIVOT_REPLACED"
    assert t.ingest(p("LOW",99.5,2_000_000))["event"]=="SAME_SIDE_WEAKER_IGNORED"
    e=t.ingest(p("HIGH",110,3_000_000))
    assert e["event"]=="TERMINAL_FINAL_AND_FLIP"
    assert e["terminal_final"]["price"]==99
    assert t.ingest(p("HIGH",111,4_000_000))["event"]=="PIVOT_REPLACED"
    e=t.ingest(p("LOW",101,5_000_000))
    assert e["terminal_final"]["side"]=="HIGH"
    assert e["terminal_final"]["price"]==111
