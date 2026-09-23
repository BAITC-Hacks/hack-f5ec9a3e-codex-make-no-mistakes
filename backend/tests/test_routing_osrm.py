import json
from copy import deepcopy
from pathlib import Path

import pytest

from replenishment.cli.almaty_routes import example_inputs
from replenishment.routing import recommend_schedule
from replenishment.routing_osrm import road_matrix_from_osrm


def test_osrm_conversion_keeps_direction_nulls_and_conservative_rounding():
    payload = {"code": "Ok", "distances": [[0, 10.1, None], [20, 0, 5], [None, 8, 0]],
               "durations": [[0, 60.1, None], [20, 0, 120], [None, 61, 0]]}
    matrix = road_matrix_from_osrm(payload, 3)
    assert matrix.metres == ((0, 11, None), (20, 0, 5), (None, 8, 0))
    assert matrix.minutes == ((0, 2, None), (1, 0, 2), (None, 2, 0))
    for field, value in (("durations", [[0]]), ("distances", [[0, True, None], [20, 0, 5], [None, 8, 0]]),
                         ("fallback_speed_cells", [[0, 1]]), ("code", "NoTable")):
        with pytest.raises(ValueError):
            road_matrix_from_osrm({**payload, field: value}, 3)
    invalid = deepcopy(payload)
    invalid["durations"][0][2] = 0
    with pytest.raises(ValueError, match="reachability"):
        road_matrix_from_osrm(invalid, 3)


def test_saved_almaty_roads_support_a_complete_better_plan_without_network():
    source = Path(__file__).resolve().parents[2] / "docs/sources/almaty-routing"
    locations = json.loads((source / "locations.json").read_text(encoding="utf-8"))["locations"]
    capture = json.loads((source / "osrm-table.json").read_text(encoding="utf-8"))
    assert capture["location_order"] == [p["id"] for p in locations]
    assert capture["requested_coordinates_lon_lat"] == [[p["longitude"], p["latitude"]] for p in locations]
    assert max(p["distance"] for p in capture["response"]["sources"]) < 200
    matrix = road_matrix_from_osrm(capture["response"], len(locations))
    orders, shifts, costs = example_inputs(locations)
    result = recommend_schedule(orders, shifts, matrix, costs, time_limit_ms=300)
    assert result.savings > 0
    assert sum(len(r.visits) for r in result.proposed.routes) == 9
    assert [(c.delivery_id, c.from_day, c.to_day) for c in result.changes] == [("distel", 0, 3)]
    assert sum(r.distance_metres for r in result.proposed.routes) < sum(
        r.distance_metres for r in result.baseline.routes
    )
