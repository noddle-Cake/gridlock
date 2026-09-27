"""Title case for names read from all-caps public sources.

`str.title()` turns "MCDONOUGH 230KV (FPL)" into "Mcdonough 230Kv (Fpl)". `title_case`
keeps what the source's capitals meant: units ("230 kV"), acronyms ("BESS", "LLC",
"(FPL)", "8ME"), roman numerals ("Atlas BESS IV") and Mc names ("McDonough").
"""

from __future__ import annotations

import re

_UNITS = {"KV": "kV", "KW": "kW", "KVA": "kVA", "MW": "MW", "MWH": "MWh", "MVA": "MVA",
          "MVAR": "MVAR", "GW": "GW"}
_NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)(" + "|".join(_UNITS) + r")")
_ORDINAL = re.compile(r"\d+(ST|ND|RD|TH)")
_ROMAN = re.compile(r"(?=[IVX]{2,}$)X{0,3}(IX|IV|V?I{0,3})")
# Acronyms with a vowel, so the no-vowel rule below can't tell them from words.
_ACRONYMS = {"BESS", "ESS", "CVE", "EDF", "EDP", "EDPR", "EMC", "ERCOT", "JEA", "MEAG",
             "SCANA", "TVA", "USA"}
_SPELLED = {"NEXTERA": "NextEra"}
_SMALL = {"of", "and", "the", "de", "to", "at", "for"}  # lower case unless leading
# Two-letter words and name particles; any other two letters are a code ("NY", "LP", "US").
_TWO_LETTER_WORDS = {"of", "to", "in", "on", "at", "by", "or", "an", "as", "is", "it", "be",
                     "do", "go", "no", "so", "up", "we", "my", "ox", "ed", "el", "la", "le", "du",
                     "da", "di", "lo"}
# Vowel-less abbreviations that read as words; other vowel-less words are acronyms (LLC).
_ABBREVIATIONS = {"st", "ft", "mt", "pt", "rd", "dr", "jr", "ln", "jct", "blvd", "twp",
                  "mtn", "bldg", "pwr", "jnt", "mgmt"}
_VOWEL = re.compile(r"[AEIOUY]")
_WORD = re.compile(r"[A-Za-z0-9]+(?:['&][A-Za-z0-9]+)*")


def _case_word(word: str, *, first: bool, alone_in_parens: bool) -> str:
    if word not in (word.upper(), word.lower(), word.capitalize()):
        return word  # deliberate mixed case: "McDonough", "kV", "NextEra"
    upper, lower = word.upper(), word.lower()
    if "&" in upper:
        return upper  # "LG&E", "AT&T"
    if "'" in upper:
        head, tail = upper.split("'", 1)
        head = _case_word(head, first=first, alone_in_parens=False)
        return f"{head}'{tail.capitalize() if len(head) == 1 and len(tail) > 1 else tail.lower()}"
    if upper in _UNITS:
        return _UNITS[upper]
    if m := _NUMBER_UNIT.fullmatch(upper):
        return m[1] + _UNITS[m[2]]
    if _ORDINAL.fullmatch(upper):
        return lower
    if any(c.isdigit() for c in upper):  # codes ("8ME", "TS25") unless a word ("Solar1")
        return "".join(run if len(run) <= 3 else run.capitalize()
                       for run in re.findall(r"\d+|[A-Z]+", upper))
    if _ROMAN.fullmatch(upper) or upper in _ACRONYMS:
        return upper
    if upper in _SPELLED:
        return _SPELLED[upper]
    if alone_in_parens and len(upper) <= 4:
        return upper  # "(CO)", "(FPL)", "(BREG)"
    if lower in _SMALL and not first:
        return lower
    if len(upper) == 2 and lower not in _TWO_LETTER_WORDS | _ABBREVIATIONS:
        return upper
    if len(upper) > 1 and not _VOWEL.search(upper) and lower not in _ABBREVIATIONS:
        return upper
    if upper.startswith("MC") and len(upper) >= 5:
        return "Mc" + upper[2:].capitalize()
    return upper.capitalize()


def title_case(text: str) -> str:
    """'MCDONOUGH - LG&E 230KV LINE (FPL)' -> 'McDonough - LG&E 230kV Line (FPL)'."""
    def fix(m: re.Match[str]) -> str:
        start, end = m.span()
        before = text[:start].rstrip()
        return _case_word(
            m[0], first=not before or before[-1] in "(-:",
            alone_in_parens=text[start - 1:start] == "(" and text[end:end + 1] == ")",
        )
    return _WORD.sub(fix, text)
