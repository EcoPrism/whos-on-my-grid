"""The optional interpretation of a what-if: three plain sentences from Muse
Spark around the engine's numbers, with claims that cite only the pages the
scenario already cites. The model adds words, never figures: the prompt hands
it the engine's numbers and forbids new ones, and a paragraph carrying a
number the facts do not contain is rejected. Numbers are read as quantities:
digits, number words ("two"), scale words ("1.5 million") and multipliers
("half", "double"); the allowed ones come from the engine's lines and the
curated quotes, never from a source's URL or title. Only a bare small count
("two campuses") is exempt; one beside a $, a % or a unit is a figure. A claim
whose page is not one of the scenario's quoted sources, or whose quote is not
that page's curated quote, is dropped before the verifier sees it; a page with
no curated quote (the tariff page) is not offered for citing at all. The result
is `reported`, never measured.

The ZIP is not sent: the facts block names the county and state, says "this
ZIP" where an engine line names it, and leaves out (and so forbids citing) the
one source whose URL or title carries it, the ZIP's household count."""

import copy
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.brief.draft import ATTEMPTS, DraftResult, SectionFailure
from app.llm.base import LLMError, LLMProvider
from app.schema import CLAIM_DRAFT, ValidationError, prune_nulls, strictify
from app.telemetry import log_event

SECTION = "scenario"
MAX_CLAIMS = 6
MAX_SOURCES = 30
SMALL_NUMBERS = {str(n) for n in range(11)}  # "two campuses", "3 sentences": not figures
_SHARE = ("%", "percent", "per cent", "percentage")
UNIT_AFTER = (
    "%", "percent", "per cent", "percentage", "dollar", "dollars", "cent", "cents",
    "mw", "gw", "kw", "kwh", "mwh", "gwh", "megawatt", "megawatts", "gigawatt", "gigawatts",
    "kilowatt", "kilowatts", "kilowatthour", "kilowatthours", "gallon", "gallons", "home",
    "homes", "household", "households", "acre", "acres", "mile", "miles", "job", "jobs",
    "people", "residents", "customers", "times", "fold", "a month", "a year", "per month",
    "per year", "a day", "per day",
)  # fmt: skip

INTERPRET_DRAFT: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "confidence", "claims"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "Three plain-English sentences a resident would read. The first says "
            "this is a hypothetical, modelled scenario. Only numbers from the facts block.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "claims": {
            "type": "array",
            "maxItems": MAX_CLAIMS,
            "items": CLAIM_DRAFT,
            "description": "The checkable statements in the summary, each citing one of the "
            "numbered sources in the facts block by its exact URL and its exact quote.",
        },
    },
}

INTERPRET_PROMPT = (
    "You are explaining a modelled what-if scenario to a US resident: a hypothetical data-center "
    "campus dropped on their town. The engine has already done all the arithmetic; your job is "
    "three sentences of plain words around its numbers.\n\n"
    "Rules:\n"
    "1. Write exactly three sentences in `summary`. The first makes clear this is hypothetical "
    "and modelled, not a real proposal and not a measurement.\n"
    "2. Use only numbers that appear in the facts block, written as they appear there. Do not "
    "compute, convert, round, add or estimate any figure of your own. A paragraph with a number "
    "the facts block does not contain is thrown away.\n"
    "3. Never say or imply that a data center would cause a change in anyone's bill. Say what "
    "the engine's bill line says, including when it says there is no estimate.\n"
    "4. Cite only the numbered sources in the facts block. Each claim copies one source's URL "
    "exactly into `source_url` and that source's quote exactly into `quote`, and its `text` says "
    "only what that quote says. Claims citing any other page are dropped.\n"
    "5. Never invent a facility, an operator, a tariff, a vote or a person. Name only what the "
    "facts block names.\n"
    "6. No jargon, no acronyms a resident would not know, no hedging filler.\n"
    "7. `confidence` (0 to 1) is your honest estimate that the paragraph says only what the "
    "facts support.\n"
    f"8. At most {MAX_CLAIMS} claims. Never copy the facts block back into the output.\n"
    "Output only the JSON object."
)

