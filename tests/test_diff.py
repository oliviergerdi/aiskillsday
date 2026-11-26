from nparity.diff import diff
from nparity.models import HttpResult


def kinds(a, b, sa=200, sb=200):
    return {(d.path, d.kind) for d in diff(HttpResult(status=sa, body=a), HttpResult(status=sb, body=b))}


def test_changed_number():
    (d,) = diff(HttpResult(status=200, body={"total": 10.01}), HttpResult(status=200, body={"total": 10.0}))
    assert (d.path, d.kind, d.old, d.new) == ("$.total", "changed", 10.01, 10.0)


def test_status():
    assert kinds({}, {}, 200, 201) == {("status", "status_changed")}


def test_missing_and_added():
    assert kinds({"a": 1, "currency": "ZAR"}, {"a": 1, "b": 2}) == {("$.currency", "missing_in_new"),
                                                                    ("$.b", "added_in_new")}


def test_keyed_list_membership_no_element_diffs():
    assert kinds({"items": [{"id": 4}, {"id": 5}]}, {"items": []}) == {("$.items", "items_removed")}


def test_unkeyed_list_length():
    assert kinds({"items": [{"q": 1}, {"q": 2}]}, {"items": []}) == {("$.items", "list_length_changed")}


def test_nested_elements():
    assert kinds({"items": [{"q": 1}]}, {"items": [{"q": 2}]}) == {("$.items[0].q", "changed")}


def test_type_changed_vs_int_float():
    assert kinds({"a": "1"}, {"a": 1}) == {("$.a", "type_changed")}
    assert kinds({"a": None}, {"a": "x"}) == {("$.a", "type_changed")}
    assert kinds({"a": 10}, {"a": 10.0}) == set()


def test_errors_produce_no_diffs():
    assert diff(HttpResult(status=None, error="boom"), HttpResult(status=200, body={})) == []
