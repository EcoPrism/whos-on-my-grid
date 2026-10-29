"""What a resident asks: a ZIP, a campus size, a cooling type and an optional
pin. The scenario id is a hash of these; a ZIP is coarser than an address but
gets the same hygiene: it is never logged, only the id is."""

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

Cooling = Literal["evaporative", "closed_loop"]
COOLING: tuple[Cooling, ...] = ("evaporative", "closed_loop")

ZIP = re.compile(r"^\d{5}$")
MW_MIN, MW_MAX = 10, 2000
PIN_DECIMALS = 3  # about 100 m: enough to place a campus, too coarse to name a house


class InputsInvalid(ValueError):
    pass


def round_pin(lat: float, lon: float) -> tuple[float, float]:
    return (round(float(lat), PIN_DECIMALS), round(float(lon), PIN_DECIMALS))


@dataclass(frozen=True)
class ScenarioInputs:
    zip: str  # ^\d{5}$
    mw: int  # 10..2000
    cooling: Cooling
    pin: tuple[float, float] | None = None  # rounded to 3 decimals before id and storage

    def __post_init__(self) -> None:
        if not ZIP.match(self.zip):
            raise InputsInvalid("zip")
        if isinstance(self.mw, bool) or not isinstance(self.mw, int):
            raise InputsInvalid("mw")
        if not MW_MIN <= self.mw <= MW_MAX:
            raise InputsInvalid("mw")
        if self.cooling not in COOLING:
            raise InputsInvalid("cooling")
        if self.pin is not None:
            lat, lon = self.pin
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise InputsInvalid("pin")
            object.__setattr__(self, "pin", round_pin(lat, lon))

    @classmethod
    def create(
        cls, *, zip: str, mw: int, cooling: str, pin: tuple[float, float] | None = None
    ) -> "ScenarioInputs":
        return cls(zip=zip, mw=mw, cooling=cast(Cooling, cooling), pin=pin)

    def scenario_id(self) -> str:
        """sha256 of 'zip|mw|cooling|lat|lon', first 16 hex. Nothing else derived
        from the inputs is logged."""
        lat, lon = (f"{v:.{PIN_DECIMALS}f}" for v in self.pin) if self.pin else ("", "")
        key = f"{self.zip}|{self.mw}|{self.cooling}|{lat}|{lon}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def as_json(self) -> dict[str, Any]:
        return {
            "zip": self.zip,
            "mw": self.mw,
            "cooling": self.cooling,
            "pin": {"lat": self.pin[0], "lon": self.pin[1]} if self.pin else None,
        }
