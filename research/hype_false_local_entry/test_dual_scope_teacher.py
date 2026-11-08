from research.hype_false_local_entry.dual_scope_teacher import (
    HOUR_MS,
    INTERNAL,
    STRICT,
    matured_pivot_label,
    finalized_terminal_label,
    teacher_contract,
)


def rows(n=10):
    out=[]
    for i in range(n):
        out.append({"start_ms":i*HOUR_MS,"high":100+i,"low":80+i})
    return out


def test_internal_matures_one_hour_earlier_than_strict():
    h=6*HOUR_MS
    assert INTERNAL.maturity_ms(h)==h+2*HOUR_MS
    assert STRICT.maturity_ms(h)==h+3*HOUR_MS


def test_internal_low_label_is_causal_after_k1_completion():
    r=rows()
    # Hour 4 is below its previous 3 hours and below/equal to next hour.
    r[4]["low"]=50
    r[5]["low"]=60
    t=4*HOUR_MS
    assert matured_pivot_label(r,t+10,"LOW",INTERNAL,INTERNAL.maturity_ms(t)-1) is None
    assert matured_pivot_label(r,t+10,"LOW",INTERNAL,INTERNAL.maturity_ms(t)) is True
    assert matured_pivot_label(r,t+10,"HIGH",INTERNAL,INTERNAL.maturity_ms(t)) is False


def test_missing_teacher_hour_never_fabricates_label():
    r=rows()
    r=[x for x in r if x["start_ms"]!=5*HOUR_MS]
    t=4*HOUR_MS
    assert matured_pivot_label(r,t,"LOW",INTERNAL,10*HOUR_MS) is None


def test_contract_separates_tactical_and_core_roles():
    c=teacher_contract()
    assert c["internal"]["role"]=="TACTICAL"
    assert c["strict"]["role"]=="CORE"
    assert "does not authorize full core flip" in c["internal"]["rule"]


def test_terminal_teacher_defers_then_replaces_same_side_pivot():
    r=[]
    lows=[100,99,98,97,90,95,85,90,95,96,97]
    highs=[110,110,110,110,110,110,110,110,120,115,114]
    for i,(lo,hi) in enumerate(zip(lows,highs)):
        r.append({"start_ms":i*HOUR_MS,"low":lo,"high":hi})

    h4=4*HOUR_MS
    h6=6*HOUR_MS

    # After K1 for hour 4, the LOW is only provisional.
    assert finalized_terminal_label(r,h4+1,"LOW",INTERNAL,6*HOUR_MS) is None

    # Once the better same-side hour-6 LOW has matured, hour 4 is false.
    assert finalized_terminal_label(r,h4+1,"LOW",INTERNAL,8*HOUR_MS) is False
    assert finalized_terminal_label(r,h6+1,"LOW",INTERNAL,8*HOUR_MS) is None

    # Hour-8 HIGH matures at hour 10 and finalizes hour-6 LOW.
    assert finalized_terminal_label(r,h6+1,"LOW",INTERNAL,10*HOUR_MS) is True


def test_terminal_teacher_ignores_rows_not_completed_at_now():
    r=rows(10)
    r[4]["low"]=50
    r[5]["low"]=60
    # A fabricated later opposite pivot exists in the supplied array, but it
    # has not completed at now=6H and therefore cannot finalize the LOW.
    r[7]["high"]=999
    assert finalized_terminal_label(r,4*HOUR_MS,"LOW",INTERNAL,6*HOUR_MS) is None
