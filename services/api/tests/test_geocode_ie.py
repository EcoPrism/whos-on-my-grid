"""Ireland's geocoder: OpenStreetMap Nominatim behind httpx.MockTransport, no
network. The responses under tests/fixtures/nominatim are live answers saved on
2026-10-29 (three reconstructed ones say so in their `_note`).

What it pins: the point is snapped to 3 decimals; the display line is built
from place components (never a house number, a full Eircode or a POI name);
the planning authority and the Eircode routing key; one retry for an Eircode
that finds nothing; one /reverse when the county is missing; errors carry only
the exception's class name and no log line holds the address or the point."""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import REPO_ROOT
from app.geocode import (
    EIRCODE,
    USER_AGENT,
    FakeGeocoder,
    GeocodeResult,
    GeocodeUnavailable,
    NominatimGeocoder,
    _Throttle,
    brief_id_for,
    ie_result,
    normalise,
    routing_key,
)
from app.regions import load_ie_fixtures

FIXTURES = Path(__file__).parent / "fixtures" / "nominatim"
EVAL_IE = REPO_ROOT / "eval" / "ie" / "addresses.json"
FULL_EIRCODE = re.compile(r"\b(?:[AC-FHKNPRTV-Y]\d{2}|D6W)\s?[0-9AC-FHKNPRTV-Y]{4}\b", re.I)
HOUSE_NUMBER = re.compile(r"(?:^|,\s*)\d+[A-Za-z]?\s")


def fixture(name: str) -> Any:
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)["response"]


def decimals(x: float) -> int:
    text = repr(x)
    return len(text.split(".")[1]) if "." in text else 0


class Recorder:
    """A MockTransport handler: answers by (path, q) and records each request."""

    def __init__(
        self,
        search: dict[str, Any] | None = None,
        reverse: Any = None,
        *,
        status: int = 200,
        raise_exc: Exception | None = None,
    ) -> None:
        self.search = {normalise(k): v for k, v in (search or {}).items()}
        self.reverse = reverse
        self.status = status
        self.raise_exc = raise_exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "x"})
        if request.url.path.endswith("/reverse"):
            return httpx.Response(200, json=self.reverse or {})
        q = request.url.params.get("q", "")
        return httpx.Response(200, json=self.search.get(normalise(q), []))

    def paths(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[-1] for r in self.requests]

    def queries(self) -> list[str]:
        return [r.url.params.get("q", "") for r in self.requests if "search" in r.url.path]


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def geocoder(rec: Recorder, *, clock: FakeClock | None = None, **kw: Any) -> NominatimGeocoder:
    clock = clock or FakeClock()
    return NominatimGeocoder(
        "https://nominatim.example.org",
        transport=httpx.MockTransport(rec),
        throttle=_Throttle(clock, clock.sleep),
        timeout=5.0,
        **kw,
    )


def assert_safe(r: GeocodeResult) -> None:
    assert r.country == "IE"
    assert decimals(r.lat) <= 3 and decimals(r.lon) <= 3
    assert not FULL_EIRCODE.search(r.display), r.display
    assert not HOUSE_NUMBER.search(r.display), r.display
    assert r.postal_code == "" or re.fullmatch(r"(?:[AC-FHKNPRTV-Y]\d{2}|D6W)", r.postal_code)


# --- the Eircode ----------------------------------------------------------------------


async def test_eircode_resolves_to_the_routing_key_and_authority() -> None:
    rec = Recorder({"D15 T1FD": fixture("eircode_d15t1fd")})
    r = await geocoder(rec).geocode("D15 T1FD")
    assert r is not None
    assert (r.region_code, r.county, r.admin_county, r.postal_code) == (
        "IE-D",
        "Fingal",
        "Dublin",
        "D15",
    )
    assert r.display == "Blanchardstown, Fingal, Co. Dublin, D15"
    assert (r.lat, r.lon) == (53.396, -6.39)  # live 53.3957840, -6.3902944
    assert_safe(r)
    assert rec.paths() == ["search"]  # county and ISO code present: no reverse


