"""Characterization tests for batch/sample selector handling.

Verifies prefix-aware normalization and sample splitting using a neutral
configured batch prefix (``TE``) so tests behave identically across clean
clones and customized local workspaces.
"""

from __future__ import annotations

from unittest.mock import patch

from _helpers import load_script

_plot_te = None
_run_analysis = None


def _scripts():
    global _plot_te, _run_analysis
    if _plot_te is None:
        _plot_te = load_script("scripts/plotting/plot_te.py", "plot_te_under_test")
        _run_analysis = load_script(
            "scripts/analysis/run_analysis.py", "run_analysis_under_test"
        )
    return _plot_te, _run_analysis


NORMALIZE_BATCH_ID_CASES = {
    "TE-1054": "TE-1054",
    "1054": "TE-1054",
    "Batch-1054": "TE-1054",
    "1054-B": "TE-1054-B",
    "TE-1054B": "TE-1054B",
    "1054B": "TE-1054B",
    "TE-1054-B": "TE-1054-B",
    "TE-1054/B": "TE-1054/B",
    "TE-1054:B": "TE-1054:B",
    "weird name": "weird name",
    "": "",
}

PLOT_TE_NORMALIZE_CASES = dict(
    NORMALIZE_BATCH_ID_CASES,
    **{"TE-1054B": "TE-1054-B", "1054B": "TE-1054-B"},
)

PARSE_BATCH_SAMPLE_CASES = {
    "TE-1054": ("TE-1054", None),
    "1054": ("TE-1054", None),
    "Batch-1054": ("TE-1054", None),
    "1054-B": ("TE-1054", "TE-1054-B"),
    "TE-1054B": ("TE-1054B", None),
    "1054B": ("TE-1054B", None),
    "TE-1054-B": ("TE-1054", "TE-1054-B"),
    "TE-1054/B": ("TE-1054", "TE-1054/B"),
    "TE-1054:B": ("TE-1054", "TE-1054:B"),
    "weird name": ("weird name", None),
    "": ("", None),
}


def test_plot_te_normalize_selector():
    plot_te, _ = _scripts()
    with patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
        for raw, expected in PLOT_TE_NORMALIZE_CASES.items():
            assert plot_te.normalize_selector(raw) == expected, raw


def test_run_analysis_normalize_batch_id():
    _, run_analysis = _scripts()
    with patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
        for raw, expected in NORMALIZE_BATCH_ID_CASES.items():
            assert run_analysis.normalize_batch_id(raw) == expected, raw


def test_xrd_normalize_batch_selector():
    from te_analysis.tools.selectors import normalize_batch_id as normalize_batch_selector

    with patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
        for raw, expected in NORMALIZE_BATCH_ID_CASES.items():
            assert normalize_batch_selector(raw) == expected, raw


def test_run_analysis_parse_batch_sample_selector():
    _, run_analysis = _scripts()
    with patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
        for raw, expected in PARSE_BATCH_SAMPLE_CASES.items():
            assert run_analysis.parse_batch_sample_selector(raw) == expected, raw


def test_run_analysis_parse_qualified_sample_selector():
    _, run_analysis = _scripts()
    with patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
        assert run_analysis.parse_qualified_sample_selector("1054-B") == (
            "TE-1054",
            "TE-1054-B",
        )
        assert run_analysis.parse_qualified_sample_selector("TE-1054") == ("", "TE-1054")
        assert run_analysis.parse_qualified_sample_selector("") == ("", "")


def test_plot_te_safe_selector_name():
    plot_te, _ = _scripts()
    assert plot_te.safe_selector_name("TE-1054-B") == "TE-1054-B"
    assert plot_te.safe_selector_name("a/b\\c:d e") == "a-b-c-d_e"
    long = plot_te.safe_selector_name("x" * 120)
    assert len(long) <= 96
    assert long != plot_te.safe_selector_name("x" * 119 + "y")


def test_xrd_safe_filename():
    from te_analysis.tools.xrd import safe_filename

    assert safe_filename("TE-1054/B:raw") == "TE-1054_B_raw"
    assert len(safe_filename("z" * 140)) <= 96
