"""Characterization tests for batch/sample selector handling.

Expected values were captured from the code as of v1.4.1 (2026-07-01).
They pin CURRENT behavior so refactors can be verified not to change it.
Note the intentional differences between functions, e.g. plot_te expands
"CHY-1054B" to "CHY-1054-B" while run_analysis/plot_xrd_data do not.
"""

from __future__ import annotations

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
    "CHY-1054": "CHY-1054",
    "1054": "CHY-1054",
    "Batch-1054": "CHY-1054",
    "1054-B": "CHY-1054-B",
    "CHY-1054B": "CHY-1054B",
    "1054B": "CHY-1054B",
    "CHY-1054-B": "CHY-1054-B",
    "CHY-1054/B": "CHY-1054/B",
    "CHY-1054:B": "CHY-1054:B",
    "weird name": "weird name",
    "": "",
}

PLOT_TE_NORMALIZE_CASES = dict(
    NORMALIZE_BATCH_ID_CASES,
    **{"CHY-1054B": "CHY-1054-B", "1054B": "CHY-1054-B"},
)

PARSE_BATCH_SAMPLE_CASES = {
    "CHY-1054": ("CHY-1054", None),
    "1054": ("CHY-1054", None),
    "Batch-1054": ("CHY-1054", None),
    "1054-B": ("CHY-1054", "CHY-1054-B"),
    "CHY-1054B": ("CHY-1054B", None),
    "1054B": ("CHY-1054B", None),
    "CHY-1054-B": ("CHY-1054", "CHY-1054-B"),
    "CHY-1054/B": ("CHY-1054", "CHY-1054/B"),
    "CHY-1054:B": ("CHY-1054", "CHY-1054:B"),
    "weird name": ("weird name", None),
    "": ("", None),
}


def test_plot_te_normalize_selector():
    plot_te, _ = _scripts()
    for raw, expected in PLOT_TE_NORMALIZE_CASES.items():
        assert plot_te.normalize_selector(raw) == expected, raw


def test_run_analysis_normalize_batch_id():
    _, run_analysis = _scripts()
    for raw, expected in NORMALIZE_BATCH_ID_CASES.items():
        assert run_analysis.normalize_batch_id(raw) == expected, raw


def test_xrd_normalize_batch_selector():
    from te_analysis.tools import plot_xrd_data

    for raw, expected in NORMALIZE_BATCH_ID_CASES.items():
        assert plot_xrd_data.normalize_batch_selector(raw) == expected, raw


def test_run_analysis_parse_batch_sample_selector():
    _, run_analysis = _scripts()
    for raw, expected in PARSE_BATCH_SAMPLE_CASES.items():
        assert run_analysis.parse_batch_sample_selector(raw) == expected, raw


def test_run_analysis_parse_qualified_sample_selector():
    _, run_analysis = _scripts()
    assert run_analysis.parse_qualified_sample_selector("1054-B") == (
        "CHY-1054",
        "CHY-1054-B",
    )
    assert run_analysis.parse_qualified_sample_selector("CHY-1054") == ("", "CHY-1054")
    assert run_analysis.parse_qualified_sample_selector("") == ("", "")


def test_plot_te_safe_selector_name():
    plot_te, _ = _scripts()
    assert plot_te.safe_selector_name("CHY-1054-B") == "CHY-1054-B"
    assert plot_te.safe_selector_name("a/b\\c:d e") == "a-b-c-d_e"
    long = plot_te.safe_selector_name("x" * 120)
    assert long == "x" * 87 + "_ceb28216"


def test_xrd_safe_filename():
    from te_analysis.tools import plot_xrd_data

    assert plot_xrd_data.safe_filename("CHY-1054-B") == "CHY-1054-B"
    assert plot_xrd_data.safe_filename("a/b\\c:d e") == "a_b_c_d_e"
    assert plot_xrd_data.safe_filename("x" * 120) == "x" * 87 + "_ceb28216"
