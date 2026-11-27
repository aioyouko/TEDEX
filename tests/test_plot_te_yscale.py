"""TE axis scales, signed values, and CLI propagation through both plot routes."""

import io
import runpy
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import ticker
import numpy as np
import pandas as pd

from _helpers import REPO_ROOT, load_script
from te_analysis.tools import plot as plotting
from te_analysis.tools import te_plotting
from te_analysis.tools.te_plotting import locate


def _sample_data():
    return pd.DataFrame({
        "Temperature": [300, 400, 500, 600, 700],
        "Seebeck": np.array([1, 10, 100, 1000, 10000]) * 1e-6,
        "Conductivity": [100, 1000, 10000, 100000, 1000000],
        "Power_Factor": [0.0001, 0.001, 0.01, 0.1, 1],
        "Thermal_Conductivity": [0.1, 0.2, 0.4, 0.8, 1.6],
        "Lattice_Thermal_Conductivity": [0.05, 0.1, 0.2, 0.4, 0.8],
        "ZT": [0.001, 0.01, 0.1, 1, 10],
    })


def test_yscale_cli_aliases_and_default():
    script = load_script("scripts/plotting/plot_te.py", "plot_te_yscale_cli")
    with patch.object(sys, "argv", ["plot_te.py", "--zt"]):
        assert script.parse_args().yscale == "linear"
    for option in ("--yscale", "--yscal"):
        for scale in ("linear", "log", "symlog"):
            with patch.object(sys, "argv", ["plot_te.py", "--zt", option, scale]):
                assert script.parse_args().yscale == scale
        with patch.object(sys, "argv", ["plot_te.py", option, "invalid"]), redirect_stderr(io.StringIO()):
            try:
                script.parse_args()
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError("Unsupported scale was accepted")


def test_log_axis_decades_units_and_limits():
    samples = {"demo": _sample_data()}
    fig, ax = plotting.plot_single_property(
        samples, "conductivity", yscale="log", ylim=(1, 10000),
        xlim=(300, 700), legend="inside", legend_columns=2,
    )
    try:
        fig.canvas.draw()
        assert ax.get_yscale() == "log"
        assert ax.get_xscale() == "linear"
        assert ax.get_ylim() == (1, 10000)
        assert ax.get_xlim() == (300, 700)
        assert isinstance(ax.yaxis.get_minor_locator(), ticker.LogLocator)
        # Conductivity still uses S/cm, and successive decades are equally spaced.
        values = ax.lines[0].get_ydata()
        np.testing.assert_allclose(values, [1, 10, 100, 1000, 10000])
        positions = ax.get_yaxis_transform().transform(np.column_stack([np.zeros(5), values]))[:, 1]
        np.testing.assert_allclose(np.diff(positions), np.repeat(np.diff(positions)[0], 4))
        assert ax.get_legend() is not None
    finally:
        plt.close(fig)


def test_symlog_keeps_negative_zero_positive_values_and_native_ticks():
    data = _sample_data()
    values = np.array([-1000, -1, 0, 1, 1000])
    data["Seebeck"] = values * 1e-6
    fig, ax = plotting.plot_single_property(
        {"demo": data}, "seebeck", yscale="symlog", ylim=(-2000, 2000),
    )
    try:
        fig.canvas.draw()
        assert ax.get_yscale() == "symlog"
        assert isinstance(ax.yaxis.get_minor_locator(), ticker.SymmetricalLogLocator)
        np.testing.assert_allclose(ax.lines[0].get_ydata(), values)
        positions = ax.yaxis.get_transform().transform(values)
        assert np.isfinite(positions).all()
        assert (np.diff(positions) > 0).all()
        np.testing.assert_allclose(positions, -positions[::-1])
        near_zero = ax.yaxis.get_transform().transform([-1, 0, 1])
        np.testing.assert_allclose(np.diff(near_zero), np.repeat(np.diff(near_zero)[0], 2))
        # Applying house formatting again must not replace symlog minor ticks
        # with a linear locator when the axis already uses the requested scale.
        plotting.plot_property_vs_temperature(ax, {"demo": data}, "seebeck", yscale="symlog")
        fig.canvas.draw()
        assert isinstance(ax.yaxis.get_minor_locator(), ticker.SymmetricalLogLocator)
    finally:
        plt.close(fig)


def test_cli_single_and_combined_scales_for_batch_and_csv_inputs():
    save_figure = plotting.save_figure
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = _sample_data()
        csv_path = root / "demo.csv"
        data.to_csv(csv_path, index=False)
        for selector in ("TE-1048", str(csv_path)):
            for option, scale in (("--yscal", "log"), ("--yscale", "symlog")):
                rendered = []

                def capture_figure(fig, *args, **kwargs):
                    fig.canvas.draw()
                    rendered.append([ax.get_yscale() for ax in fig.axes])
                    return save_figure(fig, *args, **kwargs)

                argv = ["plot_te.py", selector, "--zt", "--plot-mode", "both",
                        option, scale, "--no-show", "--no-data-figures"]
                output = io.StringIO()
                with patch.object(sys, "argv", argv), \
                     patch.object(te_plotting, "ALL_LAB_BATCHES", {"TE-1048": {}}), \
                     patch.object(te_plotting, "load_batch_processed_data", return_value={"demo": data}), \
                     patch.object(locate, "TE_FIGURE_DIR", root / "figures"), \
                     patch.object(plotting, "save_figure", side_effect=capture_figure), \
                     redirect_stdout(output):
                    runpy.run_path(str(REPO_ROOT / "scripts/plotting/plot_te.py"), run_name="__main__")
                assert "❌" not in output.getvalue(), output.getvalue()
                assert rendered == [[scale] * 6, [scale]], (selector, scale, rendered)
        assert len(list((root / "figures").rglob("*.svg"))) >= 4
