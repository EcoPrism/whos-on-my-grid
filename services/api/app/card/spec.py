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

# ShareCard.tsx drops the bill line ("+$20/mo ...") when the big number shows it.
_BILL_LINE = re.compile(r"^[+−-]\$")


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


def fmt_money(n: float) -> str:
    """lib/format.ts fmtMoney: '+$31', '−$4'."""
    return f"{'−' if n < 0 else '+'}${_whole(n)}"


def fmt_range(lo: float, hi: float) -> str:
    """lib/format.ts fmtRange: '+$25 to $37'. A range, never a point alone."""
    return f"{'−' if hi < 0 else '+'}${_whole(lo)} to ${_whole(hi)}"


def _title(card: dict[str, Any]) -> str:
    return str(card.get("title") or "").removeprefix(TITLE_PREFIX)


def _lines(card: dict[str, Any], big: str | None) -> tuple[str, ...]:
    lines = [str(line) for line in card.get("lines") or [] if line]
    if big is not None:
        lines = [line for line in lines if not _BILL_LINE.match(line)]
    return tuple(lines[:MAX_LINES])


def _years(price: dict[str, Any] | None) -> str:
    """'2025 vs 2023' for annual utility data, as ShareCard.tsx words it."""
    as_of = (price or {}).get("as_of") or ""
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
        span = headline.get("ai_rent_range_usd_per_month")
        big = fmt_range(*span) if span else f"about {fmt_money(rent)}"
        price = ((brief.get("sections") or {}).get("your_bill") or {}).get("price")
        caption = f"a month for a typical home, {_years(price)} · modeled"
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
