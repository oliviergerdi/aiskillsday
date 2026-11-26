"""PRD 0002: format-preserving default noise rules."""

from nparity.config import NoiseRules
from nparity.diff import diff
from nparity.models import HttpResult
from nparity.normalise import format_token, normalise

RULES = NoiseRules()


def res(body):
    return HttpResult(status=200, body=body)


def run(a, b, rules=RULES, endpoint="GET /x"):
    o, n, noise = normalise(endpoint, res(a), res(b), rules)
    return o.body, n.body, [(x.path, x.rule) for x in noise], {(d.path, d.kind) for d in diff(o, n)}


def test_tokens():
    assert format_token("2026-11-26T10:00:00Z", None, RULES)[0] == "<datetime tz=Z precision=s>"
    assert format_token("2026-11-26T10:00:00.123+0200", None, RULES)[0] == "<datetime tz=+02:00 precision=ms>"
    assert format_token("2026-11-26 10:00", None, RULES)[0] == "<datetime tz=naive precision=min>"
    assert format_token("2026-11-26", None, RULES)[0] == "<date>"
    assert format_token("0f8fad5b-d9cb-469f-a165-70867728950e", None, RULES)[0] == "<uuid v4>"
    assert format_token(1764150000, "createdAt", RULES)[0] == "<epoch s>"
    assert format_token(1764150000000, "updated", RULES)[0] == "<epoch ms>"
    assert format_token(1764150000, "count", RULES) is None          # epoch only in timestamp-named fields
    assert format_token("hello", None, RULES) is None
    assert format_token(True, "createdAt", RULES) is None


def test_same_format_different_value_is_noise():
    a, b, noise, diffs = run({"shipDate": "2026-11-26T10:00:00Z", "id": "0f8fad5b-d9cb-469f-a165-70867728950e"},
                             {"shipDate": "2026-11-26T11:30:05Z", "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7"})
    assert diffs == set()
    assert set(noise) == {("$.shipDate", "datetime (format kept)"), ("$.id", "uuid (format kept)")}


def test_timezone_change_survives():
    """Review focus 1."""
    _, _, noise, diffs = run({"at": "2026-11-26T10:00:00Z"}, {"at": "2026-11-26T12:00:00+02:00"})
    assert diffs == {("$.at", "changed")} and noise == []


def test_precision_epoch_and_null_changes_survive():
    assert run({"t": "2026-11-26T10:00:00Z"}, {"t": "2026-11-26T10:00:00.000Z"})[3] == {("$.t", "changed")}
    assert run({"createdAt": "2026-11-26T10:00:00Z"}, {"createdAt": 1764150000})[3] == {("$.createdAt", "type_changed")}
    assert run({"t": "2026-11-26T10:00:00Z"}, {"t": None})[3] == {("$.t", "type_changed")}


def test_equal_values_untouched():
    a, b, noise, diffs = run({"t": "2026-11-26T10:00:00Z"}, {"t": "2026-11-26T10:00:00Z"})
    assert a == b == {"t": "2026-11-26T10:00:00Z"} and noise == [] and diffs == set()


def test_inside_lists_and_keyed_items():
    a = {"items": [{"id": 1, "at": "2026-11-26T10:00:00Z"}, {"id": 2, "at": "2026-11-26T10:00:01Z"}]}
    b = {"items": [{"id": 2, "at": "2026-11-26T11:00:01Z"}, {"id": 1, "at": "2026-11-26T11:00:00Z"}]}
    _, _, noise, diffs = run(a, b)
    assert diffs == set()
    assert set(noise) == {("$.items", "order (matched by id)"), ("$.items[*].at", "datetime (format kept)")}


def test_defaults_can_be_switched_off():
    off = NoiseRules(defaults={"datetime": False})
    assert run({"t": "2026-11-26T10:00:00Z"}, {"t": "2026-11-26T11:00:00Z"}, off)[3] == {("$.t", "changed")}
