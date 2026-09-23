"""Runnable guard checks: python scripts/check_experiment_registry.py."""
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from register_experiment import inspect_predictions


def main():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        row = dict(model_id="test", supplier="IEK", sku="001_", unit="шт",
                   origin="2026-01-01", horizon_days=28, forecast=8., actual=10.)
        metrics = [dict(model="test", phase="retrospective_2026", supplier="IEK", unit="шт",
                        horizon=28, segment="all", n=1, wape_pct=20., bias_pct=-20., underforecast_pct=20.)]

        def write(rows):
            with (root / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(rows)

        def rejects(rows, models):
            write(rows)
            try:
                inspect_predictions(root, models, metrics)
            except ValueError:
                return
            raise AssertionError("Invalid run was accepted")

        write([row])
        signature, count, checked = inspect_predictions(root, ["test"], metrics)
        assert count == checked == 1 and metrics[0]["mae"] == 2
        assert len(signature) == 64
        rejects([row, row], ["test"])
        rejects([{**row, "forecast": float("nan")}], ["test"])
        rejects([{**row, "forecast": 7}], ["test"])
        rejects([row], ["test", "missing"])
        rejects([row, {**row, "model_id": "other", "actual": 11}], ["test", "other"])
    print("Registry guards passed: duplicate, nonfinite, metric mismatch, missing cohort, inconsistent actuals")


if __name__ == "__main__":
    main()
