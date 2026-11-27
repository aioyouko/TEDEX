"""Local legend labels must work with paths, batches, and sample selectors."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from te_analysis.tools.te_plotting import locate


@contextmanager
def sample_batch(labels=None):
    with TemporaryDirectory() as tmp:
        directory = Path(tmp) / "TE-9999-processed"
        directory.mkdir()
        samples = {}
        for i, suffix in enumerate("ABC"):
            sample_id = f"TE-9999-{suffix}"
            csv_path = directory / f"{sample_id}.csv"
            csv_path.write_text(f"Temperature,Seebeck\n300,{i + 1}e-4\n")
            name = f"Metadata {suffix}"
            samples[name] = {
                "sample_id": sample_id,
                "sample_name": name,
                "processed_file": str(csv_path),
            }
        if labels is not None:
            (directory / "legend.txt").write_text(labels, encoding="utf-8")
        with patch.object(locate, "ALL_LAB_BATCHES", {"TE-9999": samples}), patch.object(
            locate, "get_processed_dir", return_value=str(directory)
        ), patch("te_analysis.tools.selectors._active_batch_prefix", return_value="TE"):
            yield directory


def test_local_legend_overrides_metadata_for_paths_and_batch_ids():
    with sample_batch("# labels\nLocal A\n\nLocal B\nLocal C\n") as directory:
        for selector in ("TE-9999", "9999", str(directory)):
            for include_batch in (False, True):
                data = locate.get_selected_processed_data([selector], include_batch)
                assert list(data) == ["Local A", "Local B", "Local C"]
                assert [df["Seebeck"].iloc[0] for df in data.values()] == [1e-4, 2e-4, 3e-4]
        assert list(locate.load_batch_processed_data("TE-9999")) == [
            "Local A", "Local B", "Local C"
        ]


def test_sample_subset_keeps_full_folder_label_order():
    with sample_batch("Local A\nLocal B\nLocal C\n") as directory:
        for selector in ("TE-9999-C", str(directory / "TE-9999-C.csv")):
            assert list(locate.get_selected_processed_data([selector])) == ["Local C"]
        data = locate.load_interbatch_processed_data(["TE-9999-C", "TE-9999-A"])
        assert list(data) == ["Local C", "Local A"]
        assert [df["Seebeck"].iloc[0] for df in data.values()] == [3e-4, 1e-4]


def test_missing_legend_uses_metadata():
    with sample_batch() as directory:
        for selector in ("TE-9999", str(directory)):
            assert list(locate.get_selected_processed_data([selector])) == [
                "Metadata A", "Metadata B", "Metadata C"
            ]
        assert list(locate.load_interbatch_processed_data(["TE-9999-B"])) == [
            "TE-9999/Metadata B"
        ]


def test_partial_legend_falls_back_only_for_unlabeled_samples():
    with sample_batch("Local A\n") as directory:
        for selector in ("TE-9999", str(directory)):
            assert list(locate.get_selected_processed_data([selector], include_batch=True)) == [
                "Local A", "TE-9999/Metadata B", "TE-9999/Metadata C"
            ]


def test_duplicate_local_labels_preserve_every_sample():
    with sample_batch("Same\nSame\nSame\n") as directory:
        for selector in ("TE-9999", str(directory)):
            data = locate.get_selected_processed_data([selector])
            assert list(data) == ["Same", "Same (TE-9999-B)", "Same (TE-9999-C)"]
            assert [df["Seebeck"].iloc[0] for df in data.values()] == [1e-4, 2e-4, 3e-4]
