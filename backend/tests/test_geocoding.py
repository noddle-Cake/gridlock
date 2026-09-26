import asyncio

from hypothesis import given
from hypothesis import strategies as st

from app.services.geocoding import (
    MAX_ATTEMPTS,
    Candidate,
    GeocodingService,
    county_centroid,
    dedupe_candidates,
)
from tests.conftest import FakeGeocoder

# One attempt outcome: "timeout", "error", or a candidate count.
attempts = st.lists(
    st.one_of(st.sampled_from(["timeout", "error"]), st.integers(0, 4)),
    min_size=MAX_ATTEMPTS, max_size=MAX_ATTEMPTS + 2,
)


class ScriptedGeocoder:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def resolve(self, name):
        outcome = self.script[self.calls]
        self.calls += 1
        if outcome == "timeout":
            await asyncio.sleep(10)  # longer than the (shrunk) per-attempt timeout
        if outcome == "error":
            raise ConnectionError("geocoder down")
        return [Candidate(40.0 + i, -77.0 - i) for i in range(outcome)]


# Feature: gridmerge, Property 9: Geocoding resolution outcome
@given(attempts)
def test_resolution_outcome(script):
    geocoder = ScriptedGeocoder(script)
    service = GeocodingService(geocoder, attempt_timeout=0.001)
    outcome = asyncio.run(service.resolve_with_retry("Hanover, PA"))

    assert geocoder.calls <= MAX_ATTEMPTS
    completed = [s for s in script[:MAX_ATTEMPTS] if isinstance(s, int)]
    if not completed:
        # All attempts failed or timed out: review, geom unset.
        assert geocoder.calls == MAX_ATTEMPTS
        assert outcome.requires_review and not outcome.has_geom
    elif completed[0] == 1:
        assert outcome.has_geom and not outcome.requires_review
        assert (outcome.lat, outcome.lng) == (40.0, -77.0)
    else:
        # Ambiguous (>1) or no match: unresolved, review, geom unset.
        assert outcome.requires_review and not outcome.has_geom


def test_single_candidate_town_resolves_to_point():
    geocoder = FakeGeocoder({"Gettysburg, PA": [Candidate(39.83, -77.23)]})
    out = asyncio.run(GeocodingService(geocoder).geocode("Gettysburg, PA"))
    assert (out.lat, out.lng) == (39.83, -77.23)
    assert out.approximate is False and out.requires_review is False


def test_county_reference_uses_centroid_and_is_approximate():
    geocoder = FakeGeocoder()
    out = asyncio.run(GeocodingService(geocoder).geocode("Adams County, PA", kind="county"))
    assert out.approximate is True and out.has_geom
    assert abs(out.lat - 39.87) < 0.2 and abs(out.lng + 77.22) < 0.2
    assert geocoder.calls == []  # offline gazetteer, no hosted call


def test_county_state_from_hint_and_full_name():
    assert len(county_centroid("York County", "PA")) == 1
    assert len(county_centroid("York County, Pennsylvania")) == 1
    assert len(county_centroid("York County")) > 1  # ambiguous without a state


def test_ambiguous_county_goes_to_review():
    out = asyncio.run(GeocodingService(FakeGeocoder()).geocode("Washington County"))
    assert out.requires_review and not out.has_geom


def test_substation_falls_back_to_town_approximately():
    geocoder = FakeGeocoder({"Hanover, PA": [Candidate(39.8, -76.98)]})
    out = asyncio.run(GeocodingService(geocoder).geocode("Hanover Substation, PA"))
    assert out.has_geom and out.approximate


def test_empty_reference_requires_review():
    out = asyncio.run(GeocodingService(FakeGeocoder()).geocode(""))
    assert out.requires_review and not out.has_geom


def test_dedupe_merges_nearby_candidates():
    cands = [Candidate(40.0, -77.0), Candidate(40.001, -77.001), Candidate(41.0, -77.0)]
    assert len(dedupe_candidates(cands)) == 2
