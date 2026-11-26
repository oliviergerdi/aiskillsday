from nparity.config import load_noise
from nparity.models import HttpResult
from nparity.normalise import MASK, normalise

RULES = load_noise("config/noise.yaml")


def res(body, status=200):
    return HttpResult(status=status, body=body)


def test_mask_records_noise_and_equalises():
    o, n, noise = normalise("POST /orders", res({"id": "ord_a", "createdAt": "t1", "total": 10.0}),
                            res({"id": "ord_b", "createdAt": "t2", "total": 10.0}, 201), RULES)
    assert o.body == n.body == {"id": MASK, "createdAt": MASK, "total": 10.0}
    assert {x.path for x in noise} == {"$.id", "$.createdAt"}


def test_mask_scoped_to_endpoint():
    o, n, noise = normalise("GET /orders/{id}", res({"id": 1}), res({"id": 2}), RULES)
    assert (o.body, n.body, noise) == ({"id": 1}, {"id": 2}, [])


def test_order_only_is_noise_and_diff_matches_by_key():
    from nparity.diff import diff
    page = lambda ids: {"page": 1, "items": [{"id": i} for i in ids]}
    o, n, noise = normalise("GET /orders", res(page([1, 2, 3])), res(page([3, 2, 1])), RULES)
    assert [(x.path, x.rule) for x in noise] == [("$.items", "order (matched by id)")]
    assert diff(o, n) == []
    _, _, noise2 = normalise("GET /orders", res(page([4, 5])), res(page([])), RULES)
    assert noise2 == []


def test_rename_and_drop_applied_to_old():
    o, n, _ = normalise("GET /customers/{id}",
                        res({"id": 1, "fullName": "Ada", "legacyCode": "L"}), res({"id": 1, "name": "Ada"}),
                        RULES, {"fullName": "name", "legacyCode": None})
    assert o.body == n.body == {"id": 1, "name": "Ada"}


def test_inputs_not_mutated():
    old = res({"id": "a", "createdAt": "t"})
    normalise("POST /orders", old, res({"id": "b", "createdAt": "u"}), RULES)
    assert old.body == {"id": "a", "createdAt": "t"}
