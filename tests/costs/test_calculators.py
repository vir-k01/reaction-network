""" Tests for ChempotDistanceCalculator """
from pathlib import Path

import numpy as np
import pytest
from monty.serialization import loadfn

from rxn_network.costs.calculators import ChempotDistanceCalculator
from rxn_network.entries.entry_set import GibbsEntrySet
from rxn_network.reactions.computed import ComputedReaction
from rxn_network.reactions.hull import InterfaceReactionHull
from rxn_network.thermo.chempot_diagram import ChemicalPotentialDiagram

TEST_FILES_PATH = Path(__file__).parent.parent / "test_files"

cpd_expected_values = {
    "0.5 Y2O3 + 0.5 Mn2O3 -> YMnO3": {
        "sum": 0.480008216,
        "max": 0.480008216,
        "mean": 0.240004108,
    },
    "2 YClO + 2 NaMnO2 + 0.5 O2 -> Y2Mn2O7 + 2 NaCl": {
        "sum": 1.369790046,
        "max": 1.369790045,
        "mean": 0.195684292,
    },
}


@pytest.fixture(
    params=[
        [["Y2O3", "Mn2O3"], ["YMnO3"]],
        [["YOCl", "NaMnO2", "O2"], ["Y2Mn2O7", "NaCl"]],
    ],
    scope="module",
)
def rxn(entries, request):
    reactants = request.param[0]
    products = request.param[1]
    reactant_entries = [entries.get_min_entry_by_formula(r) for r in reactants]
    product_entries = [entries.get_min_entry_by_formula(p) for p in products]
    return ComputedReaction.balance(reactant_entries, product_entries)


@pytest.fixture
def rxns(entries):
    return [
        ComputedReaction.balance(
            [entries.get_min_entry_by_formula(r) for r in reactants],
            [entries.get_min_entry_by_formula(p) for p in products],
        )
        for reactants, products in [
            (["Y2O3", "Mn2O3"], ["YMnO3"]),
            (["YOCl", "NaMnO2", "O2"], ["Y2Mn2O7", "NaCl"]),
        ]
    ]


@pytest.fixture(params=["sum", "max", "mean"], scope="module")
def mu_func(request):
    return request.param


@pytest.fixture
def cpd(entries):
    return ChemicalPotentialDiagram(entries)


@pytest.fixture
def cpd_calculator(cpd, mu_func):
    return ChempotDistanceCalculator(cpd=cpd, mu_func=mu_func)


@pytest.fixture
def primary_selectivity_calculator(irh_batio):
    return PrimarySelectivityCalculator(irh_batio)


@pytest.fixture
def secondary_selectivity_calculator(irh_batio):
    return SecondarySelectivityCalculator(irh_batio)


@pytest.fixture(scope="module")
def stable_rxn(bao_tio2_rxns):
    for r in bao_tio2_rxns:
        if str(r) == "TiO2 + 2 BaO -> Ba2TiO4":
            return r


@pytest.fixture(scope="module")
def unstable_rxn(bao_tio2_rxns):
    for r in bao_tio2_rxns:
        if str(r) == "TiO2 + 0.9 BaO -> 0.1 Ti10O11 + 0.9 BaO2":
            return r


def test_cpd_calculate(calculator, rxn):
    actual_cost = calculator.calculate(rxn)
    expected_cost = cpd_expected_values[str(rxn)][calculator.mu_func.__name__]

    assert actual_cost == pytest.approx(expected_cost)


def test_cpd_decorate(calculator, rxn):
    rxn_missing_data = rxn.copy()
    rxn_missing_data.data = None

    rxn_dec = calculator.decorate(rxn)
    rxn_missing_data_dec = calculator.decorate(rxn_missing_data)

    actual_cost = rxn_dec.data[calculator.name]
    expected_cost = cpd_expected_values[str(rxn)][calculator.mu_func.__name__]

    assert type(rxn_dec) == ComputedReaction
    assert actual_cost == pytest.approx(expected_cost)
    assert rxn_missing_data_dec.data[calculator.name] == actual_cost


def test_cpd_calculate_many(calculator, rxns):
    actual_costs = calculator.calculate_many(rxns)
    expected_costs = [calculator.calculate(rxn) for rxn in rxns]

    assert actual_costs == pytest.approx(expected_costs)


def test_cpd_decorate_many(calculator, rxns):
    rxns_missing_data = [rxn.copy() for rxn in rxns]
    for rxn in rxns_missing_data:
        rxn.data = None

    rxns_dec = calculator.decorate_many(rxns)
    rxns_missing_data_dec = calculator.decorate_many(rxns_missing_data)

    actual_costs = [rxn.data[calculator.name] for rxn in rxns_dec]
    expected_costs = [calculator.calculate(rxn) for rxn in rxns]

    assert type(rxns_dec) == list
    assert actual_costs == pytest.approx(expected_costs)
    assert rxns_missing_data_dec == rxns_dec


def test_cpd_calculator_from_entries(entries, mu_func, rxn):
    calc = ChempotDistanceCalculator.from_entries(entries=entries, mu_func=mu_func)

    actual_cost = calc.calculate(rxn)
    expected_cost = cpd_expected_values[str(rxn)][calc.mu_func.__name__]

    assert type(calc) == ChempotDistanceCalculator
    assert actual_cost == pytest.approx(expected_cost)


def test_primary_selectivity_calculate(primary_selectivity_calculator, rxn):
    actual_cost = primary_selectivity_calculator.calculate(rxn)
    expected_cost = 0.0

    assert actual_cost == pytest.approx(expected_cost)


def test_secondary_selectivity_calculate(secondary_selectivity_calculator, rxn):
    actual_cost = secondary_selectivity_calculator.calculate(rxn)
    expected_cost = 0.0

    assert actual_cost == pytest.approx(expected_cost)
