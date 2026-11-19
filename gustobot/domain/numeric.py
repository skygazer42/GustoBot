"""Exact numeric query contracts and bounded source-duration grammar."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NumericProperty = Literal["ingredientUsageAmount", "ingredientTotalAmount", "reportedDuration"]
NumericGrain = Literal["usage", "recipe_total", "reported_unspecified", "prep", "cook", "total"]
DEFAULT_NUMERIC_GRAINS: dict[str, NumericGrain] = {
    "ingredientUsageAmount": "usage",
    "ingredientTotalAmount": "recipe_total",
    "reportedDuration": "reported_unspecified",
}
ExactNumber = str | int
INT64_MAX = 9223372036854775807
DURATION_FIELDS = {
    "reported_unspecified": "cook_time",
    "prep": "prep_duration",
    "cook": "cook_duration",
    "total": "total_duration",
}


def exact_number(value: ExactNumber) -> Decimal:
    if type(value) not in (str, int):
        raise ValueError("Numeric values must be exact strings or integers")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Invalid exact numeric value") from error
    if not result.is_finite() or result < 0:
        raise ValueError("Numeric values must be finite and nonnegative")
    return result


class _NumericModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _NumericReference(_NumericModel):
    property: NumericProperty
    target_ref: str | None = None
    grain: NumericGrain

    @model_validator(mode="after")
    def _validate_grain(self):
        if self.property == "reportedDuration":
            valid = self.grain in DURATION_FIELDS and self.target_ref is None
        else:
            valid = (
                self.grain
                == ("usage" if self.property == "ingredientUsageAmount" else "recipe_total")
                and self.target_ref is not None
                and bool(self.target_ref.strip())
            )
        if not valid:
            raise ValueError("Numeric property, grain and target_ref disagree")
        return self


class OrderSpec(_NumericReference):
    direction: Literal["asc", "desc"] = "asc"


class NumericSelection(_NumericReference):
    unit: str | None = None


class NumericCondition(_NumericReference):
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "between"]
    value: ExactNumber | None = None
    minimum: ExactNumber | None = None
    maximum: ExactNumber | None = None
    unit: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_bounds(self):
        if not self.unit.strip():
            raise ValueError("Numeric unit cannot be blank")
        if self.op == "between":
            if self.value is not None or self.minimum is None or self.maximum is None:
                raise ValueError("between requires minimum and maximum only")
            if exact_number(self.minimum) > exact_number(self.maximum):
                raise ValueError("Numeric interval bounds are reversed")
        elif self.value is None or self.minimum is not None or self.maximum is not None:
            raise ValueError("Numeric comparisons require value only")
        for value in (self.value, self.minimum, self.maximum):
            if value is not None:
                exact_number(value)
        return self


class NumericProjectionSpec(_NumericModel):
    dimension: str
    tick_unit: str
    minimum: int = Field(ge=0)
    maximum: int = Field(le=INT64_MAX)
    projection_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_range(self):
        if self.minimum > self.maximum:
            raise ValueError("Projection range is reversed")
        return self


class NumericValue(_NumericModel):
    status: Literal["comparable", "unknown", "non_comparable"]
    dimension: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    projection_version: str


class NumericCoverage(_NumericModel):
    property: NumericProperty
    target_ref: str | None = None
    grain: NumericGrain
    projection_version: str
    total: int = Field(ge=0)
    matched: int = Field(ge=0)
    not_matched: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)
    uncertain: int = Field(default=0, ge=0)
    non_comparable: int = Field(default=0, ge=0)


class NumericMeasurement(_NumericReference):
    anchor_id: str
    status: Literal["comparable", "unknown", "uncertain", "non_comparable"]
    minimum: int | None = None
    maximum: int | None = None
    dimension: str | None = None
    projection_version: str
    relation_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class NumericRebuildReport(_NumericModel):
    domain_id: str
    ontology_version: str
    ontology_fingerprint: str
    projection_version: str
    revision: int
    applied: bool
    entities: int = Field(ge=0)
    relations: int = Field(ge=0)
    comparable: int = Field(ge=0)
    unknown: int = Field(ge=0)
    non_comparable: int = Field(ge=0)


_CHINESE_DIGITS = dict(
    zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9), strict=True)
)
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_DURATION_COMPONENT = re.compile(
    r"(\d+(?:\.\d+)?|半|[零〇一二两三四五六七八九十百千万]+)(毫秒|秒钟|秒|分钟|分|小时|时|天|日)"
)
_DURATION_UNITS = {
    "毫秒": "ms",
    "秒钟": "second",
    "秒": "second",
    "分钟": "minute",
    "分": "minute",
    "小时": "hour",
    "时": "hour",
    "天": "day",
    "日": "day",
}
_ISO_DURATION = re.compile(
    r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?"
)


def _duration_number(value: str) -> Decimal:
    if value == "半":
        return Decimal("0.5")
    if value[0].isdigit():
        return Decimal(value)
    total, section, digit = 0, 0, 0
    last_scale, previous_digit = 10001, None
    for character in value:
        if character in _CHINESE_DIGITS:
            if previous_digit is not None and previous_digit != 0:
                raise ValueError("Unsupported Chinese duration numeral")
            digit = _CHINESE_DIGITS[character]
            previous_digit = digit
        else:
            scale = _CHINESE_UNITS[character]
            if scale >= last_scale:
                raise ValueError("Chinese duration units must descend")
            if scale == 10000:
                total += (section + digit) * scale
                section, digit = 0, 0
                last_scale = 10000
            else:
                section += (digit if digit else 1) * scale
                digit = 0
                last_scale = scale
            previous_digit = None
    return Decimal(total + section + digit)


def duration_components(raw: str | None) -> list[tuple[Decimal, str]] | None:
    if raw is None:
        return None
    text = "".join(unicodedata.normalize("NFKC", raw).split())
    iso = _ISO_DURATION.fullmatch(text)
    if iso is not None and any(value is not None for value in iso.groups()):
        if "T" in text and not any(value is not None for value in iso.groups()[1:]):
            return None
        return [
            (Decimal(value), unit)
            for value, unit in zip(iso.groups(), ("day", "hour", "minute", "second"), strict=True)
            if value is not None
        ]
    matches = list(_DURATION_COMPONENT.finditer(text))
    if not matches or "".join(match.group() for match in matches) != text:
        return None
    try:
        return [(_duration_number(match[1]), _DURATION_UNITS[match[2]]) for match in matches]
    except ValueError:
        return None