async def test_eircode_that_finds_nothing_is_retried_once_as_its_routing_key() -> None:
    rec = Recorder({"D15": fixture("dublin_15")}, reverse=fixture("dublin_15_reverse"))
    r = await geocoder(rec).geocode("D15 T1FD")
    assert rec.queries() == ["D15 T1FD", "D15"]
    assert rec.paths() == ["search", "search", "reverse"]
    assert r is not None and r.postal_code == "D15" and r.county == "Fingal"
    assert r.display == "Fingal, Co. Dublin, D15"
    assert_safe(r)


async def test_routing_key_retry_keeps_the_rest_of_the_text() -> None:
    rec = Recorder({"Blanchardstown Centre, D15": fixture("blanchardstown_centre")})
    r = await geocoder(rec).geocode("Blanchardstown Centre, D15 T1FD")
    assert rec.queries() == ["Blanchardstown Centre, D15 T1FD", "Blanchardstown Centre, D15"]
    assert r is not None
    # The hit has no postcode; the routing key the user typed fills it.
    assert r.display == "Blanchardstown, Fingal, Co. Dublin, D15" and r.postal_code == "D15"


async def test_bare_routing_key_retry_accepts_only_a_postal_hit() -> None:
    """'D15' alone could match a road or a bus route; only a postcode or postal
    district answers it."""
    rec = Recorder({"D15": fixture("m3_parkway")})
    assert await geocoder(rec).geocode("D15 T1FD") is None
    assert rec.queries() == ["D15 T1FD", "D15"]


async def test_no_retry_without_an_eircode() -> None:
    rec = Recorder({})
    assert await geocoder(rec).geocode("Nowhere Street, Atlantis") is None
    assert rec.paths() == ["search"]


# --- postal district and reverse ------------------------------------------------------


async def test_postal_district_gets_one_reverse_for_county_and_code() -> None:
    rec = Recorder({"Dublin 15": fixture("dublin_15")}, reverse=fixture("dublin_15_reverse"))
    r = await geocoder(rec).geocode("Dublin 15")
    assert rec.paths() == ["search", "reverse"]
    rev = rec.requests[1].url.params
    assert rev["zoom"] == "10" and rev["accept-language"] == "en"
    assert r is not None
    assert (r.region_code, r.county, r.admin_county, r.postal_code) == (
        "IE-D",
        "Fingal",
        "Dublin",
        "D15",
    )
    assert_safe(r)


# --- names and authorities ------------------------------------------------------------


async def test_galway_irish_city_name_is_mapped_to_english() -> None:
    rec = Recorder({"Galway City Hall": fixture("galway_city_hall_irish")})
    r = await geocoder(rec).geocode("Galway City Hall")
    assert r is not None
    assert r.county == "Galway City" and r.region_code == "IE-G" and r.admin_county == "Galway"
    assert r.display == "Galway, Co. Galway, H91"
    assert "Gaillimhe" not in r.display + r.matched
    assert_safe(r)


async def test_cork_city() -> None:
    rec = Recorder({"Anglesea Street, Cork": fixture("cork_anglesea_street")})
    r = await geocoder(rec).geocode("Anglesea Street, Cork")
    assert r is not None
    assert (r.county, r.region_code, r.postal_code) == ("Cork City", "IE-CO", "T12")
    assert r.display == "Cork, Co. Cork, T12"
    assert_safe(r)


async def test_meath() -> None:
    rec = Recorder({"M3 Parkway railway station": fixture("m3_parkway")})
    r = await geocoder(rec).geocode("M3 Parkway railway station")
    assert r is not None
    assert (r.county, r.region_code, r.admin_county) == ("Meath", "IE-MH", "Meath")
    assert r.display == "Pace, Co. Meath"
    assert "M3 Parkway" not in r.display
    assert_safe(r)


@pytest.mark.parametrize(
    ("name", "display", "never"),
    [
        ("ikea_ballymun_bus_stop", "Saint Margaret's Road, Fingal, Co. Dublin", "IKEA"),
        ("citywest_restaurant", "Saggart, South Dublin, Co. Dublin", "Rocket"),
        ("clondalkin_civic_offices", "Clondalkin, South Dublin, Co. Dublin, D22", "Civic"),
        ("limerick_merchants_quay", "Limerick, Co. Limerick, V94", "John's B"),
        ("wood_quay", "Dublin, Co. Dublin, D08", "Wood Quay"),
        ("blanchardstown_centre", "Blanchardstown, Fingal, Co. Dublin", "Centre"),
    ],
)
async def test_poi_hits_display_from_components(name: str, display: str, never: str) -> None:
    hit = fixture(name)
    rec = Recorder({"q": hit})
    r = await geocoder(rec).geocode("q")
    assert r is not None
    assert r.display == display
    assert never not in r.display
    assert_safe(r)


