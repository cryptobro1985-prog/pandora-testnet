"""Executable boundary proof; mutation cases prevent an always-green audit."""
import ast
from pathlib import Path
import unittest

from scripts.audit_flow_decision_path import ROOT, audit


def inject_statement(module, member, statement):
    source = (ROOT / (module + ".py")).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls, _, method = member.rpartition(".")
    nodes = tree.body
    if cls:
        nodes = next(node for node in nodes if isinstance(node, ast.ClassDef) and node.name == cls).body
    node = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == (method or member))
    first = node.body[0]
    # Insert after a docstring so a valid source retains its function metadata.
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        lineno = first.end_lineno
        indent = " " * (node.col_offset + 4)
    else:
        lineno = first.lineno - 1
        indent = " " * first.col_offset
    lines = source.splitlines(keepends=True)
    lines.insert(lineno, indent + statement + "\n")
    return "".join(lines)


class FlowV2DecisionPathTests(unittest.TestCase):
    def test_active_decision_graph_has_no_candle_or_timer_gate(self):
        result = audit()
        self.assertTrue(result["ok"], result["violations"])
        self.assertIn("app.pandora_open", result["inspected_functions"])
        self.assertIn("pandora_runtime.PandoraRuntime._cycle_symbol", result["inspected_functions"])
        self.assertIn("pandora_flow_strategy.FlowStrategy._decide", result["inspected_functions"])
        self.assertIn("pandora_flow_strategy.FlowStrategy._analysis", result["inspected_functions"])

    def test_audit_rejects_injected_m15_dependency(self):
        source = inject_statement("app", "pandora_open", "live_locals([], [], 0, symbol)")
        result = audit(sources={"app": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("legacy trading helper" in item["reason"] or
                            "candle/indicator" in item["reason"] for item in result["violations"]))

    def test_audit_rejects_injected_calendar_bucket(self):
        source = inject_statement("app", "pandora_open", "decision_bucket = int(time.time() // 900)")
        result = audit(sources={"app": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("bucketing" in item["reason"] for item in result["violations"]))

    def test_audit_rejects_duration_or_window_completion_gate(self):
        for key in ("dominance_duration", "complete", "observed_seconds"):
            with self.subTest(key=key):
                source = inject_statement("app", "pandora_open", "elapsed = flow.get(" + repr(key) + ")")
                result = audit(sources={"app": source})
                self.assertTrue(any("legacy decision-state read: " + key == item["reason"]
                                    for item in result["violations"]))

    def test_audit_rejects_unreviewed_direction_helper(self):
        source = inject_statement("app", "pandora_open", "hidden_direction_gate()")
        source += "\ndef hidden_direction_gate():\n return True\n"
        result = audit(sources={"app": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("unreviewed project decision dependency: app.hidden_direction_gate" == item["reason"]
                            for item in result["violations"]))

    def test_audit_rejects_legacy_cached_analysis_read(self):
        source = inject_statement("app", "pandora_open", "cached = S.get('_pandora_analysis')")
        result = audit(sources={"app": source})
        self.assertTrue(any("legacy decision-state read: _pandora_analysis" == item["reason"]
                            for item in result["violations"]))

    def test_collector_summary_is_restricted_to_freshness(self):
        source = inject_statement("pandora_runtime", "PandoraRuntime.event_fresh", "return quality.get('buy_notional')")
        result = audit(sources={"pandora_runtime": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("freshness only" in item["reason"] for item in result["violations"]))

    def test_unreviewed_external_direction_import_is_rejected(self):
        source = inject_statement("app", "pandora_open", "external_direction()")
        source = "from unreviewed_signal_source import choose as external_direction\n" + source
        result = audit(sources={"app": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("unreviewed_signal_source.choose" in item["reason"] for item in result["violations"]))

    def test_legacy_summary_cannot_be_added_to_directional_path(self):
        source = inject_statement("app", "pandora_open", "legacy_summary([], 0, 0)")
        source = "from pandora_flow import summarize as legacy_summary\n" + source
        result = audit(sources={"app": source})
        self.assertFalse(result["ok"])
        self.assertTrue(any("pandora_flow.summarize" in item["reason"] for item in result["violations"]))

    def test_legacy_history_code_is_outside_active_roots(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        source += "\ndef historical_ui_only():\n return execution_anchor({'m15_confirmation': True}, {})\n"
        baseline = audit()
        result = audit(sources={"app": source})
        self.assertEqual(baseline["violations"], result["violations"])
        self.assertNotIn("app.historical_ui_only", result["inspected_functions"])

    def test_risk_and_accounting_are_preserved_from_baseline(self):
        result = audit()
        self.assertTrue(all(item["unchanged"] for item in result["preserved_money_engine"].values()))
        source = (ROOT / "pandora_risk.py").read_text(encoding="utf-8") + "\n# changed\n"
        changed = audit(sources={"pandora_risk": source})
        self.assertFalse(changed["preserved_money_engine"]["pandora_risk.py"]["unchanged"])


if __name__ == "__main__":
    unittest.main()
