import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import allocation


def s(i, urgency=0, bonus=0.0):
    return {"id": i, "full_name": f"Student {i}", "exam_urgency": urgency, "need_bonus": bonus}


def test_empty():
    assert allocation.compute_allocation([], 5000) == []


def test_floor_guaranteed():
    res = allocation.compute_allocation([s(1), s(2), s(3)], 6000)
    assert all(a["minutes"] >= allocation.FLOOR_MINUTES for a in res)
    assert sum(a["minutes"] for a in res) == 6000


def test_urgency_gets_more():
    res = allocation.compute_allocation([s(1, urgency=0), s(2, urgency=10)], 6000)
    by_id = {a["user_id"]: a["minutes"] for a in res}
    assert by_id[2] > by_id[1]
    assert "urgency" in next(a["rationale"] for a in res if a["user_id"] == 2)


def test_pool_below_floor_even_split():
    res = allocation.compute_allocation([s(1), s(2), s(3), s(4)], 200)
    assert all(a["minutes"] == 50 for a in res)
    assert "Emergency" in res[0]["rationale"]


def test_deterministic():
    students = [s(i, urgency=i % 11) for i in range(1, 30)]
    assert allocation.compute_allocation(students, 9000) == allocation.compute_allocation(students, 9000)
