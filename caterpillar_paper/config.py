from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
import re


@dataclass(frozen=True)
class Config:
    start_equity: float = 500.0
    margin_fraction: float = 0.20
    leverage: float = 25.0
    fee_bps: float = 4.5
    slippage_bps: float = 2.0
    maintenance_fraction: float = 0.005
    block_trades: int = 32
    baseline_blocks: int = 256
    warmup_blocks: int = 8
    transfer_blocks: int = 2
    control_imbalance: float = 0.15
    freshness_seconds: float = 15.0
    h1_lookback: int = 4
    minimum_turnover: float = 10_000_000.0
    maximum_spread_bps: float = 20.0
    scanner_seconds: int = 30
    checkpoint_seconds: int = 30
    snapshot_seconds: int = 5
    publish_seconds: int = 60
    paper_symbols: tuple = ()
    pyramiding: bool = False

    def __post_init__(self):
        for k, v in asdict(self).items():
            if isinstance(v, (float, int)) and not isinstance(v, bool) and (not math.isfinite(v) or v <= 0):
                if k not in ('fee_bps', 'slippage_bps') or v != 0:
                    raise ValueError('Invalid config: '+k)
        for k in ('block_trades', 'baseline_blocks', 'warmup_blocks', 'transfer_blocks', 'h1_lookback',
                  'scanner_seconds', 'checkpoint_seconds', 'snapshot_seconds', 'publish_seconds'):
            if type(getattr(self, k)) is not int:
                raise ValueError(k+' must be an integer')
        if not 0 < self.margin_fraction <= .2 or not 1 <= self.leverage <= 25:
            raise ValueError('PAPER risk limits: margin <=20%, leverage <=25x')
        if not 0 < self.control_imbalance < 1 or self.block_trades < 2 or self.h1_lookback < 2:
            raise ValueError('Invalid evidence configuration')
        if self.baseline_blocks < self.warmup_blocks or self.warmup_blocks < 2 or self.transfer_blocks < 2:
            raise ValueError('Need past baseline and multiple transfer observations')
        if self.fee_bps >= 100 or self.slippage_bps >= 100 or self.maintenance_fraction >= 1/self.leverage:
            raise ValueError('Invalid costs/maintenance')
        if self.pyramiding:
            raise ValueError('Pyramiding disabled: historical add rule NOT VERIFIED')
        if self.paper_symbols and (len(self.paper_symbols) != 5 or len(set(self.paper_symbols)) != 5
                                   or any(not re.fullmatch(r'[A-Z0-9]{1,24}', s) for s in self.paper_symbols)):
            raise ValueError('PAPER_SYMBOLS must contain five unique base symbols')

    @classmethod
    def from_env(cls):
        values = {}
        for name, field in cls.__dataclass_fields__.items():
            raw = os.getenv(name.upper())
            if raw is None:
                continue
            if name == 'paper_symbols':
                values[name] = tuple(s.strip().upper().removesuffix('USDT') for s in raw.split(',') if s.strip())
            elif name == 'pyramiding':
                values[name] = raw.lower() in ('true', '1', 'yes')
            else:
                values[name] = type(field.default)(raw)
        return cls(**values)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


METADATA = {
    'version': 'CATERPILLAR_RUNTIME_V1', 'mode': 'PAPER_ONLY',
    'historical_source': '0788b22a67f9f2a11e1dcb85676403721f76b074',
    'research_source': 'a12e23d8e0507725844ec0466e18db69afddf84b',
    'local_algorithm': 'research.H1Tracker/h1_lb4_retreat0_b1',
    'flow_algorithm': 'research.features/nonoverlapping_execution_blocks',
    'entry_version': 'confirmed_H1+responsive_control+acceleration/v1',
    'exit_version': 'two_block_effective_transfer_or_structural/v1',
    'reentry_version': 'original_local+cost_scaled_correction+control+acceleration/v1',
    'artifact_findings': 'NOT VERIFIED: remote Actions artifacts inaccessible at implementation time',
    'liquidation_model': 'conservative isolated-margin maintenance approximation; gaps can exceed margin',
    'limitations': 'Funding, depth, market impact, queue priority and exact exchange liquidation not modeled',
}