def test_dublin_city_and_county_authorities() -> None:
    base = {"county": "County Dublin", "ISO3166-2-lvl6": "IE-D", "country_code": "ie"}
    city = ie_result({**base, "city": "Dublin", "road": "Wood Quay"}, 53.34, -6.27)
    dlr = ie_result({**base, "municipality": "Dun Laoghaire-Rathdown", "town": "Dundrum"}, 53, -6)
    limerick = ie_result(
        {"county": "County Limerick", "city": "Limerick", "country_code": "ie"}, 52.6, -8.6
    )
    assert city is not None and city.county == "Dublin City"
    assert dlr is not None and dlr.county == "Dún Laoghaire-Rathdown"
    assert dlr.display == "Dundrum, Dún Laoghaire-Rathdown, Co. Dublin"
    assert limerick is not None and limerick.county == "Limerick"


def test_roadless_hits_in_one_town_get_different_brief_ids() -> None:
    """'Blanchardstown Centre' and the Blanchardstown town node: same components,
    no road, no postcode, about 1.2 km apart. They must not share a brief."""
    block = {
        "town": "Blanchardstown",
        "municipality": "Fingal",
        "county": "County Dublin",
        "ISO3166-2-lvl6": "IE-D",
        "country_code": "ie",
    }
    centre = ie_result(block, 53.393, -6.392)
    town = ie_result(block, 53.384, -6.383)
    assert centre is not None and town is not None
    assert centre.display == town.display
    assert brief_id_for(centre.matched, "IE") != brief_id_for(town.matched, "IE")
    # A full Eircode already names one address: no point is added.
    exact = ie_result({**block, "postcode": "D15 T1FD"}, 53.393, -6.392)
    assert exact is not None and exact.matched.endswith("D15 T1FD")


def test_house_number_reaches_matched_never_display() -> None:
    r = ie_result(
        {
            "house_number": "12",
            "road": "Main Street",
            "town": "Blanchardstown",
            "municipality": "Fingal",
            "county": "County Dublin",
            "ISO3166-2-lvl6": "IE-D",
            "postcode": "D15 T1FD",
            "country_code": "ie",
        },
        53.39327,
        -6.39204,
    )
    assert r is not None
    assert r.display == "Blanchardstown, Fingal, Co. Dublin, D15"
    assert r.matched == "12 Main Street, Blanchardstown, Co. Dublin, D15 T1FD"
    assert (r.lat, r.lon) == (53.393, -6.392)


@pytest.mark.parametrize(
    ("postcode", "district", "key"),
    [
        ("D15 T1FD", None, "D15"),
        ("d15t1fd", None, "D15"),
        ("H91 X4K8", None, "H91"),
        ("D15", None, "D15"),
        (None, "Dublin 15", "D15"),
        (None, "Dublin 8", "D08"),
        (None, "Dublin 6W", "D6W"),
        ("Dublin 22", None, "D22"),
        ("BT1 1AA", None, ""),
        (None, None, ""),
    ],
)
def test_routing_key(postcode: str | None, district: str | None, key: str) -> None:
    assert routing_key(postcode, district) == key


def test_eircode_pattern() -> None:
    for ok in ("D15 T1FD", "D15T1FD", "h91 x4k8"):
        assert EIRCODE.match(ok)
    for bad in ("D15", "20147", "BT1 1AA", "B15 T1FD"):
        assert not EIRCODE.match(bad)


# --- rejection ------------------------------------------------------------------------


async def test_coarse_hit_is_rejected() -> None:
    hit = [{**fixture("m3_parkway")[0], "place_rank": 10, "type": "county"}]
    assert await geocoder(Recorder({"q": hit})).geocode("q") is None


async def test_non_irish_hit_is_rejected() -> None:
    hit = fixture("m3_parkway")[0]
    gb = [{**hit, "address": {**hit["address"], "country_code": "gb"}}]
    assert await geocoder(Recorder({"q": gb})).geocode("q") is None


async def test_empty_text_makes_no_request() -> None:
    rec = Recorder({})
    assert await geocoder(rec).geocode("  ,, ") is None
    assert rec.requests == []


