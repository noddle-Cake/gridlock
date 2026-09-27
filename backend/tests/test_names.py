"""Title case for all-caps source names (project names, terminals, EIA-860M owners)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.names import title_case
from app.services.owners import CORPORATE_PARENT, canonical_utility


@pytest.mark.parametrize(("raw", "expected"), [
    ("GAINESVILLE #2 - BULL SHOALS 161 KV TRANSMISSION LINE, REBUILD",
     "Gainesville #2 - Bull Shoals 161 kV Transmission Line, Rebuild"),
    ("MCDONOUGH - OLA 230KV LINE", "McDonough - Ola 230kV Line"),
    ("LOOP IN 500/230KV (FPL)", "Loop In 500/230kV (FPL)"),
    ("LG&E AND KU", "LG&E and KU"),
    ("CC - HYUNDAI MOTORS SAVANNAH", "CC - Hyundai Motors Savannah"),
    ("GOSHEN (SAV) - MCINTOSH", "Goshen (SAV) - McIntosh"),
    ("ATLAS BESS IV", "Atlas BESS IV"),
    ("CALLISTO II ENERGY CENTER", "Callisto II Energy Center"),
    ("AMISCOPE NORDHOFF LP", "Amiscope Nordhoff LP"),
    ("201LC 8ME", "201LC 8ME"),
    ("CVE US NY RIVERHEAD 215", "CVE US NY Riverhead 215"),
    ("ENBRIDGE SOLAR (SEQUOIA II)", "Enbridge Solar (Sequoia II)"),
    ("CITY OF BELLEVILLE - (KS)", "City of Belleville - (KS)"),
    ("BELGIAN RENEWABLE ENERGY GROUP (BREG)", "Belgian Renewable Energy Group (BREG)"),
    ("SOLAR1 PROJECT2 TS25-422", "Solar1 Project2 TS25-422"),
    ("3RD ST - 31ST AVE", "3rd St - 31st Ave"),
    ("O'BANNION SMITH'S FT MYERS", "O'Bannion Smith's Ft Myers"),
    ("LA GRANGE - EL DORADO", "La Grange - El Dorado"),
    ("NEXTERA ENERGY RESOURCES - ERCOT", "NextEra Energy Resources - ERCOT"),
])
def test_title_case(raw, expected):
    assert title_case(raw) == expected


@given(st.text(st.sampled_from("ABCIKMVXYZcdeiov0123 &'-()/#,.")))
def test_title_case_changes_only_case_and_is_idempotent(raw):
    once = title_case(raw)
    assert once.lower() == raw.lower()
    assert title_case(once) == once


@pytest.mark.parametrize(("raw", "expected"), [
    # "CO" in parentheses is Colorado, not a corporate suffix to strip.
    ("CITY OF COLORADO SPRINGS - (CO)", "City of Colorado Springs - (CO)"),
    ("Enbridge Solar (Sequoia II) LLC", "Enbridge Solar (Sequoia II)"),
    ("Atlas BESS IV, LLC", "Atlas BESS IV"),
    ("SCANA Corporation", "SCANA"),
    ("NextEra Energy Resources - ERCOT, LLC", "NextEra Energy Resources - ERCOT"),
    ("Met-Ed", "Met-Ed"),
    ("TVA", "TVA"),
])
def test_canonical_utility_casing(raw, expected):
    assert canonical_utility(raw) == expected


def test_corporate_parent_keys_are_canonical():
    assert all(canonical_utility(k) == k for k in CORPORATE_PARENT)
