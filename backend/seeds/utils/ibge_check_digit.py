"""IBGE municipality code check digit computation.

The 7-digit IBGE code is the 6-digit code plus a single check digit.
"""


def compute_check_digit(codigo_6: str) -> str:
    """Compute the check digit for a 6-digit IBGE municipality code.

    Algorithm: Luhn/EAN variant — even-indexed positions add the digit directly;
    odd-indexed positions double the digit and sum the resulting two digits (v // 10 + v % 10).
    Check digit is (10 - total % 10) % 10.
    """
    digits = [int(c) for c in codigo_6]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            v = d * 2
            total += v // 10 + v % 10
        else:
            total += d
    remainder = total % 10
    return str(0 if remainder == 0 else 10 - remainder)


def to_7_digit(codigo_6: str) -> str:
    """Return the 7-digit IBGE code by appending the check digit."""
    return codigo_6 + compute_check_digit(codigo_6)