# --- errors never carry the address ---------------------------------------------------

SECRET = "Blanchardstown Centre, Dublin 15"


@pytest.mark.parametrize(
    ("rec", "name"),
    [
        (Recorder(status=429), "HTTPStatusError"),
        (Recorder(status=503), "HTTPStatusError"),
        (Recorder(raise_exc=httpx.ReadTimeout("timed out")), "ReadTimeout"),
        (Recorder(raise_exc=httpx.ConnectError("refused")), "ConnectError"),
    ],
)
async def test_errors_are_unavailable_with_the_class_name_only(
    rec: Recorder, name: str, caplog: pytest.LogCaptureFixture
) -> None:
    # main.py quiets httpx's own request lines (they hold the URL); do the same here
    # and capture everything the app itself logs.
    for noisy in ("httpx", "httpcore"):
        caplog.set_level(logging.WARNING, logger=noisy)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GeocodeUnavailable) as err:
        await geocoder(rec).geocode(SECRET)
    assert str(err.value) == name
    assert err.value.__cause__ is None and err.value.__suppress_context__
    logged = caplog.text
    assert "Blanchardstown" not in logged and "Dublin" not in logged
    assert "lat=" not in logged and "q=" not in logged


async def test_reverse_error_is_unavailable_without_the_point(
    caplog: pytest.LogCaptureFixture,
) -> None:
    for noisy in ("httpx", "httpcore"):
        caplog.set_level(logging.WARNING, logger=noisy)
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reverse"):
            return httpx.Response(503)
        return httpx.Response(200, json=fixture("dublin_15"))

    g = NominatimGeocoder(
        "https://nominatim.example.org",
        transport=httpx.MockTransport(handler),
        throttle=_Throttle(FakeClock(), FakeClock().sleep),
        timeout=5.0,
    )
    with pytest.raises(GeocodeUnavailable) as err:
        await g.geocode("Dublin 15")
    assert str(err.value) == "HTTPStatusError"
    assert "53.39" not in caplog.text and "lat=" not in caplog.text


async def test_unreadable_json_is_unavailable() -> None:
    g = NominatimGeocoder(
        "https://nominatim.example.org",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")),
        throttle=_Throttle(FakeClock(), FakeClock().sleep),
        timeout=5.0,
    )
    with pytest.raises(GeocodeUnavailable) as err:
        await g.geocode("Galway")
    assert str(err.value) == "JSONDecodeError"


# --- request shape, throttle, cache ---------------------------------------------------


async def test_request_carries_ua_language_country_and_no_email_by_default() -> None:
    rec = Recorder({"Galway City Hall": fixture("galway_city_hall_irish")})
    await geocoder(rec).geocode("Galway City Hall")
    req = rec.requests[0]
    assert req.headers["user-agent"] == USER_AGENT
    p = req.url.params
    assert p["accept-language"] == "en" and p["countrycodes"] == "ie"
    assert p["format"] == "jsonv2" and p["addressdetails"] == "1" and p["limit"] == "1"
    assert "email" not in p
    assert str(req.url).startswith("https://nominatim.example.org/search?")


async def test_email_is_sent_when_set() -> None:
    rec = Recorder({"Dublin 15": fixture("dublin_15")}, reverse=fixture("dublin_15_reverse"))
    await geocoder(rec, email="ops@example.org").geocode("Dublin 15")
    assert [r.url.params.get("email") for r in rec.requests] == ["ops@example.org"] * 2


async def test_throttle_spaces_requests_by_the_interval() -> None:
    clock = FakeClock()
    rec = Recorder({"Dublin 15": fixture("dublin_15")}, reverse=fixture("dublin_15_reverse"))
    g = geocoder(rec, clock=clock, min_interval=1.0)
    await g.geocode("Dublin 15")  # search + reverse
    clock.now += 0.25
    await g.geocode("Galway City Hall")
    assert clock.slept == [1.0, 0.75]


async def test_throttle_is_shared_per_base_url() -> None:
    from app.geocode import _throttle_for

    a = NominatimGeocoder("https://n.example.org/")
    b = NominatimGeocoder("https://n.example.org")
    c = NominatimGeocoder("https://other.example.org")
    assert a.throttle is b.throttle is _throttle_for("https://n.example.org")
    assert c.throttle is not a.throttle