_WS = re.compile(r"\s+")
_UNIT_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
)
_UNITS = {w: n for n, w in enumerate(_UNIT_WORDS.split(" "))}
_TEN_WORDS = "twenty thirty forty fifty sixty seventy eighty ninety"
_TENS = {w: 10 * n for n, w in enumerate(_TEN_WORDS.split(" "), 2)}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 10**6, "billion": 10**9,
           "trillion": 10**12}  # fmt: skip
# Words that state a quantity without a digit: a figure unless the facts use them.
_MULTIPLIERS = re.compile(
    r"\b(half|halve[sd]?|double[sd]?|twice|triple[sd]?|quadruple[sd]?|tenfold|dozens?|"
    r"a third|a quarter|\w+-fold)\b"
)
_WORD = (
    r"(?:(?:" + "|".join(_TENS) + r")(?:[- ](?:" + "|".join(list(_UNITS)[1:10]) + r"))?"
    r"|" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")"
)
_QTY = re.compile(
    r"(?P<cur>\$\s*)?\b(?P<num>\d[\d,]*(?:\.\d+)?|" + _WORD + r")\b"
    r"(?:\s+(?P<scale>" + "|".join(_SCALES) + r")\b)?"
    r"(?=(?P<rest>[^.;:!?]{0,24}))"  # a look, so the next number is still read
)
_URL = re.compile(r"https?://\S+")


def interpret_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    """(original, strict) schemas for the interpretation draft."""
    return INTERPRET_DRAFT, strictify(copy.deepcopy(INTERPRET_DRAFT))


def validate_interpretation(draft: dict[str, Any]) -> dict[str, Any]:
    original, _ = interpret_schemas()
    pruned = prune_nulls(draft, original)
    Draft202012Validator(original, format_checker=FormatChecker()).validate(pruned)
    return pruned


# --- the scenario's own sources ---------------------------------------------


