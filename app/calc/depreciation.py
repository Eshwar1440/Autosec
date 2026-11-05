from decimal import Decimal

from app.calc.amortization import to_cents


def depreciation_schedule(
    cost: Decimal, salvage_value: Decimal, useful_life_years: int, method: str
) -> list[dict[str, Decimal | int]]:
    """Yearly depreciation down to salvage value.

    "double_declining" switches to straight-line once that writes off more, the usual
    convention, so the asset still reaches salvage value exactly in its final year.
    """
    if salvage_value >= cost:
        raise ValueError("salvage value must be below cost")

    rate = Decimal(2) / useful_life_years
    book = cost
    accumulated = Decimal(0)
    rows: list[dict[str, Decimal | int]] = []
    for year in range(1, useful_life_years + 1):
        remaining_years = useful_life_years - year + 1
        straight_line = (book - salvage_value) / remaining_years
        if year == useful_life_years:
            amount = book - salvage_value
        elif method == "straight_line":
            amount = to_cents(straight_line)
        else:
            amount = min(to_cents(max(book * rate, straight_line)), book - salvage_value)
        book -= amount
        accumulated += amount
        rows.append({"year": year, "depreciation": amount, "accumulated": accumulated, "book_value": book})
    return rows
