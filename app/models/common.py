import re
from decimal import Decimal
from typing import Annotated, Any, NoReturn

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema

# Each pattern encodes the field's upper bound too, so the published schema
# matches what the server accepts and fuzzers don't waste cases on it.
MONEY_PATTERN = r"^((0|[1-9]\d{0,6})(\.\d{1,2})?|10000000(\.0{1,2})?)$"
APR_PATTERN = r"^(([0-9]|[12][0-9]|3[0-5])(\.\d{1,4})?|36(\.0{1,4})?)$"
TAX_PATTERN = r"^(([0-9]|1[0-9])(\.\d{1,4})?|20(\.0{1,4})?)$"
RESIDUAL_PATTERN = r"^(([0-9]|[1-8][0-9]|9[0-4])(\.\d{1,4})?|95(\.0{1,4})?)$"


def decimal_field(pattern: str, *, le: str, step: str, gt: str | None = None) -> Any:
    """A Decimal accepted as a JSON number or a plain decimal string.

    Pydantic alone would also take strings like "1e2", " 5" or "1_000", and would
    advertise any string as valid in the OpenAPI schema. This pins both down.
    """
    regex = re.compile(pattern)

    def reject_loose_strings(value: object) -> object:
        if isinstance(value, str) and not regex.fullmatch(value):
            raise ValueError("must be a plain decimal string within range, e.g. '1234.56'")
        return value

    number: dict[str, Any] = {"type": "number", "maximum": float(le), "multipleOf": float(step)}
    if gt is None:
        number["minimum"] = 0
    else:
        number["exclusiveMinimum"] = float(gt)
    return Annotated[
        Decimal,
        BeforeValidator(reject_loose_strings),
        Field(
            ge=0 if gt is None else None,
            gt=None if gt is None else Decimal(gt),
            le=Decimal(le),
            decimal_places=len(step.split(".")[1]),
        ),
        WithJsonSchema({"anyOf": [number, {"type": "string", "pattern": pattern}]}),
    ]


Money = decimal_field(MONEY_PATTERN, le="10000000", step="0.01")
Price = decimal_field(MONEY_PATTERN, le="10000000", step="0.01", gt="0")
Apr = decimal_field(APR_PATTERN, le="36", step="0.0001")
TaxRate = decimal_field(TAX_PATTERN, le="20", step="0.0001")
Term = Annotated[int, Field(ge=12, le=96)]


class ErrorMessage(BaseModel):
    detail: str


BAD_JSON = {400: {"model": ErrorMessage, "description": "Request body is not valid JSON"}}


def business_rule_error(exc: ValueError) -> NoReturn:
    """Raise a 422 shaped like schema-validation errors, so clients parse one format."""
    raise RequestValidationError(
        [{"type": "value_error", "loc": ("body",), "msg": str(exc), "input": None}]
    ) from exc

Residual = decimal_field(RESIDUAL_PATTERN, le="95", step="0.0001", gt="0")
