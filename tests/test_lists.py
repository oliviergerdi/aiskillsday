"""PRD 0002: lists matched by key."""

from nparity.config import ListRule, NoiseRules
from nparity.diff import diff
from nparity.jsonpath import generic, value_at
from nparity.lists import NO_KEY, membership, stable_key
from nparity.models import HttpResult


def kinds(a, b, keys=None):
    return {(d.path, d.kind, str(d.old), str(d.new))
            for d in diff(HttpResult(status=200, body=a), HttpResult(status=200, body=b), keys)}


def test_key_detection():
    assert stable_key([{"id": 1}], [{"id": 2}]) == "id"
    assert stable_key([{"uuid": "a", "id": 1}, {"uuid": "b", "id": 1}], [{"uuid": "c", "id": 2}]) == "uuid"
    assert stable_key([{"id": 1}, {"id": 1}], [{"id": 2}]) is None           # duplicated
    assert stable_key([{"id": 1}, {"name": "x"}], [{"id": 2}]) is None       # missing on one item
    assert stable_key([1, 2], [2, 3]) is None                                # not objects
    assert stable_key([], []) is None
    assert stable_key([{"id": 1}], [{"id": 1}], NO_KEY) is None
    assert stable_key([{"sku": "a"}], [{"sku": "b"}], "sku") == "sku"


def test_membership_is_two_findings_not_field_noise():
    """Review focus 2."""
    old = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}]
    new = [{"id": 2, "name": "B"}, {"id": 4, "name": "d"}]
    assert kinds(old, new) == {
        ("$", "items_removed", "[1, 3]", "None"),
        ("$", "items_added", "None", "[4]"),
        ("$[id=2].name", "changed", "b", "B"),
    }
    assert membership(old, new) == ("id", [1, 3], [4])


def test_positional_override():
    keys = NoiseRules(lists=[ListRule(endpoint="E", path="$", key=None)]).list_keys("E")
    assert kinds([{"id": 1}], [{"id": 2}], keys) == {("$[0].id", "changed", "1", "2")}


def test_paths():
    body = {"items": [{"id": 10, "name": "x"}, {"id": "a", "name": "y"}]}
    assert value_at(body, "$.items[id=10].name") == "x"
    assert value_at(body, "$.items[id=a].name") == "y"
    assert generic("$.items[id=10].name") == generic("$.items[3].name") == "$.items[*].name"


def test_petstore_findbystatus_capture():
    """Task 4: the real captured Petstore lists become membership findings, not positional field noise."""
    import json

    from nparity.config import NoiseRules
    from nparity.normalise import normalise

    load = lambda f: json.loads(open(f"samples/api-versions/{f}").read())   # noqa: E731
    old = HttpResult(status=200, body=load("petstore_v2_findByStatus.json"))
    new = HttpResult(status=200, body=load("petstore_v3_findByStatus.json"))
    o, n, _ = normalise("GET /pet/findByStatus", old, new, NoiseRules())
    diffs = diff(o, n)
    kinds_at_root = {d.kind for d in diffs if d.path == "$"}
    assert kinds_at_root <= {"items_removed", "items_added"} and kinds_at_root
    assert all(d.path == "$" or d.path.startswith("$[id=") for d in diffs)
