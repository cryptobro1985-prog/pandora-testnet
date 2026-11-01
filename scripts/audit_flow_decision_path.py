"""AST and scoped-grep proof for the active PAPER flow decision path.

Run from any directory. Legacy candle/history/UI code is deliberately outside
the roots. Every reachable project helper must be in the reviewed allowlist;
adding a new directional dependency requires updating this audit and its tests.
This is a static boundary check, complemented by event-replay acceptance tests.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
PRESERVED = {
    "pandora_risk": "dcc3bee9df53696a08eddbefe36ed73e3d219a956f71d8cf101f0cc0184b6ef3",
    "accounting": "310bdd2b1988fbe1b2a3d17adf0c7ec73eaa85391599f7a7517664e82553a11e",
}
ROOTS = (
    "app.pandora_open", "app.pandora_mark_positions",
    "app.pandora_flow_fast_entries", "pandora_runtime.PandoraRuntime.pyramid",
    "pandora_runtime.PandoraRuntime._cycle_symbol",
    "pandora_win_core.pyramid_decision",
)
# These modules form the fully inspected strategy boundary, including private
# helpers. Their imports may not escape into legacy candle/indicator modules.
PURE_MODULES = {"pandora_flow_strategy", "pandora_win_core"}
APP_HELPERS = {
    "account_mutation", "now", "pg", "publication_epoch", "journal", "log_learning_decision",
    "fresh_mark_price", "current_entry_price", "pandora_trade_symbols",
    "pandora_runtime_symbols", "_pandora_margin_state", "risk_snapshot",
    "_pandora_watch_clear", "_pandora_watch_observe", "pandora_open",
    "pandora_close", "pandora_mark_positions", "pandora_flow_fast_entries",
}
RUNTIME_HELPERS = {
    "pyramid", "_cycle_symbol", "event", "transition", "save_token",
    "reload_token", "semantic_open", "semantic_close", "_write_runtime",
    "event_fresh", "current_decision", "entry_decision", "flow_snapshot",
    "cycle", "_cycle",
}
# Operational boundaries do not decide direction: account fencing/persistence,
# fresh transport/mark checks, and a universe membership snapshot. Risk is
# separately verified byte-for-byte, and gets a flow-only compatibility adapter.
BOUNDARIES = {
    "engine_store": "single-writer lease and fence",
    "pandora_universe": "hourly universe membership, never trade direction",
    "psycopg": "transactional PAPER persistence",
}
EXACT_BOUNDARIES = {
    "pandora_experiment.configure_connection_args": "validated experiment search path; no public fallback",
}
FRESHNESS_FUNCTION = "pandora_runtime.PandoraRuntime.event_fresh"
FRESHNESS_BOUNDARY = "market_data.RollingMarketData.flow_context"
FORBIDDEN_MODULES = {
    "h1_structure", "pandora_locals", "local_order_flow", "pandora_bootstrap",
    "pandora_decisions",
}
SAFE_IMPORTS = {
    "copy", "math", "dataclasses", "typing", "collections", "enum",
    "bisect", "decimal", "__future__", "pandora_flow", "pandora_risk", "accounting",
}
OPERATIONAL_IMPORTS = (SAFE_IMPORTS - {"pandora_flow", "pandora_risk", "accounting"}) | {
    "datetime", "functools", "hashlib", "json", "os", "time",
}
FORBIDDEN_NAME = re.compile(
    r"(?:^|_)(?:m15|h1|candles?|klines?|macd|ema|mfi|rsi|time_bucket|"
    r"minute_number|periodic_reversal)(?:_|$)", re.I,
)
FORBIDDEN_FIELDS = {
    "_pandora_analysis", "pandora_win_h1_direction", "m15_confirmation",
    "m15_confirmed_local", "h1_direction_anchor", "forming_local",
    "forming_locals", "confirmed_local", "execution_local",
    "confirmation_candle_time", "confirmation_close_time", "last_candle_time",
    "complete", "dominance_duration", "evidence_required_seconds",
    "required_seconds", "observed_seconds",
}
GREP = re.compile(r"\bM15\b|\bH1\b|\bMACD\b|\bEMA\b|\bMFI\b|\bRSI\b|"
                  r"pandora_runtime_h1_verified|execution_anchor|entry_structure_valid|"
                  r"time_bucket|minute_number", re.I)


def _functions(tree: ast.Module):
    result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result[node.name + "." + child.name] = child
    return result


def _imports(tree: ast.Module):
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                result[alias.asname or alias.name] = node.module + "." + alias.name
    return result


def _chain(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _chain(node.value) + "." + node.attr
    return ""


def _forbidden_field(function, key):
    # Account valuation completeness means every held symbol has a fresh mark;
    # it is unrelated to completion of a flow measurement horizon.
    return key in FORBIDDEN_FIELDS and not (function == "app.risk_snapshot" and key == "complete")


def _executable_nodes(node):
    """Skip docstrings; SQL text is storage metadata, not an executable key."""
    for item in ast.walk(node):
        if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
            continue
        yield item


def audit(root: Path = ROOT, sources: Mapping[str, str] | None = None):
    """Return a JSON-serializable report; sources overrides support mutation tests."""
    root = Path(root)
    source = {p.stem: p.read_text(encoding="utf-8") for p in root.glob("*.py")}
    source.update(sources or {})
    trees = {name: ast.parse(text, filename=name + ".py") for name, text in source.items()}
    imports = {name: _imports(tree) for name, tree in trees.items()}
    functions = {module + "." + name: node for module, tree in trees.items()
                 for name, node in _functions(tree).items()}
    violations = []
    inspected = set()
    edges = set()
    grep_hits = []

    def fail(function, node, reason):
        entry = {"function": function, "line": getattr(node, "lineno", 1), "reason": reason}
        if entry not in violations:
            violations.append(entry)

    def approved(name):
        module, _, member = name.partition(".")
        return (module in PURE_MODULES or module in PRESERVED or
                module == "app" and member in APP_HELPERS or
                module == "pandora_runtime" and member.removeprefix("PandoraRuntime.") in RUNTIME_HELPERS or
                name in {"market_data.RollingMarketData.events_after",
                         "market_data.RollingMarketData.event_status",
                         "market_data.RollingMarketData._sequence"})

    def resolve(function, call):
        module = function.split(".", 1)[0]
        chain = _chain(call.func)
        head, _, tail = chain.partition(".")
        if head in imports[module]:
            candidate = imports[module][head] + ("." + tail if tail else "")
            return candidate
        if module + "." + chain in functions:
            return module + "." + chain
        if chain.startswith(("WIN.", "a.WIN.", "self.a.WIN.")):
            candidate = "pandora_runtime.PandoraRuntime." + chain.rsplit(".", 1)[-1]
            if candidate in functions:
                return candidate
        if chain.startswith(("a.", "self.a.")):
            member = chain.rsplit(".", 1)[-1]
            if "app." + member in functions:
                return "app." + member
        if chain.startswith("self.") and "." in function.split(".", 1)[1]:
            cls = function.rsplit(".", 1)[0]
            candidate = cls + "." + chain.removeprefix("self.")
            if candidate in functions:
                return candidate
        if "MARKET_OBS." in chain:
            return "market_data.RollingMarketData." + chain.rsplit(".", 1)[-1]
        # Runtime owns the strategy instance; these methods are part of the
        # inspected pure module even when Python receiver typing is dynamic.
        member = chain.rsplit(".", 1)[-1]
        matches = [name for name in functions
                   if name.startswith("pandora_flow_strategy.") and name.endswith("." + member)]
        strategy_receiver = chain.startswith(("self.strategy.", "WIN.strategy.", "clone.", "self.a.WIN.strategy."))
        return matches[0] if strategy_receiver and len(matches) == 1 else None

    queue = list(ROOTS)
    for module in PURE_MODULES:
        if module not in trees:
            fail(module, ast.Module(body=[], type_ignores=[]), "required pure strategy module is missing")
            continue
        queue.extend(name for name in functions if name.startswith(module + "."))
        for imported in imports[module].values():
            dep = imported.split(".", 1)[0]
            if dep not in SAFE_IMPORTS:
                fail(module, trees[module], "unreviewed pure-strategy import: " + imported)

    while queue:
        name = queue.pop()
        if name in inspected:
            continue
        if name not in functions:
            fail(name, ast.Module(body=[], type_ignores=[]), "required decision function is missing")
            continue
        inspected.add(name)
        module = name.split(".", 1)[0]
        node = functions[name]
        for decorator in node.decorator_list:
            target = module + "." + _chain(decorator)
            if target in functions:
                if approved(target):
                    queue.append(target)
                else:
                    fail(name, decorator, "unreviewed decision decorator: " + target)
        if name == FRESHNESS_FUNCTION:
            # This is the sole consumer of the legacy collector summary in the
            # trading graph. Prove its use is restricted to the freshness bit;
            # direction/sizing metrics come from FlowStrategy, never this blob.
            parents = {child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)}
            for item in ast.walk(node):
                if not isinstance(item, ast.Name) or item.id != "quality" or not isinstance(item.ctx, ast.Load):
                    continue
                attr = parents.get(item)
                call = parents.get(attr)
                if not (isinstance(attr, ast.Attribute) and attr.attr == "get" and
                        isinstance(call, ast.Call) and call.args and
                        isinstance(call.args[0], ast.Constant) and call.args[0].value == "trade_data_fresh"):
                    fail(name, item, "collector summary may supply freshness only, never direction")
        for item in _executable_nodes(node):
            if isinstance(item, (ast.Name, ast.Attribute)):
                token = item.id if isinstance(item, ast.Name) else item.attr
                if FORBIDDEN_NAME.search(token):
                    fail(name, item, "forbidden candle/indicator dependency: " + token)
                if isinstance(item, ast.Attribute) and item.attr in {"hour", "minute", "second"}:
                    fail(name, item, "calendar field may not drive a decision: " + item.attr)
            if isinstance(item, ast.BinOp):
                # `%` with a string is formatting (ledger IDs and log text).
                # Numeric modulo/floor-division in this path is a forbidden
                # decision bucket; continuous rolling measurements use ranges.
                is_format = isinstance(item.left, ast.Constant) and isinstance(item.left.value, str)
                if isinstance(item.op, ast.FloorDiv) or isinstance(item.op, ast.Mod) and not is_format:
                    fail(name, item, "clock/window bucketing is forbidden in the decision path")
            if isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Load):
                if isinstance(item.slice, ast.Constant) and _forbidden_field(name, item.slice.value) and module not in PRESERVED:
                    fail(name, item, "legacy decision-state read: " + str(item.slice.value))
            if not isinstance(item, ast.Call):
                continue
            chain = _chain(item.func)
            if module == "pandora_flow_strategy" and chain.startswith(("time.", "datetime.")):
                fail(name, item, "pure strategy may not read a wall clock")
            if chain.endswith(".strftime") or chain in {"eval", "exec", "__import__", "getattr", "setattr", "globals", "locals"}:
                fail(name, item, "dynamic/calendar decision dependency: " + chain)
            if chain.endswith(".get") and item.args and isinstance(item.args[0], ast.Constant):
                key = item.args[0].value
                if _forbidden_field(name, key) and module not in PRESERVED:
                    fail(name, item, "legacy decision-state read: " + str(key))
            target = resolve(name, item)
            if not target:
                continue
            dep = target.split(".", 1)[0]
            edges.add((name, target))
            if target == FRESHNESS_BOUNDARY:
                if name != FRESHNESS_FUNCTION:
                    fail(name, item, "legacy collector summary may be consumed only by the audited freshness adapter")
            elif target in EXACT_BOUNDARIES:
                continue
            elif dep in FORBIDDEN_MODULES:
                fail(name, item, "legacy trading helper is reachable: " + target)
            elif dep in BOUNDARIES:
                continue
            elif dep in OPERATIONAL_IMPORTS:
                continue
            elif not approved(target):
                fail(name, item, "unreviewed project decision dependency: " + target)
            elif target in functions:
                queue.append(target)
        # Grep the exact executable function, filtering comments/docstrings by
        # token scope; a hit is evidence to inspect, and AST decides pass/fail.
        for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            line = source[module].splitlines()[lineno - 1]
            if GREP.search(line) and not line.lstrip().startswith("#"):
                grep_hits.append({"function": name, "line": lineno, "text": line.strip()})

    preserved = {}
    for module, expected in PRESERVED.items():
        actual = hashlib.sha256(source.get(module, "").encode()).hexdigest()
        preserved[module + ".py"] = {"expected": expected, "actual": actual, "unchanged": actual == expected}
        if actual != expected:
            fail(module, trees.get(module, ast.Module(body=[], type_ignores=[])),
                 "preserved money engine changed from the audited baseline")
    return {
        "ok": not violations,
        "roots": list(ROOTS),
        "inspected_functions": sorted(inspected),
        "dependencies": [{"from": a, "to": b} for a, b in sorted(edges)],
        "operational_boundaries": BOUNDARIES,
        "exact_operational_boundaries": EXACT_BOUNDARIES,
        "freshness_only_boundary": {"function": FRESHNESS_BOUNDARY,
                                    "consumer": FRESHNESS_FUNCTION,
                                    "permitted_field": "trade_data_fresh"},
        "scoped_grep_hits": grep_hits,
        "preserved_money_engine": preserved,
        "violations": sorted(violations, key=lambda x: (x["function"], x["line"], x["reason"])),
        "scope": "Active AST roots and reviewed project dependencies; historical/UI candle code is excluded.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(not result["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
