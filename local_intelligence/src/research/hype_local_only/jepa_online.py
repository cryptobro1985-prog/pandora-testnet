"""Unarmed research learner: frozen production encoders are never passed here."""
import copy
from pathlib import Path
import torch
from .jepa import Config,NumericJEPA,objective
from .reliability import CheckpointStore,WriterLock

class OnlineJEPAChallenger:
    def __init__(self,directory:Path,seed:dict):self.directory=Path(directory);self.seed=seed
    def __enter__(self):
        self.lock=WriterLock(self.directory/'.jepa_writer.lock');self.lock.__enter__()
        try:
            self.store=CheckpointStore(self.directory);self.state=self.store.load() or copy.deepcopy(self.seed)
            if self.state.get('promoted'):raise ValueError('cannot mutate promoted encoder')
            self.model=NumericJEPA(Config(**self.state['config']));self.model.load_state_dict(self.state['model'])
            self.optimizer=torch.optim.AdamW([p for p in self.model.parameters() if p.requires_grad],lr=self.model.cfg.learning_rate)
            if self.state.get('optimizer'):self.optimizer.load_state_dict(self.state['optimizer'])
            self.state.setdefault('pending_ssl',{});self.state.setdefault('learned_ssl',set())
            self.state['role']='online_challenger_only';return self
        except BaseException:
            self.lock.__exit__();raise
    def checkpoint(self):
        self.state.update(schema=1,model=self.model.state_dict(),optimizer=self.optimizer.state_dict(),promoted=False)
        return self.store.save(self.state)
    def observe(self,event_id,context,targets,context_available_ms,target_available_ms,as_of_ms):
        if context_available_ms>as_of_ms:raise ValueError('unreceived context')
        if event_id in self.state['learned_ssl']:return 'ALREADY_LEARNED'
        if target_available_ms<=context_available_ms:raise ValueError('target must follow context')
        expected=(self.model.cfg.context,32)
        if context.ndim!=3 or tuple(context.shape[1:])!=expected:raise ValueError('invalid causal sequence shape')
        pending=self.state['pending_ssl']
        if event_id not in pending:
            pending[event_id]={'context':context.detach().clone(),'context_available_ms':context_available_ms,
                               'target_available_ms':target_available_ms}
        elif (not torch.equal(pending[event_id]['context'],context) or
              pending[event_id]['context_available_ms']!=context_available_ms):raise ValueError('prediction context changed')
        if target_available_ms<pending[event_id]['target_available_ms']:raise ValueError('target clock regressed')
        if as_of_ms<self.state.get('last_update_ms',0):raise ValueError('training clock regressed')
        pending[event_id]['target_available_ms']=target_available_ms
        if target_available_ms>as_of_ms:
            self.checkpoint();return 'WAITING_FOR_FUTURE_STATE'
        if len(targets)!=len(self.model.cfg.horizons) or any(t.shape!=context.shape for t in targets):raise ValueError('invalid target windows')
        self.optimizer.zero_grad(set_to_none=True)
        loss=objective(self.model,pending[event_id]['context'],targets,masked=False)
        if not torch.isfinite(loss):raise ValueError('nonfinite online loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(self.model.parameters(),1)
        self.optimizer.step();self.model.update_target()
        self.state['learned_ssl'].add(event_id);pending.pop(event_id)
        self.state.update(last_update_ms=as_of_ms,heads_require_revalidation=True,
            model_version=f"jepa_online_{len(self.state['learned_ssl'])}")
        self.checkpoint();return 'CHALLENGER_UPDATED'
    def __exit__(self,*args):self.lock.__exit__(*args)
