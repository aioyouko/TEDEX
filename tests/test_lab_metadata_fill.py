"""Tests for `sync workbook` and `sync fill` on synthetic data.

The workbook mimics "NU Lab samples lists.xlsx": one sheet per batch, one
block per sample, column G holding molar mass, Cp, and atoms per formula unit
(newer sheets) or molar mass, atoms, Cp (older sheets). Nothing here reads
the real lab files.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from _helpers import REPO_ROOT, run_cli

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

R = 8.314462618
BATCH = "CHY-9001"


def dulong_petit(atoms: float, molar_mass: float) -> float:
    return 3 * R * atoms / molar_mass


def block(sample_id, composition, elements, g_values):
    """Rows for one sample block; elements are (symbol, ratio), g_values fill column G from the composition row."""
    rows = [("Sample ID", None, "weight (g)", "elements", "Mole ratio", None, None), (sample_id, None, 5.0)]
    for index, (symbol, ratio) in enumerate(elements):
        g = g_values[index] if index < len(g_values) else None
        rows.append((composition if index == 0 else None, None, 0.5, symbol, ratio, 100.0, g))
    rows.append(())
    return rows


def sheet_rows():
    cp_a = dulong_petit(4, 400.0)
    cp_c = dulong_petit(5, 500.0)
    rows = []
    rows += block("CHY-9000-0", "Ref", [("Cu", 1), ("Te", 2)], [300.0, 0.2, 3])  # another batch
    rows += block(f"{BATCH}-A", "CuInTe2", [("Cu", 1), ("In", 1), ("Te", 2)], [400.0, cp_a, 4])
    rows += block(  # six elements, Cp 20% off Dulong-Petit
        f"{BATCH}-B", "CuIn0.5Ga0.5Te2-0.4(Zn1)Se",
        [("Cu", 1), ("In", 0.5), ("Ga", 0.5), ("Te", 2), ("Se", 0.4), ("Zn", 0.4)],
        [467.36, 0.30, 4.8],
    )
    rows += block(f"{BATCH}-C", "AgInTe2", [("Ag", 1), ("In", 1), ("Te", 2)], [500.0, 5, cp_c])  # old G order
    rows += [("Sample ID", None, "weight (g)"), (None, None, 4.9), ("Orphan", None, 0.5, "Cu", 1, 63.5, 900.0)]
    return rows, cp_a, cp_c


def write_workbook(path: Path) -> None:
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.title = "Notes"
    sheet = workbook.create_sheet(BATCH)
    for row in sheet_rows()[0]:
        sheet.append(list(row))
    workbook.save(path)


def write_metadata(directory: Path, samples_extra=None) -> list[str]:
    from scripts.sync_lab_markdown import render_markdown

    samples = []
    for suffix in "ABC":
        record = {
            "sample_id": f"{BATCH}-{suffix}",
            "batch_id": BATCH,
            "sample_name": suffix,  # raw-scan placeholder
            "density": None,
            "cp_value": None,
            "sample_composition": "",
            "notes": "",
        }
        record.update((samples_extra or {}).get(suffix, {}))
        samples.append(record)
    batches = [{"batch_id": BATCH, "matrix_composition": "", "notes": ""}]
    (directory / "samples.json").write_text(json.dumps(samples, indent=4), encoding="utf-8")
    (directory / "batches.json").write_text(json.dumps(batches, indent=4), encoding="utf-8")
    (directory / "lab_metadata.md").write_text(render_markdown(batches, samples), encoding="utf-8")
    return [
        "--markdown", str(directory / "lab_metadata.md"),
        "--batches-json", str(directory / "batches.json"),
        "--samples-json", str(directory / "samples.json"),
    ]


def samples_by_id(directory: Path) -> dict:
    records = json.loads((directory / "samples.json").read_text(encoding="utf-8"))
    return {record["sample_id"]: record for record in records}


# --- workbook parsing ---------------------------------------------------------


def test_parse_rows_reads_both_column_g_orders():
    from te_analysis.tools.lab_workbook import parse_rows

    rows, cp_a, cp_c = sheet_rows()
    samples, skipped, unlabeled = parse_rows(rows, BATCH)

    assert [s.sample_id for s in samples] == [f"{BATCH}-A", f"{BATCH}-B", f"{BATCH}-C"]
    assert skipped == ["CHY-9000-0"]
    assert len(unlabeled) == 1
    a, b, c = samples
    assert (a.composition, a.cp_value, a.molar_mass, a.atoms_per_formula) == ("CuInTe2", cp_a, 400.0, 4)
    assert a.warnings == []
    assert c.cp_value == cp_c and c.atoms_per_formula == 5  # old order: M, atoms, Cp
    assert b.composition == "CuIn0.5Ga0.5Te2-0.4(Zn1)Se" and b.cp_value == 0.30
    assert any("Dulong-Petit" in warning for warning in b.warnings)


def test_parse_rows_refuses_ambiguous_cp():
    from te_analysis.tools.lab_workbook import parse_rows

    rows = block(f"{BATCH}-A", "X", [("Cu", 1), ("Te", 2)], [0.3, 0.4])
    (sample,), _, _ = parse_rows(rows, BATCH)
    assert sample.cp_value is None
    assert any("Cp not read" in warning for warning in sample.warnings)


# --- sync workbook --------------------------------------------------------------


def test_workbook_fills_cp_and_composition_and_respects_conflicts():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        workbook = tmp / "lab.xlsx"
        write_workbook(workbook)
        _, cp_a, cp_c = sheet_rows()
        paths = write_metadata(
            tmp,
            {
                "B": {"sample_composition": "something else"},
                "C": {"cp_value": round(cp_c, 4)},  # typed with fewer decimals: a match
            },
        )
        args = ["sync", "workbook", BATCH, "--workbook", str(workbook), *paths]

        conflict = run_cli(args)
        assert conflict.returncode == 1, conflict.stderr[-1500:]
        assert "Nothing was written" in conflict.stderr
        assert samples_by_id(tmp)[f"{BATCH}-A"]["cp_value"] is None  # all or nothing

        applied = run_cli(args + ["--overwrite"])
        assert applied.returncode == 0, applied.stderr[-1500:]
        records = samples_by_id(tmp)
        assert records[f"{BATCH}-A"]["cp_value"] == round(cp_a, 9)
        assert records[f"{BATCH}-A"]["sample_composition"] == "CuInTe2"
        assert records[f"{BATCH}-B"]["sample_composition"] == "CuIn0.5Ga0.5Te2-0.4(Zn1)Se"
        assert records[f"{BATCH}-C"]["cp_value"] == round(cp_c, 4)  # rounded match kept
        assert "Skipped sample IDs from other batches: CHY-9000-0" in applied.stdout
        assert "empty sample-ID cell" in applied.stderr
        assert "| sample_composition | CuInTe2 |" in (tmp / "lab_metadata.md").read_text(encoding="utf-8")

        again = run_cli(args)
        assert again.returncode == 0 and "Nothing to change" in again.stdout


def test_workbook_reports_batch_without_samples():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        workbook = tmp / "lab.xlsx"
        write_workbook(workbook)
        paths = write_metadata(tmp)
        result = run_cli(["sync", "workbook", "CHY-9002", "--workbook", str(workbook), *paths])
        assert result.returncode == 2
        assert "no sheet named 'CHY-9002'" in result.stderr


# --- sync fill ------------------------------------------------------------------


def test_fill_writes_values_in_sample_order():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)

        mismatch = run_cli(["sync", "fill", BATCH, "density", "5.9", "6.0", *paths])
        assert mismatch.returncode == 2 and "got 2 value(s) for 3 sample(s)" in mismatch.stderr

        result = run_cli(["sync", "fill", BATCH, "density", "5.91", "5.92", "5.93", *paths])
        assert result.returncode == 0, result.stderr[-1500:]
        records = samples_by_id(tmp)
        assert [records[f"{BATCH}-{s}"]["density"] for s in "ABC"] == [5.91, 5.92, 5.93]
        markdown = (tmp / "lab_metadata.md").read_text(encoding="utf-8")
        section_b = markdown.split(f"### Sample {BATCH}-B")[1].split("### Sample")[0]
        assert "| density | 5.92 |" in section_b

        conflict = run_cli(["sync", "fill", BATCH, "density", "6.5", "--samples", "B", *paths])
        assert conflict.returncode == 1
        assert samples_by_id(tmp)[f"{BATCH}-B"]["density"] == 5.92

        overwrite = run_cli(["sync", "fill", BATCH, "density", "6.5", "--samples", "B", "--overwrite", *paths])
        assert overwrite.returncode == 0
        assert samples_by_id(tmp)[f"{BATCH}-B"]["density"] == 6.5


def test_fill_treats_placeholder_label_as_empty_and_keeps_markdown_edits():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        markdown_path = tmp / "lab_metadata.md"
        text = markdown_path.read_text(encoding="utf-8")
        section_a = text.index(f"### Sample {BATCH}-A")
        notes_at = text.index("| notes |  |", section_a)
        markdown_path.write_text(
            text[:notes_at] + "| notes | typed by hand |" + text[notes_at + len("| notes |  |"):],
            encoding="utf-8",
        )

        result = run_cli(["sync", "fill", BATCH, "sample_name", "Na_dope", "--samples", "A", *paths])
        assert result.returncode == 0, result.stderr[-1500:]
        record = samples_by_id(tmp)[f"{BATCH}-A"]
        assert record["sample_name"] == "Na_dope"
        assert record["notes"] == "typed by hand"  # the Markdown edit was imported, not lost
        assert "| notes | typed by hand |" in markdown_path.read_text(encoding="utf-8")


def test_fill_rejects_bad_numbers_and_unknown_fields():
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        paths = write_metadata(tmp)
        bad_number = run_cli(["sync", "fill", BATCH, "density", "5.9x", "1", "2", *paths])
        assert bad_number.returncode == 2 and "expects a number" in bad_number.stderr
        bad_field = run_cli(["sync", "fill", BATCH, "zem", "a", "b", "c", *paths])
        assert bad_field.returncode == 2
