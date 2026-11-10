"""Regression tests for legal causal predictor selection in bounce CV."""
from research.hype_false_local_entry import confirmed_local_bounce_cv as cv
from research.hype_quant.feature_contract import INPUT_IDS


def test_legal_input_and_invalid_metadata():
    legal = next(p for p in sorted(INPUT_IDS) if p not in cv.QUALITY_ONLY)
    assert cv.legal_predictor(f"p{legal:03d}_observed", 1.0)
    for name in ("target_terminal", "fullmicro_raw_metadata", "p999_future", "", "pXXX_value"):
        assert not cv.legal_predictor(name, 1.0)
    assert not cv.legal_predictor(f"p{legal:03d}_observed", float("nan"))
    assert not cv.legal_predictor(f"p{legal:03d}_observed", None)


def test_forbidden_point_ids():
    forbidden = next(p for p in range(1, 117) if p not in INPUT_IDS)
    assert not cv.legal_predictor(f"p{forbidden:03d}_target", 1.0)
    if cv.QUALITY_ONLY:
        point = next(iter(cv.QUALITY_ONLY))
        assert not cv.legal_predictor(f"p{point:03d}_quality", 1.0)
