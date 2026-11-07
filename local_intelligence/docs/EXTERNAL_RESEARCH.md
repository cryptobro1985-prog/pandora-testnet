# External model research — verified scope

Sources retrieved from official project repositories on 2026-11-07. The attached text copies are evidence of documentation, not a successful local model installation or a LOW/HIGH benchmark.

| Candidate | Verified official facts | Decision for this CPU instance |
|---|---|---|
| OpenAI gpt-oss-20b | Official README: 21B total, 3.6B active, Apache 2.0, MXFP4 about 16GB memory; Harmony format required. | Retain an optional structured adapter, outside inference path. No weights installed here; no market-quality or inference-latency claim. |
| OpenAI gpt-oss-120b | Official README describes a single 80GB GPU configuration. | Exceeds this machine's GPU resources; not installed. |
| Qwen3 | Official README documents dense 0.6/1.7/4/8/14/32B and MoE variants, reasoning/nonreasoning modes and llama.cpp serving. | Smaller candidate for a later controlled meta-analysis benchmark; checkpoint-specific license, quantization and RAM must be checked before downloading. Not selected on model-card language alone. |
| Amazon Chronos-2 | Official repository: 120M parameters (28M small alternative), covariate-informed multivariate forecasting, Apache 2.0. | Different target from delayed H1 pivot classification; needs a separately designed causal comparison. Not installed or reported as a measured winner. |
| Google TimesFM | Official repository describes pretrained time-series forecasting. | Forecasting utility does not establish H1 pivot detection utility. Not benchmarked. |
| Paid cloud reasoning APIs | No API key bindings configured; official pricing page was blocked by environment policy. | Provider adapters/fallback may be tested locally, but service access, current price and incremental predictive utility remain unverified. No paid requests made. |

This machine reports 5 CPUs and ~33GiB RAM and has no NVIDIA device or nvidia-smi. Those observations do not measure inference speed for uninstalled weights. Statistical Cortex uses CPU only and requires no external model service. There is no measured basis for calling any contemporary LLM the best Local detector.

Official sources:

- https://raw.githubusercontent.com/openai/gpt-oss/main/README.md
- https://raw.githubusercontent.com/openai/gpt-oss/main/LICENSE
- https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md
- https://raw.githubusercontent.com/QwenLM/Qwen3/main/README.md
- https://raw.githubusercontent.com/amazon-science/chronos-forecasting/main/README.md
- https://raw.githubusercontent.com/google-research/timesfm/master/README.md

Requests to HuggingFace model cards and https://openai.com/api/pricing/ were denied with HTTP tunnel 403. This is a configured-network access limitation, not evidence that those services or models are unavailable globally. Current live Bybit REST and stream destinations are also denied; see NETWORK_CHECK.json. The saved draft domains need to be applied in environment settings before a fresh REST/WSS test.
