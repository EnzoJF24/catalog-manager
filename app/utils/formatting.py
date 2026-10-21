"""
Number and price formatting shared by the UI, the PDF catalog and Excel export.
US conventions: "$1,234.56".
"""
from __future__ import annotations

CURRENCY_SYMBOL = "$"

# openpyxl number format matching format_price()
EXCEL_PRICE_FORMAT = '"$"#,##0.00'


def format_price(value: float, decimals: int = 2) -> str:
    """1234.5 → '$1,234.50' (decimals=0 → '$1,235')."""
    return f"{CURRENCY_SYMBOL}{value:,.{decimals}f}"


def parse_number(text) -> float:
    """
    Parse a user-typed number, tolerating both '1,234.56' and '12,5'.
    A comma is a thousands separator when a dot is also present,
    otherwise it is treated as the decimal separator.
    Raises ValueError on anything that is not a number.
    """
    s = str(text).strip().replace(CURRENCY_SYMBOL, "").replace(" ", "")
    if not s:
        raise ValueError("empty value")
    if "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    return float(s)
