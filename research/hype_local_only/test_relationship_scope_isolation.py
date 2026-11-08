from research.hype_local_only.live_relationship_miner import mine_heads,split_scopes


def row(teacher,label,value):
    return {"teacher":teacher,"side":"LOW","stage":60,"label":label,
            "features":{"x":float(value)}}


def test_relationship_rows_never_pool_teacher_scopes():
    rows=[]
    # Old rows without teacher remain STRICT for backward compatibility.
    rows += [row(None,True,1),row("STRICT_L6_K2",False,0)]
    rows += [row("INTERNAL_L3_K1",True,10),row("INTERNAL_L3_K1",False,9)]
    strict,internal=split_scopes(rows)
    assert len(strict)==2
    assert len(internal)==2
    assert all(r.get("teacher")!="INTERNAL_L3_K1" for r in strict)
    assert all(r.get("teacher")=="INTERNAL_L3_K1" for r in internal)

    sh=mine_heads(strict)["LOW_60s"]
    ih=mine_heads(internal)["LOW_60s"]
    assert sh["examples"]==2
    assert ih["examples"]==2
