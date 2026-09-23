"""Validate an OSRM Table response and convert its units for the routing solver."""

from math import ceil, isfinite

from replenishment.routing import RoadMatrix


def road_matrix_from_osrm(payload: dict, size: int) -> RoadMatrix:
    if payload.get("code") != "Ok" or payload.get("fallback_speed_cells"):
        raise ValueError("OSRM must return successful road routes without straight-line fallbacks")
    matrices = []
    for field, divisor in (("distances", 1), ("durations", 60)):
        matrix = payload.get(field)
        if not isinstance(matrix, list) or len(matrix) != size:
            raise ValueError(f"OSRM {field} dimensions do not match locations")
        rows = []
        for row in matrix:
            if not isinstance(row, list) or len(row) != size:
                raise ValueError(f"OSRM {field} must be square")
            converted = []
            for value in row:
                if value is not None and (type(value) not in (float, int)
                                          or not isfinite(value) or value < 0):
                    raise ValueError(f"OSRM {field} must contain finite nonnegative numbers or null")
                converted.append(None if value is None else ceil(value / divisor))
            rows.append(tuple(converted))
        matrices.append(tuple(rows))
    for i in range(size):
        for j in range(size):
            if (matrices[0][i][j] is None) != (matrices[1][i][j] is None):
                raise ValueError("OSRM distance/time reachability disagree")
        if matrices[0][i][i] != 0 or matrices[1][i][i] != 0:
            raise ValueError("OSRM matrix diagonal must be zero")
    return RoadMatrix(*matrices)
