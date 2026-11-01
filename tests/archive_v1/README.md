# Retired Pandora v1 application requirements

These source files preserve historical acceptance tests for the previous
H1/M15-directed application. They are archived because the flow-v2 specification
explicitly replaces their entry, exit, reversal and refresh requirements. They
are not a collection of unexplained failures or skipped active tests.

| Archived file | Retired requirement | Replacement |
| --- | --- | --- |
| `pandora_end_to_end_v1.py` | H1 determines direction; 15 seconds of tape warmup and three seconds of exit confirmation; local structure permits re-entry | Event-driven executed-flow application integration in `tests/test_flow_v2_*` |
| `persistent_pyramid_h1_v1.py` | H1 fixture drives opening and pyramiding; a new confirmed local changes reversal direction | New executed-flow PostgreSQL/wire integration; pure sizing, quantity, fee and MFE tests remain active |
| `incident_integration_v1.py` | Closed M15 structure changes application direction; historical pivot geometry vetoes entries; same-cycle H1 reversal | Independent new executions confirm direction and reversal; valuation, dashboard, history recovery and maintenance accounting tests remain active in `test_incident_integration.py` |
| `runtime_h1_gate_v1.py` | Application trading readiness depends on a verified closed H1 anchor | Flow freshness and new executed evidence determine readiness |

The active bootstrap rotation regression now releases a closed, deselected token's
old watch instead of retaining every old watch subscription. This implements the
flow-v2 requirement to retain deselected symbols while their position remains
open, then release them after complete closure. Direct close tests now require
`WAIT_INDEPENDENT_EXECUTIONS`; a close or maintenance event cannot invent the old
`counter_pressure_seen` confirmation.

The original files can be used with the original v1 project archive for historical
comparison. Their filenames do not start with `test_`, and the release runner
continues to include every current `tests/test_*.py` module. No active failure is
converted to a skip. Standalone H1/M15 analysis and local-flow helper tests remain
active as compatibility checks for historical/UI code; they are not flow-v2
application acceptance tests.
