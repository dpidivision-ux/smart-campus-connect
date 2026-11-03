"""Internet-hours allocation engine.

The scarcity problem at UNN: the campus can offer only a fixed weekly
pool of online minutes, far less than students want. This engine splits
the pool fairly and transparently:

  weight = base + exam_urgency * EXAM_WEIGHT + need_bonus

Every student gets a guaranteed floor; the remainder is divided in
proportion to weights. Each allocation stores a human-readable
rationale so students can see *why* they got their hours - a lecturer
can defend the outcome, which matters on a real campus.
"""

BASE_WEIGHT = 1.0
EXAM_WEIGHT = 0.5          # each urgency point adds half a base share
FLOOR_MINUTES = 120        # guaranteed weekly minimum per student


def compute_allocation(students, total_minutes):
    """students: iterable of dicts with id, full_name, exam_urgency, need_bonus.

    Returns list of dicts {user_id, minutes, rationale}.
    Deterministic: same input -> same output.
    """
    students = list(students)
    if not students:
        return []
    n = len(students)
    floor_total = FLOOR_MINUTES * n
    if total_minutes < floor_total:
        # Pool too small for floors: split evenly, flag the shortfall.
        each = total_minutes // n
        return [{
            "user_id": s["id"],
            "minutes": each,
            "rationale": "Emergency even split - pool below guaranteed floor",
        } for s in students]

    distributable = total_minutes - floor_total
    weights = {s["id"]: BASE_WEIGHT + s.get("exam_urgency", 0) * EXAM_WEIGHT + s.get("need_bonus", 0.0)
               for s in students}
    weight_sum = sum(weights.values())

    out, assigned = [], 0
    for i, s in enumerate(students):
        if i < n - 1:
            share = round(distributable * weights[s["id"]] / weight_sum)
            assigned += share
        else:
            share = distributable - assigned  # remainder to last, keeps the sum exact
        minutes = FLOOR_MINUTES + share
        reasons = [f"guaranteed floor {FLOOR_MINUTES} min"]
        if s.get("exam_urgency", 0) >= 7:
            reasons.append("exam within days (high urgency)")
        elif s.get("exam_urgency", 0) >= 4:
            reasons.append("exam approaching")
        if s.get("need_bonus", 0.0) > 0:
            reasons.append("documented extra need")
        out.append({"user_id": s["id"], "minutes": minutes,
                    "rationale": "; ".join(reasons)})
    return out