def scenario_sources(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every page the scenario already cites, by URL: {title, quotes}. Taken
    from the claims, the lines, the place and the baseline; never the card.
    A source naming the scenario's ZIP is left out, so the model never sees it."""
    out: dict[str, dict[str, Any]] = {}
    zip5 = str((scenario.get("inputs") or {}).get("zip") or "")

    def add(src: dict[str, Any]) -> None:
        url, title = src.get("url"), src.get("title")
        if not isinstance(url, str) or not url or not isinstance(title, str):
            return
        if zip5 and (zip5 in url or zip5 in title):
            return
        entry = out.setdefault(url, {"title": title, "quotes": []})
        quote = src.get("quote")
        if isinstance(quote, str) and quote.strip() and quote not in entry["quotes"]:
            entry["quotes"].append(quote)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "url" in node and "title" in node:
                add(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for c in scenario.get("claims", []):
        if isinstance(c, dict) and isinstance(c.get("source"), dict):
            add(c["source"])
    for key in ("lines", "place", "baseline"):
        walk(scenario.get(key))
    return out


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def _canon(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _value(num: str) -> float:
    word = num.replace("-", " ")
    if word in _UNITS:
        return float(_UNITS[word])
    parts = word.split()
    if parts and parts[0] in _TENS:
        return float(_TENS[parts[0]] + (_UNITS[parts[1]] if len(parts) > 1 else 0))
    return float(num.replace(",", "").rstrip("."))


def _quantities(text: str) -> list[tuple[str, str, str, bool]]:
    """(scaled value, unscaled value, kind, has a $, a scale or a unit beside
    it) for every quantity in `text`, digits or words. The kind is "$" for
    money, "%" for a share, else ""."""
    out = []
    for m in _QTY.finditer(text.lower()):
        base = _value(m.group("num"))
        scale = _SCALES.get(m.group("scale") or "", 1)
        rest = m.group("rest").lstrip()
        kind = "$" if m.group("cur") else "%" if rest.startswith(_SHARE) else ""
        unit = bool(kind) or bool(m.group("scale")) or rest.startswith(UNIT_AFTER)
        out.append((_canon(base * scale), _canon(base), kind, unit))
    return out


def _numbers(text: str, kind: str | None = None) -> set[str]:
    return {
        v
        for scaled, plain, k, _ in _quantities(text)
        if kind is None or k == kind
        for v in (scaled, plain)
    }


def fact_figures(facts: str) -> str:
    """The parts of the facts block whose numbers may be repeated: everything
    but URLs, and for each source only its curated quote, not its title."""
    keep = []
    for line in facts.splitlines():
        if line.startswith("[S") and " | quote: " in line:
            line = line.split(" | quote: ", 1)[1]
        keep.append(_URL.sub(" ", line))
    return "\n".join(keep)


def foreign_numbers(text: str, facts: str) -> set[str]:
    """Figures in `text` the facts do not contain. A bare count of ten or less
    ("two campuses") is exempt; one beside a $, a %, a scale word or a unit is
    not. A multiplier word ("half", "double") counts unless the facts use it."""
    allowed_text = fact_figures(facts)
    allowed = {k: _numbers(allowed_text, k or None) for k in ("", "$", "%")}
    out = set()
    for scaled, _, kind, unit in _quantities(text):
        # Money and shares must appear as money and shares: "5 miles" is no "$5".
        if scaled in allowed[kind] or (not unit and scaled in SMALL_NUMBERS):
            continue
        out.add(f"{kind}{scaled}" if kind == "$" else f"{scaled}{kind}")
    allowed_words = {m.group(1) for m in _MULTIPLIERS.finditer(allowed_text.lower())}
    out |= {m.group(1) for m in _MULTIPLIERS.finditer(text.lower())} - allowed_words
    return out


# --- the facts block --------------------------------------------------------


def _redact(text: str, zip5: str) -> str:
    if not zip5:
        return text
    return text.replace(f"ZIP {zip5}", "this ZIP").replace(zip5, "this ZIP")


def facts_block(scenario: dict[str, Any], sources: dict[str, dict[str, Any]]) -> str:
    inputs = scenario.get("inputs") or {}
    zip5 = str(inputs.get("zip") or "")
    place = scenario.get("place") or {}
    base = scenario.get("baseline") or {}
    where = ", ".join(
        p
        for p in (
            f"{place.get('county')} County" if place.get("county") else "",
            place.get("state"),
        )
        if p
    )
    cooling = "evaporative" if inputs.get("cooling") == "evaporative" else "closed-loop"
    parts = [
        "FACTS (the engine's; use these numbers as written and no others)",
        f"Scenario: a hypothetical {inputs.get('mw', 0):,} MW data-center campus with {cooling} "
        f"cooling in {where or 'this area'}. {scenario.get('disclosure', '')}",
    ]
    count = base.get("facility_count")
    if count is not None:
        names = [f.get("name") for f in base.get("facilities") or [] if isinstance(f, dict)]
        named = f" ({', '.join(n for n in names[:5] if n)})" if names else ""
        parts.append(f"Data centers already within 5 miles: {count}{named}.")
    utility = base.get("utility")
    if isinstance(utility, dict) and utility.get("name"):
        customers = utility.get("customers")
        parts.append(
            f"Serving utility: {utility['name']}"
            + (f", {customers:,} customers." if isinstance(customers, int) else ".")
        )
    tariff = base.get("tariff")
    if isinstance(tariff, dict):
        parts.append(
            f"Large-load tariff: {tariff.get('large_load_tariff')}"
            + (f", {tariff['name']}" if tariff.get("name") else "")
            + (
                f"; protects households: {tariff['protects_households']}"
                if tariff.get("protects_households") is not None
                else ""
            )
            + "."
        )
    parts.append("Modelled lines (each with the engine's working):")
    for line in scenario.get("lines") or []:
        text = f"- {line.get('text', '')} Working: {line.get('basis', '')}"
        parts.append(_redact(text, zip5))
    parts.append("SOURCES (cite only these, by exact URL, with the exact quote):")
    for n, (url, s) in enumerate(list(sources.items())[:MAX_SOURCES], start=1):
        quotes = " | ".join(f'"{q}"' for q in s["quotes"]) or "(no curated quote)"
        parts.append(f"[S{n}] {s['title']} | {url} | quote: {quotes}")
    return "\n".join(parts)


def interpret_prompt(facts: str) -> str:
    return (
        f"{facts}\n\nWrite the three sentences and their claims. Numbers only from the facts above."
    )


# --- the draft ----------------------------------------------------------------


def _keep_claim(
    c: dict[str, Any], sources: dict[str, dict[str, Any]], facts: str
) -> dict[str, Any] | None:
    """The claim with the source's own title and curated quote, or None."""
    url = c.get("source_url")
    src = sources.get(url) if isinstance(url, str) else None
    if src is None:
        return None
    quote = _norm(str(c.get("quote") or ""))
    if len(quote) < 12:
        return None
    # Only a page with a curated quote can be cited: the model's own words
    # never stand in as a quotation.
    match = next((q for q in src["quotes"] if quote in _norm(q) or _norm(q) in quote), None)
    if match is None:
        return None
    quote_out = match
    text = str(c.get("text") or "").strip()
    if not text or foreign_numbers(text, f"{facts}\n{quote_out}"):
        return None
    return {**c, "text": text, "source_title": src["title"], "quote": quote_out}


async def draft_interpretation(
    provider: LLMProvider, scenario: dict[str, Any]
) -> DraftResult | SectionFailure:
    """One structured draft (one retry). Claims citing a page outside the
    scenario's sources, or a quote that is not that page's, are dropped; a
    summary with a figure the engine did not give fails the attempt."""
    _, strict = interpret_schemas()
    # Only pages with a curated quote are offered for citing.
    sources = {u: s for u, s in scenario_sources(scenario).items() if s["quotes"]}
    facts = facts_block(scenario, sources)
    messages = [
        {"role": "system", "content": INTERPRET_PROMPT},
        {"role": "user", "content": interpret_prompt(facts)},
    ]
    last: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            raw = await provider.complete_structured(messages, strict, "draft_scenario")
            draft = validate_interpretation(raw)
            if foreign_numbers(draft["summary"], facts):
                raise ValidationError("the summary carries a figure the facts do not")
            break
        except (LLMError, ValidationError) as exc:
            last = exc
            log_event(
                "draft_failed",
                section=SECTION,
                attempt=attempt,
                kind=exc.__class__.__name__,
                reason=str(exc)[:200],
            )
    else:
        return SectionFailure(SECTION, _reason(last))

    kept = [k for c in draft.get("claims", []) if (k := _keep_claim(c, sources, facts))]
    dropped = len(draft.get("claims", [])) - len(kept)
    if dropped:
        log_event("interpret_claims_dropped", dropped=dropped, kept=len(kept))
    return DraftResult(
        section_id=SECTION,
        confidence=max(0.0, min(1.0, float(draft["confidence"]))),
        summary=draft["summary"].strip(),
        gap=None,
        card_line=None,
        extra={"dropped": dropped},
        claims=kept[:MAX_CLAIMS],
    )


def _reason(exc: Exception | None) -> str:
    if isinstance(exc, ValidationError):
        return "The model's paragraph did not keep to the engine's figures, so it was not used."
    if isinstance(exc, LLMError):
        text = str(exc)
        if "truncated" in text:
            return "The model ran out of room before finishing the paragraph."
        if "timed out" in text.lower() or "Timeout" in text:
            return "The model did not answer in time."
        return "The drafting model was unavailable."
    return "The paragraph could not be drafted."
