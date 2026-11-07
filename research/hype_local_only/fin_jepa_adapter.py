"""Research-only Fin-JEPA adapter for HYPE 116-feature sequences.

Architecture adapted from https://github.com/cedricwyh/fin-jepa (MIT).
No pretrained stock weights are used; HYPE requires independent training.
This module NEVER places orders or promotes a model automatically.
"""
from __future__ import annotations
import torch
from torch import nn
import torch.nn.functional as F

class HypeFinJEPA(nn.Module):
    def __init__(self, n_features=116, dim=64, depth=4):
        super().__init__()
        self.encoder=nn.Sequential(nn.Linear(n_features,128),nn.GELU(),nn.LayerNorm(128),nn.Linear(128,dim))
        self.position=nn.Parameter(torch.randn(1,256,dim)*0.02)
        self.blocks=nn.ModuleList([nn.TransformerEncoderLayer(dim,4,256,dropout=0.1,activation="gelu",batch_first=True,norm_first=True) for _ in range(depth)])
        self.head=nn.Sequential(nn.LayerNorm(dim),nn.Linear(dim,dim))
        self.local_heads=nn.ModuleDict({s:nn.Linear(dim,1) for s in ("LOW","HIGH")})
    def encode(self,x):
        if x.ndim!=3 or x.shape[-1]!=116:raise ValueError("Expected (batch,time,116)")
        return self.encoder(x)
    def forward(self,x):
        z=self.encode(x)
        if z.shape[1]>256:raise ValueError("Maximum 256 context steps")
        h=z+self.position[:,:z.shape[1]]
        mask=torch.triu(torch.ones(z.shape[1],z.shape[1],device=z.device,dtype=torch.bool),diagonal=1)
        for block in self.blocks:h=block(h,src_mask=mask)
        predicted=self.head(h[:,:-1])
        target=z[:,1:].detach()
        local_logits={s:head(h[:,-1]).squeeze(-1) for s,head in self.local_heads.items()}
        return {"latent_loss":F.mse_loss(predicted,target),"local_logits":local_logits,"embedding":h[:,-1]}
    def supervised_loss(self,x,labels):
        result=self(x)
        losses=[F.binary_cross_entropy_with_logits(result["local_logits"][s],labels[s].float()) for s in ("LOW","HIGH")]
        return result["latent_loss"]+sum(losses),result

def validate_contract(feature_names):
    if len(feature_names)!=116 or len(set(feature_names))!=116:
        raise ValueError("Need exactly 116 unique named features in a fixed order")
    return tuple(feature_names)
