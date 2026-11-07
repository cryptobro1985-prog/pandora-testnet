"""Isolated paper/error tools; never execution authorities or order clients."""
from dataclasses import dataclass,field
from pathlib import Path
from .reliability import JsonlEvidence

@dataclass
class ShadowLeg:
    side:int
    entry:float
    entry_ts_ms:int
    mfe_bps:float=0.
    mae_bps:float=0.
    def mark(self,price):
        move=self.side*(price/self.entry-1)*10000
        self.mfe_bps=max(self.mfe_bps,move);self.mae_bps=min(self.mae_bps,move)

@dataclass
class ShadowPolicy:
    position:ShadowLeg|None=None
    closed:list=field(default_factory=list)
    def observe(self,ts_ms,price,side=None,state='CONTINUATION',validated=False):
        if self.position:self.position.mark(price)
        result={'ts_ms':ts_ms,'state':state,'research_only':True,'real_orders':False}
        if state not in ('LOCAL_CONFIRMED_BY_MODEL','TEACHER_CONFIRMED') or not validated or side not in ('LOW','HIGH'):
            return dict(result,decision='HOLD' if self.position else 'WATCH')
        desired=1 if side=='LOW' else -1
        if self.position and self.position.side==desired:return dict(result,decision='HOLD')
        if self.position:
            self.closed.append({**vars(self.position),'exit':price,'exit_ts_ms':ts_ms,
                'gross_bps':self.position.side*(price/self.position.entry-1)*10000,
                'costs_modelled':False})
        self.position=ShadowLeg(desired,price,ts_ms)
        return dict(result,decision='PAPER_LONG' if desired==1 else 'PAPER_SHORT')

class ErrorMemory:
    def __init__(self,path:Path):self.evidence=JsonlEvidence(path)
    def mature(self,event_id,as_of_ms,available_ms,truth,predicted,extreme_ts_ms,
               first_suspected_ms,signal_ms,quantum_probability=None,jepa_probability=None,diagnostics=None):
        if available_ms>as_of_ms:raise ValueError('teacher outcome not available')
        if truth not in ('LOW','HIGH','CONTINUATION') or predicted not in ('LOW','HIGH','CONTINUATION'):
            raise ValueError('invalid error-memory class')
        row={'event_id':event_id,'teacher_available_ms':available_ms,'as_of_ms':as_of_ms,
            'truth':truth,'predicted':predicted,'extreme_ts_ms':extreme_ts_ms,
            'first_suspected_ms':first_suspected_ms,'signal_ms':signal_ms,
            'quantum_probability':quantum_probability,'jepa_probability':jepa_probability,
            'false_positive':predicted!='CONTINUATION' and predicted!=truth,
            'false_negative':truth!='CONTINUATION' and predicted!=truth,
            'detection_delay_ms':None if signal_ms is None else signal_ms-extreme_ts_ms,
            'diagnostics':diagnostics or {},'research_only':True,'real_orders':False}
        return self.evidence.append(row)

def causal_cortex_evidence(value,as_of_ms):
    """Advisory diagnostics only; immature prediction errors stay unknown."""
    import math
    if not isinstance(value,dict):return {}
    timestamp=value.get('prediction_ts_ms')
    if not isinstance(timestamp,int) or timestamp<=0 or timestamp>as_of_ms:return {}
    output={k:value[k] for k in ('prediction_ts_ms','model_version','forward_eligible') if k in value}
    raw=value.get('diagnostics') or {};diagnostics={}
    for k in ('latent_norm','latent_distance','latent_velocity','latent_acceleration','horizon_disagreement'):
        v=raw.get(k)
        if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v):diagnostics[k]=v
    target_time=value.get('target_available_ms')
    mature=isinstance(target_time,int) and 0<target_time<=as_of_ms
    error=raw.get('prediction_error')
    diagnostics['prediction_error']=error if mature and isinstance(error,(int,float)) and math.isfinite(error) else None
    output['diagnostics']=diagnostics;output['advisory_only']=True
    return output
