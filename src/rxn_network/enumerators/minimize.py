from typing import List
from itertools import chain, combinations, compress, groupby, product
from math import comb
import numpy as np
from pymatgen.analysis.phase_diagram import PhaseDiagram, GrandPotentialPhaseDiagram
from pymatgen.analysis.interface_reactions import InterfacialReactivity

from rxn_network.core import Enumerator, Reaction
from rxn_network.reactions import ComputedReaction
from rxn_network.enumerators.utils import (
    get_total_chemsys,
    group_by_chemsys,
    filter_entries_by_chemsys
)


class MinimizeGibbsEnumerator(Enumerator):
    """
    Enumerator for finding all reactions between two reactants (+ optional open
    element) that are predicted by thermodynamics, i.e., they appear when taking the
    convex hull along a straight line connecting any two phases in G-x
    phase space.
    """

    def __init__(self):
        pass

    def enumerate(self, entries):
        combos = list(combinations(entries, 2))
        combos_dict = group_by_chemsys(combos)

        rxns = []
        for chemsys, combos in combos_dict.items():
            chemsys_entries = filter_entries_by_chemsys(entries, chemsys)
            pd = PhaseDiagram(chemsys_entries)
            for r1, r2 in combos:
                rxn = self._react_interface(r1, r2, pd)
                rxns.append(rxn)

        return rxns

    def estimate_num_reactions(self, entries) -> int:
        return comb(len(entries), 2)

    @staticmethod
    def _react_interface(r1, r2, pd, grand_pd=None):
        if grand_pd:
            interface = InterfacialReactivity(
                r1,
                r2,
                grand_pd,
                norm=False,
                include_no_mixing_energy=False,
                pd_non_grand=pd,
                use_hull_energy=True,
            )
        else:
            interface = InterfacialReactivity(
                r1,
                r2,
                pd,
                norm=False,
                include_no_mixing_energy=False,
                pd_non_grand=None,
                use_hull_energy=True,
            )

        entries = pd.all_entries
        rxns = [
            get_computed_rxn(rxn, entries, num_entries)
            for _, _, _, rxn, _ in interface.get_kinks()
        ]

        return rxns

    @staticmethod
    def _get_entry_by_comp(comp, entries):
        possible_entries = filter(
            lambda x: x.composition.reduced_composition == comp, entries
        )
        return sorted(possible_entries, key=lambda x: x.energy_per_atom)[0]

    @staticmethod
    def _get_computed_rxn(rxn, entries):
        reactants = [
            r.reduced_composition
            for r in rxn.reactants
            if not np.isclose(rxn.get_coeff(r), 0)
        ]
        products = [
            p.reduced_composition
            for p in rxn.products
            if not np.isclose(rxn.get_coeff(p), 0)
        ]
        reactant_entries = [get_entry_by_comp(r, entries) for r in reactants]
        product_entries = [get_entry_by_comp(p, entries) for p in products]

        return ComputedReaction(reactant_entries, product_entries)


class MinimizeOpenGibbsEnumerator(MinimizeGibbsEnumerator):
    def __init__(self, open_entries):
        super().__init__()
        self.open_entries = open_entries

    def enumerate(self):
        pass

