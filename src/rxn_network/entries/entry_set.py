"""
An entry set class for acquiring entries with Gibbs formation energies
"""
import collections
import logging
from typing import List, Optional, Union, Set, Dict
from copy import deepcopy
import warnings

from numpy.random import normal

from monty.json import MontyDecoder, MSONable
from pymatgen.entries.entry_tools import EntrySet
from pymatgen.analysis.phase_diagram import PhaseDiagram
from pymatgen.core import Composition
from pymatgen.entries.computed_entries import (
    ComputedEntry,
    ComputedStructureEntry,
    ConstantEnergyAdjustment,
)
from tqdm.auto import tqdm

from rxn_network.entries.gibbs import GibbsComputedEntry
from rxn_network.entries.nist import NISTReferenceEntry
from rxn_network.entries.barin import BarinReferenceEntry
from rxn_network.thermo.utils import expand_pd


class GibbsEntrySet(collections.abc.MutableSet, MSONable):
    """
    An extension of pymatgen's EntrySet to include factory methods for constructing
    GibbsComputedEntry objects from zero-temperature ComputedStructureEntry objects.
    """

    def __init__(self, entries: List[Union[GibbsComputedEntry, NISTReferenceEntry]]):
        """
        The supplied collection of entries will automatically be converted to a set of
        unique entries.

        Args:
            entries: A collection of entry objects that will make up the entry set.
        """
        self.entries = set(entries)

    def __contains__(self, item):
        return item in self.entries

    def __iter__(self):
        return self.entries.__iter__()

    def __len__(self):
        return len(self.entries)

    def add(self, element):
        """
        Add an entry.

        :param element: Entry
        """
        self.entries.add(element)

    def discard(self, element):
        """
        Discard an entry.

        :param element: Entry
        """
        self.entries.discard(element)

    def get_subset_in_chemsys(self, chemsys: List[str]):
        """
        Returns an EntrySet containing only the set of entries belonging to
        a particular chemical system (in this definition, it includes all sub
        systems). For example, if the entries are from the
        Li-Fe-P-O system, and chemsys=["Li", "O"], only the Li, O,
        and Li-O entries are returned.

        Args:
            chemsys: Chemical system specified as list of elements. E.g.,
                ["Li", "O"]

        Returns:
            EntrySet
        """
        chem_sys = set(chemsys)
        if not chem_sys.issubset(self.chemsys):
            raise ValueError("%s is not a subset of %s" % (chem_sys, self.chemsys))
        subset = set()
        for e in self.entries:
            elements = [sp.symbol for sp in e.composition.keys()]
            if chem_sys.issuperset(elements):
                subset.add(e)

        return GibbsEntrySet(subset)

    def filter_by_stability(
        self, e_above_hull: float, include_polymorphs: Optional[bool] = False
    ) -> "GibbsEntrySet":
        """
        Filter the entry set by a metastability (energy above hull) cutoff.

        Args:
            e_above_hull: Energy above hull, the cutoff describing the allowed
                metastability of the entries as determined via phase diagram
                construction.
            include_polymorphs: optional specification of whether to include
                metastable polymorphs. Defaults to False.

        Returns:
            A new GibbsEntrySet where the entries have been filtered by an energy
            cutoff (e_above_hull) via phase diagram construction.
        """
        pd_dict = expand_pd(self.entries)

        filtered_entries: Set[Union[GibbsComputedEntry, NISTReferenceEntry]] = set()
        all_comps: Dict[str, Union[GibbsComputedEntry, NISTReferenceEntry]] = dict()

        for chemsys, pd in pd_dict.items():
            for entry in pd.all_entries:
                if (
                    entry in filtered_entries
                    or pd.get_e_above_hull(entry) > e_above_hull
                ):
                    continue

                formula = entry.composition.reduced_formula
                if not include_polymorphs and (formula in all_comps):
                    if all_comps[formula].energy_per_atom < entry.energy_per_atom:
                        continue
                    filtered_entries.remove(all_comps[formula])

                all_comps[formula] = entry
                filtered_entries.add(entry)

        return self.__class__(list(filtered_entries))

    def build_indices(self):
        """
        Builds the indices for the entry set. This method is called whenever an entry is
        added/removed the entry set. The entry indices are useful for querying the entry
        set for specific entries.

        Note: this internally modifies the entries in the entry set by updating data for
        each entry to include the index.

        Returns:
            None
        """
        for idx, e in enumerate(self.entries_list):
            e.data.update({"idx": idx})

    def get_min_entry_by_formula(self, formula: str) -> ComputedEntry:
        """
        Helper method for acquiring the ground state entry with the specified formula.

        Args:
            formula: The chemical formula of the desired entry.

        Returns:
            Ground state computed entry object.
        """
        comp = Composition(formula).reduced_composition
        possible_entries = filter(
            lambda x: x.composition.reduced_composition == comp, self.entries
        )
        return sorted(possible_entries, key=lambda x: x.energy_per_atom)[0]

    def stabilize_entry(self, entry: ComputedEntry, tol: float = 1e-6) -> ComputedEntry:
        """
        Helper method for lowering the energy of a single entry such that it is just
        barely stable on the phase diagram.

        Args:
            entry: A computed entry object.
            tol: The numerical padding added to the energy correction to guarantee
                that it is determined to be stable during phase diagram construction.

        Returns:
            A new ComputedEntry with energy adjustment making it appear to be stable.
        """
        chemsys = [str(e) for e in entry.composition.elements]
        entries = self.get_subset_in_chemsys(chemsys)
        pd = PhaseDiagram(entries)
        e_above_hull = pd.get_e_above_hull(entry)

        if e_above_hull == 0.0:
            new_entry = entry
        else:
            e_adj = -1 * pd.get_e_above_hull(entry) * entry.composition.num_atoms - tol
            adjustment = ConstantEnergyAdjustment(
                value=e_adj,
                name="Stabilization Adjustment",
                description="Shifts energy so that " "entry is on the convex hull",
            )

            entry_dict = entry.as_dict()
            entry_dict["energy_adjustments"].append(adjustment)
            new_entry = MontyDecoder().process_decoded(entry_dict)

        return new_entry

    def get_entries_with_jitter(self):
        """ Returns a list of entries with jitter (random noise) added to their energies. """
        entries = deepcopy(self.entries_list)
        jitter = normal(size=len(entries))

        for idx, entry in enumerate(entries):
            if entry.is_element:
                continue
            adj = ConstantEnergyAdjustment(
                value=jitter[idx] * entry.correction_uncertainty,
                name="Random jitter",
                description="Randomly sampled noise to account for uncertainty in data",
            )
            entry.energy_adjustments.append(adj)

        return GibbsEntrySet(entries)

    def get_interpolated_entry(self, formula: str, tol=1e-6):
        """
        Helper method for interpolating an entry from the entry set.

        Args:
            formula: The chemical formula of the desired entry.

        Returns:
            An interpolated GibbsComputedEntry object.
        """
        comp = Composition(formula).reduced_composition
        pd_entries = self.get_subset_in_chemsys([str(e) for e in comp.elements])

        energy = PhaseDiagram(pd_entries).get_hull_energy(comp) + tol

        return ComputedEntry(comp, energy, entry_id="(Interpolated Entry)")

    @classmethod
    def from_pd(
        cls,
        pd: PhaseDiagram,
        temperature: float,
        include_nist_data=True,
        include_barin_data=False,
    ) -> "GibbsEntrySet":
        """
        Constructor method for building a GibbsEntrySet from an existing phase diagram.

        Args:
            pd: Phase Diagram object (pymatgen)
            temperature: Temperature [K] for determining Gibbs Free Energy of
                formation, dGf(T)
            include_nist_data: Whether to include NIST data in the entry set.
            include_barin_data: Whether to include Barin data in the entry set. Defaults
                to False. Warning: Barin data has not been verified. Use with caution.

        Returns:
            A GibbsEntrySet containing a collection of GibbsComputedEntry and
            experimental reference entry objects at the specified temperature.

        """
        gibbs_entries = []
        experimental_comps = []

        if include_barin_data:
            warnings.warn(
                "##### WARNING ##### \n\n"
                "Barin experimental data was acquired through optical "
                "recognition and has not been verified. Use at your own risk! \n\n"
                "##### WARNING #####"
            )

        for entry in pd.all_entries:
            experimental = False
            composition = entry.composition
            formula = composition.reduced_formula

            if composition.is_element and entry not in pd.el_refs.values():
                continue

            new_entries = []

            if (
                include_nist_data
                and formula in NISTReferenceEntry.REFERENCES
                and formula not in experimental_comps
            ):
                try:
                    e = NISTReferenceEntry(
                        composition=composition, temperature=temperature
                    )
                    new_entries.append(e)
                except ValueError as e:
                    logging.warning(
                        f"Compound {formula} is in NIST-JANAF tables but at different temperatures!: {e}"
                    )
                experimental = True

            if (
                include_barin_data
                and formula in BarinReferenceEntry.REFERENCES
                and formula not in experimental_comps
            ):
                try:
                    e = BarinReferenceEntry(
                        composition=composition, temperature=temperature
                    )
                    new_entries.append(e)
                except ValueError as e:
                    logging.warning(
                        f"Compound {formula} is in Barin tables but not at this temperature! {e}"
                    )
                experimental = True

            if experimental:
                experimental_comps.append(formula)

            structure = entry.structure
            formation_energy_per_atom = pd.get_form_energy_per_atom(entry)

            new_entries.append(
                GibbsComputedEntry.from_structure(
                    structure=structure,
                    formation_energy_per_atom=formation_energy_per_atom,
                    temperature=temperature,
                    energy_adjustments=None,
                    parameters=entry.parameters,
                    data=entry.data,
                    entry_id=entry.entry_id,
                )
            )

            gibbs_entries.extend(new_entries)

        return cls(gibbs_entries)

    @classmethod
    def from_entries(
        cls,
        entries: List[ComputedStructureEntry],
        temperature: float,
        include_nist_data=True,
        include_barin_data=False,
    ) -> "GibbsEntrySet":
        """
        Constructor method for initializing GibbsEntrySet from T = 0 K
        ComputedStructureEntry objects, as acquired from a thermochemical
        database e.g. The Materials Project. Automatically expands the phase
        diagram for large chemical systems (10 or more elements) to avoid limitations
        of Qhull.

        Args:
            entries: List of ComputedStructureEntry objects, as downloaded from The
                Materials Project API.
            temperature: Temperature for estimating Gibbs free energy of formation [K]

        Returns:
            A GibbsEntrySet containing a collection of GibbsComputedEntry and
            experimental reference entry objects at the specified temperature.
        """
        e_set = EntrySet(entries)
        new_entries: Set[GibbsComputedEntry] = set()

        if len(e_set.chemsys) <= 9:  # Qhull algorithm struggles beyond 9 dimensions
            pd = PhaseDiagram(e_set)
            return cls.from_pd(
                pd,
                temperature,
                include_nist_data=include_nist_data,
                include_barin_data=include_barin_data,
            )

        pd_dict = expand_pd(list(e_set))
        for chemsys, pd in tqdm(pd_dict.items()):
            gibbs_set = cls.from_pd(
                pd, temperature, include_nist_data, include_barin_data
            )
            new_entries.update(gibbs_set)

        return cls(list(new_entries))

    @property
    def entries_list(self) -> List[ComputedEntry]:
        """ Returns a list of all entries in the entry set. """
        return list(sorted(self.entries, key=lambda e: e.composition.reduced_formula))

    @property
    def chemsys(self) -> set:
        """
        Returns:
            set representing the chemical system, e.g., {"Li", "Fe", "P", "O"}
        """
        chemsys = set()
        for e in self.entries:
            chemsys.update([el.symbol for el in e.composition.keys()])
        return chemsys

    def copy(self) -> "GibbsEntrySet":
        """ Returns a copy of the entry set. """
        return GibbsEntrySet(entries=self.entries)
