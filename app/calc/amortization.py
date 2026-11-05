"""Loan amortization math using Decimal so money never touches binary floats."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext

CENT = Decimal("0.01")
MONTHS_PER_YEAR = 12


def to_cents(value: Decimal) -> Decimal:
    """Round a monetary value to whole cents, half-up (standard for consumer loans)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_payment(principal: Decimal, apr_percent: Decimal, term_months: int) -> Decimal:
    """Level monthly payment for a fully amortizing loan, rounded to cents.

    Uses P * r / (1 - (1 + r) ** -n), where r is the monthly periodic rate.
    A 0% APR loan is principal split evenly across the term.
    """
    if principal <= 0:
        raise ValueError("principal must be positive")
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    if apr_percent < 0:
        raise ValueError("apr_percent must not be negative")

    if apr_percent == 0:
        return to_cents(principal / term_months)

    # Extra working precision so intermediate powers don't lose cents on long terms.
    with localcontext() as ctx:
        ctx.prec = 34
        rate = apr_percent / Decimal(100) / MONTHS_PER_YEAR
        payment = principal * rate / (1 - (1 + rate) ** -term_months)
    return to_cents(payment)


def build_quote(
    vehicle_price: Decimal,
    down_payment: Decimal,
    trade_in_value: Decimal,
    sales_tax_percent: Decimal,
    apr_percent: Decimal,
    term_months: int,
) -> dict[str, Decimal | int]:
    """Assemble a full quote: taxed price, amount financed, payment, and totals."""
    sales_tax = to_cents(vehicle_price * sales_tax_percent / Decimal(100))
    amount_financed = vehicle_price + sales_tax - down_payment - trade_in_value
    if amount_financed <= 0:
        raise ValueError("down payment and trade-in cover the full price; nothing to finance")

    payment = monthly_payment(amount_financed, apr_percent, term_months)
    total_of_payments = payment * term_months
    return {
        "sales_tax": sales_tax,
        "amount_financed": amount_financed,
        "monthly_payment": payment,
        "term_months": term_months,
        "total_of_payments": total_of_payments,
        "total_interest": total_of_payments - amount_financed,
    }


def monthly_rate(apr_percent: Decimal) -> Decimal:
    return apr_percent / Decimal(100) / MONTHS_PER_YEAR


def schedule(principal: Decimal, apr_percent: Decimal, term_months: int) -> list[dict[str, Decimal | int]]:
    """Month-by-month breakdown. The last payment absorbs the rounding remainder so the balance ends at 0.

    Payments rounded up to the cent can retire a small loan early; the schedule then ends early too.
    """
    payment = monthly_payment(principal, apr_percent, term_months)
    rate = monthly_rate(apr_percent)
    balance = principal
    rows: list[dict[str, Decimal | int]] = []
    month = 0
    while balance > 0:
        month += 1
        interest = to_cents(balance * rate)
        principal_paid = balance if month == term_months else min(payment - interest, balance)
        balance -= principal_paid
        rows.append(
            {
                "month": month,
                "payment": principal_paid + interest,
                "principal": principal_paid,
                "interest": interest,
                "balance": balance,
            }
        )
    return rows


def max_principal(payment: Decimal, apr_percent: Decimal, term_months: int) -> Decimal:
    """Inverse of monthly_payment: the largest loan a given payment covers (before rounding)."""
    if apr_percent == 0:
        return payment * term_months
    with localcontext() as ctx:
        ctx.prec = 34
        rate = monthly_rate(apr_percent)
        return payment * (1 - (1 + rate) ** -term_months) / rate


def affordable_price(
    monthly_budget: Decimal,
    down_payment: Decimal,
    trade_in_value: Decimal,
    sales_tax_percent: Decimal,
    apr_percent: Decimal,
    term_months: int,
) -> Decimal:
    """Highest whole-cent vehicle price whose quoted payment fits the budget."""

    def fits(price: Decimal) -> bool:
        quote = build_quote(price, down_payment, trade_in_value, sales_tax_percent, apr_percent, term_months)
        return quote["monthly_payment"] <= monthly_budget

    financed = max_principal(monthly_budget, apr_percent, term_months)
    # Rounding the estimate down keeps the financed amount within half a cent of the exact
    # inverse, so it always fits; only the climb toward the true maximum is needed.
    price = ((financed + down_payment + trade_in_value) / (1 + sales_tax_percent / 100)).quantize(
        CENT, rounding=ROUND_DOWN
    )
    while fits(price + CENT):
        price += CENT
    return price
