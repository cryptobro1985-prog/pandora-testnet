from research.hype_false_local_entry.dual_scope_teacher import (
    HOUR_MS,
    INTERNAL,
    STRICT,
    matured_pivot_label,
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
