import json

import research.hype_local_only.cortex_daemon as c


class Resp:
    def __init__(self,status,obj=None,text=""):
        self.status_code=status
        self._obj=obj or {}
        self.text=text
    def raise_for_status(self):
        if self.status_code>=400:
            raise RuntimeError(f"http {self.status_code}")
    def json(self):
        return self._obj


def test_discover_model_uses_actual_llama_id(monkeypatch):
    monkeypatch.setattr(c.requests,"get",lambda *a,**k:Resp(200,{"data":[{"id":"real-model-id"}]}))
    assert c.discover_model_id("http://x","gpt-oss-20b-local")=="real-model-id"


def test_call_cortex_retries_without_json_mode_and_uses_real_model(monkeypatch):
    monkeypatch.setattr(c.requests,"get",lambda *a,**k:Resp(200,{"data":[{"id":"real-model-id"}]}))
    seen=[]
    def post(url,json=None,timeout=None):
        seen.append(json)
        if "response_format" in json:
            return Resp(400,text="response_format unsupported")
        return Resp(200,{"choices":[{"message":{"content":'{"verdict":"WAIT","confidence":0.5,"supporting_relationships":[],"contradicting_relationships":[],"missing_live_evidence":[],"summary":"ok"}'}}]})
    monkeypatch.setattr(c.requests,"post",post)
    out=c.call_cortex("http://x","wrong-alias",{"x":1},5)
    assert out["verdict"]=="WAIT"
    assert out["_model_id"]=="real-model-id"
    assert len(seen)==2
    assert seen[0]["model"]=="real-model-id"
    assert seen[0]["max_tokens"]==500
    assert "response_format" in seen[0] and "response_format" not in seen[1]


def test_compact_memory_stays_small_even_with_large_relationship_lists():
    rel=[{"feature":f"f{i}","effect":i/10,"median":i,"support":100,
          "extra":"x"*1000} for i in range(100)]
    pair=[{"a":f"a{i}","b":f"b{i}","lift":2.0,"support":20,
           "extra":"x"*1000} for i in range(100)]
    mem={"heads":{},"internal_heads":{},"h1_heads":{}}
    for side in ("LOW","HIGH"):
        for stage in (60,180,300):
            k=f"{side}_{stage}s"
            mem["heads"][k]={"top_feature_relationships":rel,"top_pair_relationships":pair}
            mem["internal_heads"][k]={"top_feature_relationships":rel,"top_pair_relationships":pair}
        mem["h1_heads"][side]={"top_feature_relationships":rel,"top_pair_relationships":pair}
    payload=c.compact_memory(mem,"LOW")
    assert len(json.dumps(payload,separators=(",",":")))<12_000
