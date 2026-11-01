"""Run explicit Flow v2 acceptance contracts 1–16 and report each separately.

Uses synthetic executions, local WebSocket frames and isolated PostgreSQL test
schemas. Shared LONG/SHORT scenarios execute once and contribute to each mapped
acceptance case. A skipped or missing test never counts as a pass.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STRATEGY = "tests.test_flow_v2_strategy.FlowV2StrategyTests."
RESET = "tests.test_flow_v2_reset.FlowExperimentResetTests."
UNIVERSE = "tests.test_flow_v2_universe.HourlyUniverseTests."
WIRE = "tests.test_flow_v2_integration.FlowV2ExecutionTests."
EVENTS = "tests.test_flow_v2_events.ExecutionEventTests."
PROOF = "tests.test_flow_v2_decision_path.FlowV2DecisionPathTests."

CASES = (
    (1, "Clean $500 reset, legacy isolation and no reset on restart", (
        RESET + "test_clean_reset_preserves_old_losses_and_new_account_survives_restart",)),
    (2, "Continuing 70/30 pump opens/holds LONG", (
        STRATEGY + "test_acceptance_2_continuing_70_30_pump_uses_executed_direction",
        WIRE + "test_wire_opens_from_new_executions_without_candles_and_polling_adds_no_proof")),
    (3, "Micro pullback holds LONG", (
        STRATEGY + "test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold",)),
    (4, "Pump exhaustion closes LONG; independent executions confirm SHORT", (
        STRATEGY + "test_acceptance_4_6_exhaustion_closes_then_requires_new_executions",
        WIRE + "test_real_flow_transfer_closes_then_new_independent_executions_reverse")),
    (5, "Small bounce holds SHORT", (
        STRATEGY + "test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold",)),
    (6, "Correction exhaustion closes SHORT; independent executions confirm LONG", (
        STRATEGY + "test_acceptance_4_6_exhaustion_closes_then_requires_new_executions",)),
    (7, "Equivalent executions are independent of wall-clock placement", (
        STRATEGY + "test_acceptance_7_receive_wall_clock_changes_do_not_change_decisions",
        PROOF + "test_active_decision_graph_has_no_candle_or_timer_gate")),
    (8, "One hundred polling calls do not advance execution proofs", (
        STRATEGY + "test_acceptance_8_repeated_polling_cannot_increase_any_proof",
        EVENTS + "test_acceptance_8_polling_never_creates_new_execution_evidence",
        WIRE + "test_wire_opens_from_new_executions_without_candles_and_polling_adds_no_proof")),
    (9, "Fee, slippage and learned noise prevent churn", (
        STRATEGY + "test_acceptance_9_costs_prevent_churn_with_even_strong_counter_volume",)),
    (10, "Hourly TOP-5 stays fixed and rotation retains managed positions", (
        UNIVERSE + "test_acceptance_10_entry_set_changes_only_at_hour_and_keeps_positions",
        WIRE + "test_rotation_preserves_held_position_and_restart_preserves_account_and_universe")),
    (11, "Restart preserves account, positions, MFE/MAE, universe and FSM", (
        UNIVERSE + "test_acceptance_11_restart_preserves_metadata_and_hourly_cycle",
        STRATEGY + "test_restart_restores_every_execution_proof_and_close_ack",
        RESET + "test_repeat_command_preserves_live_positions_mfe_and_lease",
        WIRE + "test_rotation_preserves_held_position_and_restart_preserves_account_and_universe",
        WIRE + "test_profitable_flow_add_keeps_quantity_average_and_survives_restart")),
    (12, "BUY acceleration after small dip retains LONG", (
        STRATEGY + "test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold",)),
    (13, "SELL acceleration after small bounce retains SHORT", (
        STRATEGY + "test_acceptance_3_5_12_13_micro_counter_move_and_acceleration_hold",)),
    (14, "Absorbed BUY volume is not BUY control", (
        STRATEGY + "test_acceptance_14_15_absorbed_volume_never_confirms_control",)),
    (15, "Absorbed SELL volume is not SELL control", (
        STRATEGY + "test_acceptance_14_15_absorbed_volume_never_confirms_control",)),
    (16, "Stale tape exposes uncertainty; separate risk protection and recovery", (
        STRATEGY + "test_acceptance_16_stale_state_blocks_entries_reversal_but_is_not_an_exit",
        WIRE + "test_stale_is_uncertain_without_immediate_close_then_fresh_mark_breach_can_reduce_risk")),
)


class AcceptanceResult(unittest.TextTestResult):
    """Retain base-test status, including parametrized unittest subtest failures."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statuses = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.statuses.setdefault(test.id(), "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.statuses[test.id()] = "FAIL"

    def addError(self, test, err):
        super().addError(test, err)
        self.statuses[test.id()] = "ERROR"

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.statuses[test.id()] = "SKIP"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.statuses[test.id()] = "FAIL" if issubclass(err[0], test.failureException) else "ERROR"


def build_report(result, *, generated_at=None):
    cases = []
    for number, title, names in CASES:
        tests = [{"test": name, "status": result.statuses.get(name, "NOT_RUN")} for name in names]
        statuses = {item["status"] for item in tests}
        status = ("ERROR" if "ERROR" in statuses else "FAIL" if "FAIL" in statuses
                  else "NOT_RUN" if "NOT_RUN" in statuses else "SKIP" if "SKIP" in statuses else "PASS")
        cases.append({"number": number, "title": title, "status": status, "tests": tests})
    return {
        "suite": "pandora_flow_v2_acceptance_1_to_16",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "experiment_id": "pandora_flow_v2",
        "successful": all(case["status"] == "PASS" for case in cases),
        "cases_passed": sum(case["status"] == "PASS" for case in cases),
        "cases_total": 16,
        "unique_tests_run": result.testsRun,
        "cases": cases,
        "skipped": [{"test": case.id(), "reason": reason} for case, reason in result.skipped],
        "live_exchange_verified": False,
        "production_reset_verified": False,
        "render_deployed": False,
        "note": "Software contracts with synthetic tape, loopback WebSocket and isolated PostgreSQL schemas; shared scenarios cover both directions.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps([{"number": n, "title": title, "tests": list(names)}
                          for n, title, names in CASES], indent=2))
        return 0
    binding = os.getenv("PANDORA_TEST_DATABASE_URL_FILE")
    if not binding or not Path(binding).is_file():
        parser.error("PANDORA_TEST_DATABASE_URL_FILE must name an isolated test database URL file")
    if os.getenv("DATABASE_URL") != Path(binding).read_text().strip():
        parser.error("DATABASE_URL must match the isolated test database binding")
    os.chdir(ROOT)
    names = tuple(dict.fromkeys(name for _, _, group in CASES for name in group))
    suite = unittest.TestLoader().loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2, resultclass=AcceptanceResult).run(suite)
    report = build_report(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    for case in report["cases"]:
        print(f"{case['number']:2d} {case['status']:7s} {case['title']}")
    return int(not report["successful"])


if __name__ == "__main__":
    raise SystemExit(main())
