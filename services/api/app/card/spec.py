"""What goes on a share card, as data: the same fields ShareCard.tsx reads
from the brief, so the DOM preview, the PNG and the share text agree. Built
from a brief or from a scenario; no model call, no new claim."""

import re
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from app.brief.headline import disclosure_line

TITLE_PREFIX = "Who's on my grid: "
SCENARIO_DISCLOSURE = "Hypothetical. Modelled, not measured."
SHARE_TAIL = "AI-assisted brief, every claim cited."
SCENARIO_SHARE_TAIL = "Hypothetical what-if, modelled from cited figures."
MAX_LINES = 4

# ShareCard.tsx drops the bill line ("+$20/mo ...", "+€45/mo ...") when the big
# number shows it. ShareCard.tsx copies this character class; the shared cases are
# schema/card_bill_cases.json.
_BILL_LINE = re.compile(r"^[+−-][$€£₹]")
_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


@dataclass(frozen=True)
class CardSpec:
    kind: Literal["brief", "scenario"]
    title: str  # card.title without the "Who's on my grid: " prefix
    lines: tuple[str, ...]  # card.lines, bill line dropped when `big` is shown
    big: str | None  # "+$9 to $14" from headline.ai_rent_range_usd_per_month
    big_caption: str | None  # "a month for a typical home, 2025 vs 2023 · modeled"
    footer: str | None  # card.footer (sources)
    disclosure: str  # card.disclosure
    hypothetical: bool  # scenario cards: banner "HYPOTHETICAL · modelled, not measured"

    def as_json(self) -> dict[str, Any]:
        """The CardInfo `spec` block: everything but the kind, which sits beside it."""
        out = asdict(self)
        out.pop("kind")
        out["lines"] = list(self.lines)
        return out


