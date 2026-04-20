"""Validación de NIF, NIE y CIF españoles (control coherente con python-stdnum / AEAT)."""

from __future__ import annotations

import re

_NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_CIF_FIRST = frozenset("ABCDEFGHJNPQRSUVW")
_CIF_FULL_RE = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")


def normalize_spanish_tax_id(value: str) -> str:
    return re.sub(r"[\s.\-]", "", value.strip().upper())


def _luhn_checksum(number: str) -> int:
    alphabet = "0123456789"
    n = 10
    values = tuple(alphabet.index(i) for i in reversed(str(number)))
    return (
        sum(values[::2])
        + sum(sum(divmod(i * 2, n)) for i in values[1::2])
    ) % n


def _luhn_calc_check_digit(body7: str) -> str:
    alphabet = "0123456789"
    ck = _luhn_checksum(str(body7) + alphabet[0])
    return alphabet[-ck]


def _cif_control_candidates(prefix8: str) -> str:
    d = _luhn_calc_check_digit(prefix8[1:])
    letters = "JABCDEFGHI"
    return d + letters[int(d)]


def _valid_nif(s: str) -> bool:
    if not re.fullmatch(r"\d{8}[A-Z]", s):
        return False
    return _NIF_LETTERS[int(s[:8]) % 23] == s[8]


def _valid_nie(s: str) -> bool:
    if not re.fullmatch(r"[XYZ]\d{7}[A-Z]", s):
        return False
    prefix = {"X": "0", "Y": "1", "Z": "2"}[s[0]]
    num = int(prefix + s[1:8])
    return _NIF_LETTERS[num % 23] == s[8]


def _valid_cif(s: str) -> bool:
    if not _CIF_FULL_RE.match(s) or s[0] not in _CIF_FIRST:
        return False
    opts = _cif_control_candidates(s[:8])
    return s[8] in opts


def is_valid_spanish_tax_id(value: str) -> bool:
    s = normalize_spanish_tax_id(value)
    if not s:
        return False
    return _valid_nif(s) or _valid_nie(s) or _valid_cif(s)
