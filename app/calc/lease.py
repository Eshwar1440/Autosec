from decimal import Decimal

from app.calc.amortization import build_quote, to_cents

APR_TO_MONEY_FACTOR = Decimal(2400)


def lease_quote(
    vehicle_price: Decimal,
    down_payment: Decimal,
    trade_in_value: Decimal,
    sales_tax_percent: Decimal,
    lease_apr_percent: Decimal,
    residual_percent: Decimal,
    term_months: int,
) -> dict[str, Decimal | int]:
    """Standard US lease: depreciation fee + finance (rent) charge, with sales tax on each payment."""
    net_cap_cost = vehicle_price - down_payment - trade_in_value
    residual_value = to_cents(vehicle_price * residual_percent / 100)
    if net_cap_cost <= residual_value:
        raise ValueError("down payment and trade-in bring the capitalized cost below the residual value")

    money_factor = lease_apr_percent / APR_TO_MONEY_FACTOR
    depreciation_fee = (net_cap_cost - residual_value) / term_months
    rent_charge = (net_cap_cost + residual_value) * money_factor
    base_payment = to_cents(depreciation_fee + rent_charge)
    monthly_tax = to_cents(base_payment * sales_tax_percent / 100)
    payment = base_payment + monthly_tax
    return {
        "money_factor": money_factor.quantize(Decimal("0.000001")),
        "residual_value": residual_value,
        "monthly_payment": payment,
        "total_of_payments": payment * term_months,
    }


def lease_vs_buy(
    vehicle_price: Decimal,
    down_payment: Decimal,
    trade_in_value: Decimal,
    sales_tax_percent: Decimal,
    loan_apr_percent: Decimal,
    lease_apr_percent: Decimal,
    residual_percent: Decimal,
    term_months: int,
) -> dict[str, object]:
    """Compare net cost over the same term, assuming the car is worth its residual value at the end."""
    lease = lease_quote(
        vehicle_price, down_payment, trade_in_value, sales_tax_percent,
        lease_apr_percent, residual_percent, term_months,
    )
    loan = build_quote(
        vehicle_price, down_payment, trade_in_value, sales_tax_percent, loan_apr_percent, term_months
    )
    upfront = down_payment + trade_in_value
    lease_paid = upfront + lease["total_of_payments"]
    buy_paid = upfront + loan["total_of_payments"]
    buy_net = buy_paid - lease["residual_value"]
    return {
        "lease": {
            "monthly_payment": lease["monthly_payment"],
            "total_paid": lease_paid,
            "equity_at_end": Decimal("0.00"),
            "net_cost": lease_paid,
        },
        "buy": {
            "monthly_payment": loan["monthly_payment"],
            "total_paid": buy_paid,
            "equity_at_end": lease["residual_value"],
            "net_cost": buy_net,
        },
        "money_factor": lease["money_factor"],
        "cheaper_option": "lease" if lease_paid < buy_net else "buy",
        "savings": abs(lease_paid - buy_net),
    }
