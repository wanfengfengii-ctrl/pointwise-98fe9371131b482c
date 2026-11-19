"""Run the V1 comparison and the version 2 tiered reconciliation used in TIERED.md."""
import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from assembly.requests import prepare_comparison
from assembly.store import open_review_store
from ledger.revisions import record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from records.retrieve import get_comparison
from review.reconcile import sign_comparison
from station.publish import (
    encode_station_artifact,
    freeze_station,
    freeze_tiered_station,
)

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


def freeze_tiered_sources(open_source):
    north_payloads = []
    with closing(open_source("north")) as source:
        trial = initialize_trial(source, TICKET, UNIT, STATIONS)
        for ordinal, group in enumerate(CONTROL_GROUPS, 1):
            revision = record_revision(source, trial.trial_id, "north", UNIT, f"tiered-group-{ordinal}",
                                       observations=NORTH_ROWS, control_ids=list(group))
            north_payloads.append(
                encode_station_artifact(freeze_tiered_station(source, revision, TERMINALS)))
    with closing(open_source("south")) as source:
        trial = initialize_trial(source, TICKET, UNIT, STATIONS)
        revision = record_revision(source, trial.trial_id, "south", UNIT, "tiered-seam-reference",
                                   SOUTH_EXACT, control_ids=[])
        south = encode_station_artifact(freeze_tiered_station(source, revision, TERMINALS))
    return north_payloads, south


def verify_tiered(open_source, review):
    north_payloads, south = freeze_tiered_sources(open_source)
    expected = {
        "fixture_zero": {"north": ("0", "2"), "south": ("0", "0"),
                         "totals": ("0", "2"), "b": "confirmed 1"},
        "seam_read": {"north": ("0", "1"), "south": ("0", "0"),
                      "totals": ("0", "1"), "b": "confirmed 1"},
    }
    reports = []
    for north, group in zip(north_payloads, CONTROL_GROUPS, strict=True):
        task = prepare_comparison(review, north, south, BINDINGS, contrasts=CONTRASTS)
        result = sign_comparison(review, task)
        ledger = result.residuals
        body = json.loads(result.issued.payload)
        if body["version"] != 2:
            raise AssertionError("tiered report must use version 2")
        actual = {
            "north": (str(ledger.stations[0][1]), str(ledger.stations[0][2])),
            "south": (str(ledger.stations[1][1]), str(ledger.stations[1][2])),
            "totals": (str(ledger.control_total), str(ledger.production_total)),
            "b": f"{result.contrasts[0].status} {result.contrasts[0].value}",
        }
        if actual != expected[group[0]]:
            raise AssertionError((group, actual, expected[group[0]]))
        reports.append({"control_group": group, "tiered_report": body})
    return reports, north_payloads, south


def verify_tiered_retry_and_retrieval(directory, review, north, south):
    # A conflicting reference makes the joint problem infeasible; nothing is issued.
    blocked = prepare_comparison(
        review, north, south, BINDINGS,
        references=((("south", "B"), 2),), contrasts=CONTRASTS)
    try:
        sign_comparison(review, blocked)
    except Exception as error:  # JointInfeasibleError, asserted by the regression suite
        infeasible = type(error).__name__
    else:
        raise AssertionError("the conflicting reference must block issuance")

    # A feasible task whose finalization fails after the receipt write: the whole
    # finalization rolls back, then the trigger is removed and the same task retries.
    task_id = prepare_comparison(review, north, south, BINDINGS, contrasts=CONTRASTS)
    review.executescript('''
        CREATE TABLE permitted_issues (report_id INTEGER PRIMARY KEY);
        CREATE TABLE release_checks (
            report_id INTEGER REFERENCES permitted_issues(report_id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TRIGGER check_release AFTER INSERT ON receipts
        BEGIN
            INSERT INTO release_checks (report_id) VALUES (NEW.report_id);
        END;
    ''')
    try:
        sign_comparison(review, task_id)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("the deferred trigger must abort the finalization transaction")
    review.close()
    with closing(open_review_store(directory / "review.sqlite3")) as reopened:
        reopened.execute("DROP TRIGGER check_release")
        result = sign_comparison(reopened, task_id)
        report_id = result.issued.report_id
        parent_ids = result.issued.provenance.artifact_ids
        issued_bytes = result.issued.payload
        receipt = result.issued.receipt

    # The source ledger is corrected after the review store finalized its report.
    with closing(open_ledger(directory / "north.sqlite3")) as source:
        trial = initialize_trial(source, TICKET, UNIT, STATIONS)
        first = json.loads(north)["body"]["revision_id"]
        correction = record_revision(source, trial.trial_id, "north", UNIT, "late tiered correction",
                                     observations=NORTH_ROWS, control_ids=["seam_read"], parent_id=first)
        replacement = freeze_tiered_station(source, correction, TERMINALS)
    (directory / "north.sqlite3").unlink()
    (directory / "south.sqlite3").unlink()

    # Reopen the review store and claim the original report by its original number.
    with closing(open_review_store(directory / "review.sqlite3")) as reopened:
        claimed = get_comparison(reopened, report_id)
        if claimed is None or claimed.payload != issued_bytes:
            raise AssertionError("the original finalized bytes must be retrievable by report number")
        if claimed.provenance.artifact_ids != parent_ids or claimed.receipt != receipt:
            raise AssertionError("provenance and receipt must match the original issuance")
    return {
        "infeasible_reference": infeasible,
        "report_id": report_id,
        "parent_artifact_ids": parent_ids,
        "replacement_artifact_id": replacement.artifact_id,
        "reopened_claim_matches": True,
        "receipt_id": receipt.receipt_id,
    }


def main():
    with TemporaryDirectory() as folder:
        directory = Path(folder)
        with closing(open_review_store(directory / "review.sqlite3")) as review:
            v1_reports = verify_v1(
                lambda station: open_ledger(directory / f"v1-{station}.sqlite3"), review)
            tiered_reports, north_payloads, south = verify_tiered(
                lambda station: open_ledger(directory / f"{station}.sqlite3"), review)
            retry_report = verify_tiered_retry_and_retrieval(
                directory, review, north_payloads[0], south)
    print(json.dumps({"v1": v1_reports, "tiered": tiered_reports, "retry_and_retrieval": retry_report},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