async def test_cache_answers_repeats_and_evicts_the_oldest() -> None:
    rec = Recorder(
        {
            "Galway City Hall": fixture("galway_city_hall_irish"),
            "Anglesea Street, Cork": fixture("cork_anglesea_street"),
            "M3 Parkway railway station": fixture("m3_parkway"),
        }
    )
    g = geocoder(rec, cache_size=2)
    first = await g.geocode("Galway City Hall")
    assert await g.geocode("galway  city hall!") == first
    assert len(rec.requests) == 1
    await g.geocode("Anglesea Street, Cork")
    await g.geocode("M3 Parkway railway station")  # evicts Galway
    await g.geocode("Anglesea Street, Cork")  # still cached
    assert len(rec.requests) == 3
    await g.geocode("Galway City Hall")
    assert len(rec.requests) == 4


async def test_errors_are_not_cached() -> None:
    rec = Recorder(status=503)
    g = geocoder(rec)
    for _ in range(2):
        with pytest.raises(GeocodeUnavailable):
            await g.geocode("Galway City Hall")
    assert len(rec.requests) == 2


# --- ids and the fake -----------------------------------------------------------------


def test_irish_brief_id_is_prefixed_by_country() -> None:
    matched = "Blanchardstown, Fingal, Co. Dublin, D15"
    want = hashlib.sha256(("ie|" + normalise(matched)).encode()).hexdigest()[:16]
    assert brief_id_for(matched, "IE") == want == "ffefa78202dceea9"
    assert brief_id_for(matched, "US") != want


def _eval_rows() -> list[dict[str, Any]]:
    with open(EVAL_IE, encoding="utf-8") as f:
        return json.load(f)["addresses"]


@pytest.mark.parametrize("row", _eval_rows(), ids=lambda r: r["id"])
async def test_every_eval_row_round_trips_through_the_fake(row: dict[str, Any]) -> None:
    g = FakeGeocoder(by_address=load_ie_fixtures())
    r = await g.geocode(row["address"])
    assert r is not None
    block = row["geocode"]
    for key, value in block.items():
        assert getattr(r, key) == value, key
    assert r.country == "IE"
    assert_safe(r)


# The fixture each eval row's geocode block was taken from: the parser must still
# give the same block (all but `matched`, which the fake sets to the display line).
EVAL_FROM_FIXTURE = {
    "ie_blanchardstown": "blanchardstown_centre",
    "ie_clonee": "m3_parkway",
    "ie_clondalkin": "clondalkin_civic_offices",
    "ie_citywest": "citywest_restaurant",
    "ie_ballymun": "ikea_ballymun_bus_stop",
    "ie_dublin_city": "wood_quay",
    "ie_galway": "galway_city_hall_irish",
    "ie_cork": "cork_anglesea_street",
    "ie_limerick": "limerick_merchants_quay",
}


@pytest.mark.parametrize(("row_id", "name"), sorted(EVAL_FROM_FIXTURE.items()))
async def test_eval_geocode_blocks_match_the_parser(row_id: str, name: str) -> None:
    row = next(r for r in _eval_rows() if r["id"] == row_id)
    r = await geocoder(Recorder({"q": fixture(name)})).geocode("q")
    assert r is not None
    for key, value in row["geocode"].items():
        if key != "matched":
            assert getattr(r, key) == value, key


async def test_fake_answers_the_fixture_typed_forms() -> None:
    g = FakeGeocoder(by_address=load_ie_fixtures())
    for text in ("Blanchardstown Centre, Dublin 15", "Blanchardstown, Fingal, Co. Dublin, D15"):
        r = await g.geocode(text)
        assert r is not None and brief_id_for(r.matched, "IE") == "ffefa78202dceea9"
    assert await g.geocode("21715 Filigree Ct, Ashburn, VA") is None


def test_missing_test_set_still_has_the_fixture(tmp_path: Path) -> None:
    table = load_ie_fixtures(tmp_path / "absent.json")
    assert set(table) == {
        "Blanchardstown, Fingal, Co. Dublin, D15",
        "Blanchardstown Centre, Dublin 15",
    }


def test_fixtures_carry_no_house_number() -> None:
    for path in FIXTURES.glob("*.json"):
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        assert "house_number" not in json.dumps(body["response"]), path.name
