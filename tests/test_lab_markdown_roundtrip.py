"""Round-trip tests for the lab metadata Markdown sync.

The invariant: export JSON records to Markdown, parse the Markdown back,
merge against the originals — every field value must survive unchanged.
Layout may evolve; this property must not.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _helpers import load_script

_mod = None


def _sync():
    global _mod
    if _mod is None:
        _mod = load_script("scripts/sync_lab_markdown.py", "sync_lab_markdown_under_test")
    return _mod


BATCHES = [
    {
        "batch_id": "CHY-1048",
        "project": "PbSe optimization",
        "matrix_composition": "PbSe",
        "pristine_composition": "PbSe",
        "material_family": "lead chalcogenide",
        "notes": "baseline | with pipe",
    },
    {
        "batch_id": "CHY-1056",
        "project": "",
        "matrix_composition": "Cu2Se",
        "pristine_composition": "",
        "material_family": "",
        "notes": "multi\nline note",
    },
]

SAMPLES = [
    {
        "sample_id": "CHY-1048-A",
        "batch_id": "CHY-1048",
        "sample_name": "A",
        "zem": "data/raw/CHY-1048/CHY-1048-A_ZEM.txt",
        "lfa": "data/raw/CHY-1048/CHY-1048-A_LFA.csv",
        "processed_file": "data/processed/CHY-1048-processed/CHY-1048-A.csv",
        "processed_exists": True,
        "density": 8.27,
        "cp_value": 0.339,
        "matrix_composition": "PbSe",
        "pristine_composition": "PbSe",
        "sample_composition": "Pb0.98Na0.02Se",
        "optimization_type": "doping",
        "modifier_species": "Na",
        "modifier_element": "Na",
        "modifier_elements": ["Na"],
        "modifier_amount": 0.02,
        "modifier_unit": "at%",
        "modifier_site": "Pb",
        "phase_type": "single",
        "synthesis_route": "melt + SPS",
        "annealing_condition": "823 K / 72 h",
        "notes": "",
    },
    {
        "sample_id": "CHY-1056-B",
        "batch_id": "CHY-1056",
        "sample_name": "B",
        "zem": "",
        "lfa": "data/raw/CHY-1056/CHY-1056-B_LFA.csv",
        "processed_file": "data/processed/CHY-1056-processed/CHY-1056-B.csv",
        "processed_exists": False,
        "density": None,
        "cp_value": None,
        "matrix_composition": "",
        "pristine_composition": "",
        "sample_composition": "",
        "optimization_type": "",
        "modifier_species": "",
        "modifier_element": "",
        "modifier_elements": [],
        "modifier_amount": [0.01, 0.02],
        "modifier_unit": "",
        "modifier_site": "",
        "phase_type": "",
        "synthesis_route": "",
        "annealing_condition": "",
        "notes": "",
    },
]


def _roundtrip(batches, samples):
    mod = _sync()
    text = mod.render_markdown(batches, samples)
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "lab_metadata.md"
        md.write_text(text, encoding="utf-8")
        parsed_batches, parsed_samples = mod.parse_markdown(md, batches, samples)
    merged_batches = mod.merge_records(parsed_batches, batches, "batch_id", mod.BATCH_FIELDS)
    merged_samples = mod.merge_records(parsed_samples, samples, "sample_id", mod.SAMPLE_FIELDS)
    return merged_batches, merged_samples


def _by_id(records, key):
    return {r[key]: r for r in records}


def test_roundtrip_preserves_all_fields():
    merged_batches, merged_samples = _roundtrip(BATCHES, SAMPLES)
    got_b = _by_id(merged_batches, "batch_id")
    for original in BATCHES:
        for field, value in original.items():
            assert got_b[original["batch_id"]][field] == value, (
                f"batch {original['batch_id']}.{field}"
            )
    got_s = _by_id(merged_samples, "sample_id")
    for original in SAMPLES:
        for field, value in original.items():
            assert got_s[original["sample_id"]][field] == value, (
                f"sample {original['sample_id']}.{field}"
            )


def test_roundtrip_survives_stripped_markers():
    """Some editors delete HTML comments; headings must be enough."""
    mod = _sync()
    text = mod.render_markdown(BATCHES, SAMPLES)
    text = "\n".join(l for l in text.splitlines() if not l.startswith("<!--")) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "lab_metadata.md"
        md.write_text(text, encoding="utf-8")
        parsed_batches, parsed_samples = mod.parse_markdown(md, BATCHES, SAMPLES)
    assert {b["batch_id"] for b in parsed_batches} == {"CHY-1048", "CHY-1056"}
    assert {s["sample_id"] for s in parsed_samples} == {"CHY-1048-A", "CHY-1056-B"}


def test_typed_field_parsing():
    mod = _sync()
    assert mod.parse_value("density", " 8.27 ") == 8.27
    assert mod.parse_value("density", "") is None
    assert mod.parse_value("processed_exists", "true") is True
    assert mod.parse_value("processed_exists", "") is False
    assert mod.parse_value("modifier_elements", "Na, Cl") == ["Na", "Cl"]
    assert mod.parse_value("modifier_elements", "") == []
    assert mod.parse_value("modifier_amount", "0.01, 0.02") == [0.01, 0.02]
    assert mod.parse_value("modifier_amount", "0.02") == 0.02
    assert mod.parse_value("modifier_amount", "null") is None


def test_deleted_section_is_kept_not_dropped():
    """Accidentally deleting a sample section must not lose the record."""
    mod = _sync()
    text = mod.render_markdown(BATCHES, SAMPLES)
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if "Sample CHY-1056-B" in l) - 1
    end = next(
        (i for i in range(start + 2, len(lines)) if lines[i].startswith(("###", "<!--"))),
        len(lines),
    )
    mangled = "\n".join(lines[:start] + lines[end:]) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "lab_metadata.md"
        md.write_text(mangled, encoding="utf-8")
        _, parsed_samples = mod.parse_markdown(md, BATCHES, SAMPLES)
    merged = mod.merge_records(parsed_samples, SAMPLES, "sample_id", mod.SAMPLE_FIELDS)
    assert {s["sample_id"] for s in merged} == {"CHY-1048-A", "CHY-1056-B"}
    kept = _by_id(merged, "sample_id")["CHY-1056-B"]
    assert kept["modifier_amount"] == [0.01, 0.02]


def test_structural_fields_stay_out_of_markdown():
    mod = _sync()
    text = mod.render_markdown(BATCHES, SAMPLES)
    for field in mod.STRUCTURAL_SAMPLE_FIELDS:
        assert f"| {field} |" not in text, f"{field} should not be an editable row"


def test_bad_number_raises_clear_error():
    mod = _sync()
    try:
        mod.parse_value("density", "heavy")
    except mod.MarkdownSyncError as exc:
        assert "density" in str(exc)
    else:
        raise AssertionError("expected MarkdownSyncError")
