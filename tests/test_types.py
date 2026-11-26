from nparity.models import FieldMap, HttpResult, Request, Sample
from nparity.types import declared_diffs, observed_types, value_type


def s(a, b):
    req = Request(method="GET", path="/x")
    return Sample(old_request=req, new_request=req, old=HttpResult(status=200, body=a),
                  new=HttpResult(status=200, body=b))


def test_value_type():
    assert value_type(10.01) == "decimal(2)"
    assert value_type(10.0) == "decimal(0)"
    assert value_type(3) == "integer"
    assert value_type(True) == "boolean"


def test_observed_across_samples():
    obs = observed_types([s({"total": 10.01, "items": [{"id": 1}]}, {"total": 10.0, "items": [{"id": 1}]}),
                          s({"total": None}, {"total": 3.5})])
    assert obs["$.total"] == ({"decimal(2)", "null"}, {"decimal(0)", "decimal(1)"})
    assert obs["$.items[*].id"] == ({"integer"}, {"integer"})


def test_declared_currency_change():
    old = {"properties": {"currency": {"type": "string"}, "id": {"type": "integer"}},
           "required": ["currency", "id"]}
    new = {"properties": {"currency": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "id": {"type": "integer"}},
           "required": ["id"]}
    fm = [FieldMap(endpoint="E", old="currency", new="currency", source="rule", status="accepted"),
          FieldMap(endpoint="E", old="id", new="id", source="rule", status="accepted")]
    (d,) = declared_diffs(old, new, fm)
    assert d.path == "$.currency" and d.kind == "declared_type_changed"
    assert d.old == "string, required" and d.new == "string | null, optional"