def _whole(x: float) -> str:
    """Number.toFixed(0) on |x|: ties go up, not to even as f'{x:.0f}' does.
    Decimal(float) is the float's exact value, so 0.49999999999999994 stays 0."""
    return str(Decimal(abs(x)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _symbol(currency: str) -> str:
    return _SYMBOLS.get(currency.upper(), f"{currency.upper()} ")


def fmt_money(n: float, currency: str = "USD") -> str:
    """lib/format.ts fmtMoney: '+$31', '−$4', '+€45'."""
    return f"{'−' if n < 0 else '+'}{_symbol(currency)}{_whole(n)}"


def fmt_range(lo: float, hi: float, currency: str = "USD") -> str:
    """lib/format.ts fmtRange: '+$25 to $37', '+€36 to €54'. A range, never a point alone."""
    sym = _symbol(currency)
    return f"{'−' if hi < 0 else '+'}{sym}{_whole(lo)} to {sym}{_whole(hi)}"


def _title(card: dict[str, Any]) -> str:
    return str(card.get("title") or "").removeprefix(TITLE_PREFIX)


def _lines(card: dict[str, Any], big: str | None) -> tuple[str, ...]:
    lines = [str(line) for line in card.get("lines") or [] if line]
    if big is not None:
        lines = [line for line in lines if not _BILL_LINE.match(line)]
    return tuple(lines[:MAX_LINES])


def _half(year: int, month: int) -> str:
    return f"{'H1' if month <= 6 else 'H2'} {year}"


def _years(price: dict[str, Any] | None) -> str:
    """'2025 vs 2023' for annual utility data, 'H1 2026 vs H1 2024' for a
    semiannual series, as ShareCard.tsx (lib/format.ts periodLabel) words it."""
    as_of = (price or {}).get("as_of") or ""
    if (price or {}).get("granularity") == "semiannual" and len(as_of) == 7:
        y, m = int(as_of[:4]), int(as_of[5:7])
        if m in (6, 12):
            months = y * 12 + (m - 1) - int((price or {}).get("window_months") or 24)
            return f"{_half(y, m)} vs {_half(months // 12, months % 12 + 1)}"
    if as_of.endswith("-12") and len(as_of) == 7:
        year = int(as_of[:4])
        return f"{year} vs {year - 2}"
    return "vs two years ago"


def _checked(brief: dict[str, Any]) -> tuple[bool, bool]:
    """(verified, grounded), read from the card footer as headline.derive_card
    words it; a brief with no footer is read from its claims and sections."""
    footer = str((brief.get("card") or {}).get("footer") or "")
    if footer:
        return (
            "claims not yet checked" not in footer,
            "Not verified against ground-truth data" not in footer,
        )
    claims = brief.get("claims") or []
    sections = (brief.get("sections") or {}).values()
    return (
        any(c.get("verified_by") for c in claims),
        any(isinstance(s, dict) and s.get("status") == "measured" for s in sections),
    )


def spec_from_brief(brief: dict[str, Any], *, public_base_url: str = "") -> CardSpec:
    """The brief's card block plus the headline's bill range. The disclosure is
    made here from the id, the date and the base, not read from card.disclosure:
    a brief stored without a public base (or before the field existed) still
    prints a link with a host."""
    card = brief.get("card") or {}
    headline = brief.get("headline") or {}
    rent = headline.get("ai_rent_usd_per_month")
    big: str | None = None
    caption: str | None = None
    if rent is not None:
        # The headline's figure is in the brief's currency (the key's name is legacy).
        currency = str((brief.get("locale") or {}).get("currency") or "USD")
        span = headline.get("ai_rent_range_usd_per_month")
        big = fmt_range(*span, currency) if span else f"about {fmt_money(rent, currency)}"
        price = ((brief.get("sections") or {}).get("your_bill") or {}).get("price")
        caption = f"a month for a typical home, {_years(price)} · our estimate"
    verified, grounded = _checked(brief)
    disclosure = disclosure_line(
        str(brief.get("brief_id") or ""),
        str(brief.get("generated_at") or ""),
        public_base_url,
        verified=verified,
        grounded=grounded,
    )
    return CardSpec(
        kind="brief",
        title=_title(card),
        lines=_lines(card, big),
        big=big,
        big_caption=caption,
        footer=card.get("footer") or None,
        disclosure=disclosure,
        hypothetical=False,
    )


def scenario_disclosure_line(
    scenario_id: str, generated_at: str, public_base_url: str = "", *, verified: bool = True
) -> str:
    """The what-if card's footer band, as disclosure_line is the brief's: what
    made it, in words, and its link."""
    base = public_base_url.rstrip("/")
    checked = "sources checked by Muse Spark Open" if verified else "sources not yet checked"
    return (
        "Hypothetical what-if, not a measurement. Numbers modelled by the engine from cited "
        f"public figures; {checked}. {base}/what-if/{scenario_id} · {generated_at[:10]}"
    )


def spec_from_scenario(scenario: dict[str, Any], *, public_base_url: str = "") -> CardSpec:
    """A what-if card (schema/scenario.schema.json, design B.4): its card block,
    the bill range when the tariff does not shield homes, and the hypothetical
    band. Every number on it is modelled. As for briefs, the disclosure is made
    anew from the id, the date and the base when the scenario carries them."""
    card = scenario.get("card") or {}
    bill = (scenario.get("impact") or {}).get("bill") or {}
    span = bill.get("range_usd_per_month")
    big = fmt_range(*span) if span else None
    caption = "a month for a typical home if it is built · modelled" if big else None
    return CardSpec(
        kind="scenario",
        title=_title(card),
        lines=_lines(card, big),
        big=big,
        big_caption=caption,
        footer=card.get("footer") or None,
        disclosure=_scenario_disclosure(scenario, card, public_base_url),
        hypothetical=True,
    )


def _scenario_disclosure(scenario: dict[str, Any], card: dict[str, Any], base: str) -> str:
    sid, at = scenario.get("scenario_id"), scenario.get("generated_at")
    if sid and at:
        stored = str(card.get("disclosure") or "")
        verified = (
            "not yet checked" not in stored
            if stored
            else any(c.get("verified_by") for c in scenario.get("claims") or [])
        )
        return scenario_disclosure_line(str(sid), str(at), base, verified=verified)
    return str(card.get("disclosure") or scenario.get("disclosure") or SCENARIO_DISCLOSURE)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def share_text(spec: CardSpec, url: str) -> str:
    """'{title}. {lines[0]} AI-assisted brief, every claim cited. {url}'"""
    parts = [_sentence(spec.title)]
    if spec.lines:
        parts.append(_sentence(spec.lines[0]))
    parts += [SHARE_TAIL if spec.kind == "brief" else SCENARIO_SHARE_TAIL, url]
    return " ".join(p for p in parts if p)
