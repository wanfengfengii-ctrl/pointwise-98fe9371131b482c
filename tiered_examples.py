"""Run the V1 comparison for the measurements used in TIERED.md."""
import json
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from assembly.requests import prepare_comparison
from assembly.store import open_review_store
from ledger.revisions import record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from review.reconcile import sign_comparison
from station.publish import encode_station_artifact, freeze_station

TICKET = "fixture-tier-check"
UNIT = "mm"
STATIONS = ("north", "south")
TERMINALS = ("B",)
BINDINGS = (("B", "B"),)
CONTRASTS = ((("north", "B"), None),)
NORTH_ROWS = (
    {"id": "fixture_zero", "terms": {"north_private": 1}, "target": 0, "weight": 1},
    {"id": "seam_read", "terms": {"B": 1, "north_private": -1}, "target": 0, "weight": 2},
)
SOUTH_EXACT = ({"id": "seam_pin", "terms": {"B": 1}, "target": 1},)
CONTROL_GROUPS = (("fixture_zero",), ("seam_read",))


def freeze_v1_sources(open_source):
    north_payloads = []
    with closing(open_source("north")) as source:
        trial = initialize_trial(source, TICKET, UNIT, STATIONS)
        parent = None
        for ordinal, _ in enumerate(CONTROL_GROUPS, 1):
            revision = record_revision(source, trial.trial_id, "north", UNIT, f"group-{ordinal}",
                                       observations=NORTH_ROWS, parent_id=parent)
            north_payloads.append(encode_station_artifact(freeze_station(source, revision, TERMINALS)))
            parent = revision
    with closing(open_source("south")) as source:
        trial = initialize_trial(source, TICKET, UNIT, STATIONS)
        revision = record_revision(source, trial.trial_id, "south", UNIT, "seam-reference", SOUTH_EXACT)
        south = encode_station_artifact(freeze_station(source, revision, TERMINALS))
    return north_payloads, south


def verify_v1(open_source, review):
    north_payloads, south = freeze_v1_sources(open_source)
    reports = []
    for north, future_group in zip(north_payloads, CONTROL_GROUPS, strict=True):
        task = prepare_comparison(review, north, south, BINDINGS, contrasts=CONTRASTS)
        result = sign_comparison(review, task)
        actual = (result.residuals.stations, result.residuals.total, result.contrasts[0].value)
        expected = ((("north", Fraction(2, 3)), ("south", Fraction(0))), Fraction(2, 3), Fraction(1))
        if actual != expected:
            raise AssertionError((future_group, actual, expected))
        reports.append({"proposed_control_ids": future_group, "v1_report": json.loads(result.issued.payload)})
    return reports


def main():
    with TemporaryDirectory() as folder:
        directory = Path(folder)
        with closing(open_review_store(directory / "review.sqlite3")) as review:
            reports = verify_v1(lambda station: open_ledger(directory / f"{station}.sqlite3"), review)
    print(json.dumps(reports, ensure_ascii=False))


if __name__ == "__main__":
    main()
