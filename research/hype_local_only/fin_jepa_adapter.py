"""Fin-JEPA representation expert for causal HYPE Local research.

Adapted conceptually from cedricwyh/fin-jepa (MIT). The model input dimension is
explicit because the 116-point research contract contains 86 input points plus
TARGET_EVAL and METADATA points. Target/evaluation points must NEVER be inputs.
"""
from __future__ import annotations
import torch
from torch import nn
import torch.nn.functional as F

class HypeFinJEPA(nn.Module):
    def __init__(self,n_features:int,dim=64,depth=4,max_seq_len=16):
        super().__init__()
        if int(n_features)<1: raise ValueError("n_features must be positive")
        self.n_features=int(n_features)
        self.encoder=nn.Sequential(nn.Linear(self.n_features,128),nn.GELU(),nn.LayerNorm(128),nn.Linear(128,dim))
        self.position=nn.Parameter(torch.randn(1,max_seq_len,dim)*0.02)
        self.blocks=nn.ModuleList([nn.TransformerEncoderLayer(dim,4,256,dropout=0.1,activation="gelu",batch_first=True,norm_first=True) for _ in range(depth)])
        self.predictor=nn.Sequential(nn.LayerNorm(dim),nn.Linear(dim,dim),nn.GELU(),nn.Linear(dim,dim))
        self.local_heads=nn.ModuleDict({s:nn.Linear(dim,1) for s in ("LOW","HIGH")})
    def encode(self,x):
        if x.ndim!=3 or x.shape[-1]!=self.n_features:
            raise ValueError(f"Expected (batch,time,{self.n_features})")
        return self.encoder(x)
    def forward(self,x):
        z=self.encode(x)
        if z.shape[1]>self.position.shape[1]: raise ValueError("sequence exceeds max_seq_len")
        h=z+self.position[:,:z.shape[1]]
        mask=torch.triu(torch.ones(z.shape[1],z.shape[1],device=z.device,dtype=torch.bool),diagonal=1)
        for block in self.blocks:h=block(h,src_mask=mask)
        pred=self.predictor(h[:,:-1])
        latent_loss=F.mse_loss(pred,z[:,1:].detach()) if z.shape[1]>1 else z.sum()*0.0
        logits={s:head(h[:,-1]).squeeze(-1) for s,head in self.local_heads.items()}
        return {"latent_loss":latent_loss,"local_logits":logits,"embedding":h[:,-1]}

def validate_scalar_schema(feature_names):
    names=tuple(str(x) for x in feature_names)
    if not names or len(set(names))!=len(names): raise ValueError("feature schema must be non-empty and unique")
    return names
