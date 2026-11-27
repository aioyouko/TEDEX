"""Tests for concise plot-te property flags."""

import argparse

from te_analysis.tools.te_plotting.properties import (
    add_property_flag_arguments,
    get_property_flag_selection,
)


def parse_property_flags(*flags):
    parser = argparse.ArgumentParser()
    add_property_flag_arguments(parser)
    return get_property_flag_selection(parser.parse_args(flags))


def test_total_thermal_conductivity_shortcuts():
    for flag in ("--thermal", "--kappa", "--kt", "--ktot"):
        assert parse_property_flags(flag) == ["thermal_conductivity"]


def test_lattice_thermal_conductivity_shortcuts():
    for flag in ("--kl", "--kL", "--kappa-l", "--lattice"):
        assert parse_property_flags(flag) == ["lattice_thermal_conductivity"]


def test_electronic_thermal_conductivity_shortcuts():
    for flag in ("--ke", "--kE", "--kappa-e"):
        assert parse_property_flags(flag) == ["carrier_thermal_conductivity"]
