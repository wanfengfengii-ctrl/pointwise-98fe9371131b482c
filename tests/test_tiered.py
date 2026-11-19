import json
import sqlite3
import unittest
from contextlib import closing
from fractions import Fraction

from assembly.requests import prepare_comparison
from assembly.store import open_review_store
from ledger.revisions import load_revision, record_revision
from ledger.store import open_ledger
from ledger.trials import initialize_trial
from records.retrieve import get_comparison
from review.reconcile import JointInfeasibleError, sign_comparison
from station.publish import (
    decode_station_artifact,
    encode_station_artifact,
    freeze_station,
    freeze_tiered_station,
    load_station_artifact,
)
from tests import counts, exact, ordinary, review_store, workdir

STATIONS = ("north", "south")
TICKET = "fixture-tier-check"
UNIT = "mm"
TERMINALS = ("B",)
BINDINGS = (("B", "B"),)
B_CONTRAST = ((( "north", "B"), None),)
NORTH_ROWS = (
    ordinary("fixture_zero", {"north_private": 1}, 0),
    ordinary("seam_read", {"B": 1, "north_private": -1}, 0, 2),
)
SOUTH_EXACT = (exact("seam_pin", {"B": 1}, 1),)
CONTROL_GROUPS = (("fixture_zero",), ("seam_read",))


def tiered_freeze(directory, station, exact_rows, observations, control_ids, terminals=TERMINALS,
                  ticket=TICKET, name=None):
    with closing(open_ledger(directory / f"{station}.sqlite3")) as source:
        trial = initialize_trial(source, ticket, UNIT, STATIONS)
        revision = record_revision(source, trial.trial_id, station, UNIT,
                                   name if name is not None else f"tiered-{station}",
                                   exact_rows, observations, control_ids=control_ids)
        artifact = freeze_tiered_station(source, revision, terminals)
        return encode_station_artifact(artifact)


class TieredRevisionTests(unittest.TestCase):
    def setUp(self):
        self.db = open_ledger(workdir(self) / "source.sqlite3")
        self.addCleanup(self.db.close)
        self.trial = initialize_trial(self.db, "ticket-tier", UNIT, STATIONS)

    def test_control_ids_persistence_and_ordering(self):
        revision = record_revision(self.db, self.trial.trial_id, "north", UNIT, "t1",
                                   (), NORTH_ROWS, control_ids=["seam_read", "fixture_zero"])
        loaded = load_revision(self.db, revision)
        self.assertEqual(loaded.control_ids, ("fixture_zero", "seam_read"))
        empty = record_revision(self.db, self.trial.trial_id, "north", UNIT, "t2",
                                (), NORTH_ROWS, control_ids=[])
        self.assertEqual(load_revision(self.db, empty).control_ids, ())
        all_rows = record_revision(self.db, self.trial.trial_id, "north", UNIT, "t3",
                                   (), NORTH_ROWS, control_ids=["fixture_zero", "seam_read"])
        self.assertEqual(load_revision(self.db, all_rows).control_ids,
                         ("fixture_zero", "seam_read"))

    def test_v1_revision_has_none_control_ids(self):
        revision = record_revision(self.db, self.trial.trial_id, "north", UNIT, "v1",
                                   (), NORTH_ROWS)
        self.assertIsNone(load_revision(self.db, revision).control_ids)

    def test_invalid_control_ids_rejected_without_insert(self):
        bad_cases = (
            "fixture_zero",
            ["fixture_zero", "fixture_zero"],
            ("missing",),
            {"fixture_zero"},
        )
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                record_revision(self.db, self.trial.trial_id, "north", UNIT, f"bad-{bad!r}",
                                (), NORTH_ROWS, control_ids=bad)
        self.assertEqual(counts(self.db, "revisions"), (0,))

    def test_control_group_changes_identity_and_correction_keeps_group(self):
        first = record_revision(self.db, self.trial.trial_id, "north", UNIT, "g1",
                                (), NORTH_ROWS, control_ids=["fixture_zero"])
        second = record_revision(self.db, self.trial.trial_id, "north", UNIT, "g2",
                                 (), NORTH_ROWS, control_ids=["seam_read"])
        self.assertNotEqual(first, second)
        correction = record_revision(self.db, self.trial.trial_id, "north", UNIT, "fix",
                                     (), NORTH_ROWS, control_ids=["seam_read"], parent_id=second)
        corrected = load_revision(self.db, correction)
        self.assertEqual(corrected.parent_id, second)
        self.assertEqual(corrected.control_ids, ("seam_read",))


class TieredFreezeTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)

    def test_freeze_routing_and_idempotent_bytes(self):
        with closing(open_ledger(self.directory / "source.sqlite3")) as db:
            trial = initialize_trial(db, TICKET, UNIT, STATIONS)
            v1 = record_revision(db, trial.trial_id, "north", UNIT, "v1", (), NORTH_ROWS)
            tiered = record_revision(db, trial.trial_id, "north", UNIT, "tiered",
                                     (), NORTH_ROWS, control_ids=["fixture_zero"])
            with self.assertRaisesRegex(ValueError, "freeze_tiered_station"):
                freeze_tiered_station(db, v1, TERMINALS)
            with self.assertRaisesRegex(ValueError, "freeze_tiered_station"):
                freeze_station(db, tiered, TERMINALS)
            self.assertEqual(counts(db, "station_artifacts"), (0,))
            artifact = freeze_tiered_station(db, tiered, TERMINALS)
            again = freeze_tiered_station(db, tiered, TERMINALS)
            self.assertEqual(again, artifact)
            self.assertEqual(counts(db, "station_artifacts"), (1,))
            stored = load_station_artifact(db, artifact.artifact_id)
            self.assertEqual(stored, artifact)
        payload = encode_station_artifact(artifact)
        self.assertEqual(json.loads(payload)["body"]["version"], 2)
        self.assertNotIn(b"north_private", payload)
        self.assertNotIn(b"fixture_zero", payload)
        self.assertEqual(decode_station_artifact(payload), artifact)

    def test_inconsistent_exact_rows_rejected(self):
        with closing(open_ledger(self.directory / "source.sqlite3")) as db:
            trial = initialize_trial(db, TICKET, UNIT, STATIONS)
            revision = record_revision(
                db, trial.trial_id, "north", UNIT, "bad",
                [exact("d1", {"B": 1}, 1), exact("d2", {"B": 1}, 2)],
                NORTH_ROWS, control_ids=["fixture_zero"])
            with self.assertRaisesRegex(ValueError, "inconsistent"):
                freeze_tiered_station(db, revision, TERMINALS)
            self.assertEqual(counts(db, "station_artifacts"), (0,))

    def test_decode_rejects_tampered_v2_payloads(self):
        payload = tiered_freeze(self.directory, "north", (), NORTH_ROWS, ["fixture_zero"])
        envelope = json.loads(payload)
        envelope["body"]["control_gram"][0][0] = "-1"
        tampered = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(ValueError):
            decode_station_artifact(tampered)
        envelope = json.loads(payload)
        envelope["body"]["version"] = 3
        unknown = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaisesRegex(ValueError, "invalid station artifact"):
            decode_station_artifact(unknown)
        envelope = json.loads(payload)
        envelope["body"]["free_private"] = -1
        bad_count = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(ValueError):
            decode_station_artifact(bad_count)
        envelope = json.loads(payload)
        envelope["body"]["exact"] = [[["1"], "0"], [["1"], "1"]]
        infeasible = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(ValueError):
            decode_station_artifact(infeasible)

    def test_decode_rejects_bad_rationals_and_identity_mismatch(self):
        payload = tiered_freeze(self.directory, "north", (), NORTH_ROWS, ["fixture_zero"])
        envelope = json.loads(payload)
        envelope["body"]["control_gram"][0][0] = "1/0"
        bad_rational = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(ValueError):
            decode_station_artifact(bad_rational)
        envelope = json.loads(payload)
        envelope["body"]["free_private"] = 9
        bad_dimension = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaises(ValueError):
            decode_station_artifact(bad_dimension)
        envelope = json.loads(payload)
        envelope["id"] = "0" * 64
        bad_identity = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")
        with self.assertRaisesRegex(ValueError, "identity"):
            decode_station_artifact(bad_identity)
        with self.assertRaisesRegex(ValueError, "bytes"):
            decode_station_artifact("not-bytes")


class TieredReconcileTests(unittest.TestCase):
    def setUp(self):
        self.directory = workdir(self)

    def _pair(self, north_control, south_control=()):
        label = "-".join(north_control) if north_control else "empty"
        north = tiered_freeze(self.directory, "north", (), NORTH_ROWS, list(north_control),
                              name=f"tiered-north-{label}")
        south = tiered_freeze(self.directory, "south", SOUTH_EXACT, (), south_control,
                              name=f"tiered-south-{label}")
        return north, south

    def test_two_control_groups_match_tiered_table(self):
        db = review_store(self, self.directory)
        expected = {
            "fixture_zero": ((("north", Fraction(0), Fraction(2)),
                              ("south", Fraction(0), Fraction(0))), Fraction(0), Fraction(2)),
            "seam_read": ((("north", Fraction(0), Fraction(1)),
                           ("south", Fraction(0), Fraction(0))), Fraction(0), Fraction(1)),
        }
        for group in CONTROL_GROUPS:
            north, south = self._pair(group)
            task = prepare_comparison(db, north, south, BINDINGS, contrasts=B_CONTRAST)
            result = sign_comparison(db, task)
            self.assertEqual(result.residuals.stations, expected[group[0]][0])
            self.assertEqual(result.residuals.control_total, expected[group[0]][1])
            self.assertEqual(result.residuals.production_total, expected[group[0]][2])
            self.assertEqual(result.contrasts[0].status, "confirmed")
            self.assertEqual(result.contrasts[0].value, 1)
            body = json.loads(result.issued.payload)
            self.assertEqual(body["version"], 2)
            self.assertEqual(body["total_residuals"],
                             {"control": "0", "production": str(expected[group[0]][2])})
            self.assertEqual([item["value"] for item in body["contrasts"]], ["1"])

    def test_lexicographic_control_before_production(self):
        # Equal-weight control reads B=0 (north) and B=2 (south); north production reads B=5.
        north_rows = (ordinary("c", {"B": 1}, 0), ordinary("p", {"B": 1}, 5))
        south_rows = (ordinary("c", {"B": 1}, 2),)
        north = tiered_freeze(self.directory, "north", (), north_rows, ["c"],
                              ticket="lex-case")
        south = tiered_freeze(self.directory, "south", (), south_rows, ["c"],
                              ticket="lex-case")
        db = review_store(self, self.directory)
        task = prepare_comparison(db, north, south, BINDINGS, contrasts=B_CONTRAST)
        result = sign_comparison(db, task)
        self.assertEqual(result.residuals.stations,
                         (("north", Fraction(1), Fraction(16)),
                          ("south", Fraction(1), Fraction(0))))
        self.assertEqual(result.contrasts[0].value, 1)

    def test_private_state_and_unknown_terminal_contrast(self):
        north_rows = (
            ordinary("c", {"Z": 1}, 0),
            ordinary("p", {"B": 1, "Z": -1, "D": 0}, 2),
        )
        south_rows = (ordinary("free", {"B": 0}, 0),)
        north = tiered_freeze(self.directory, "north", (), north_rows, ["c"],
                              terminals=("B", "D"))
        south = tiered_freeze(self.directory, "south", (), south_rows, [],
                              terminals=TERMINALS)
        self.assertNotIn(b'"Z"', north)
        db = review_store(self, self.directory)
        task = prepare_comparison(
            db, north, south, BINDINGS,
            contrasts=((("north", "B"), None), (("north", "D"), None)))
        result = sign_comparison(db, task)
        self.assertEqual([item.value for item in result.contrasts], [2, None])
        self.assertEqual([item.status for item in result.contrasts],
                         ["confirmed", "unknown"])
        self.assertEqual(result.residuals.stations,
                         (("north", Fraction(0), Fraction(0)),
                          ("south", Fraction(0), Fraction(0))))

    def test_mixed_versions_rejected_at_intake(self):
        north = tiered_freeze(self.directory, "north", (), NORTH_ROWS, ["fixture_zero"])
        with closing(open_ledger(self.directory / "south.sqlite3")) as source:
            trial = initialize_trial(source, TICKET, UNIT, STATIONS)
            revision = record_revision(source, trial.trial_id, "south", UNIT, "v1",
                                       SOUTH_EXACT, ())
            south = encode_station_artifact(freeze_station(source, revision, TERMINALS))
        db = review_store(self, self.directory)
        with self.assertRaisesRegex(ValueError, "same evidence version"):
            prepare_comparison(db, north, south, BINDINGS)
        self.assertEqual(counts(db, "comparison_requests", "accepted_artifacts"), (0, 0))

    def test_joint_infeasible_blocks_issue_and_request_can_retry(self):
        north, south = self._pair(CONTROL_GROUPS[0])
        db = review_store(self, self.directory)
        blocked = prepare_comparison(
            db, north, south, BINDINGS,
            references=((( "south", "B"), 2),), contrasts=B_CONTRAST)
        with self.assertRaises(JointInfeasibleError):
            sign_comparison(db, blocked)
        self.assertEqual(counts(db, "reports", "report_provenance", "receipts"), (0, 0, 0))
        retry = prepare_comparison(db, north, south, BINDINGS, contrasts=B_CONTRAST)
        result = sign_comparison(db, retry)
        self.assertEqual(result.contrasts[0].value, 1)
        self.assertEqual(counts(db, "reports", "receipts"), (1, 1))

    def test_commit_failure_rollback_then_retry(self):
        north, south = self._pair(CONTROL_GROUPS[1])
        db = review_store(self, self.directory)
        task = prepare_comparison(db, north, south, BINDINGS, contrasts=B_CONTRAST)
        db.executescript('''
            CREATE TABLE permitted_issues (report_id INTEGER PRIMARY KEY);
            CREATE TABLE release_checks (
                report_id INTEGER REFERENCES permitted_issues(report_id) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER check_release AFTER INSERT ON receipts
            BEGIN
                INSERT INTO release_checks (report_id) VALUES (NEW.report_id);
            END;
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            sign_comparison(db, task)
        self.assertFalse(db.in_transaction)
        self.assertEqual(counts(db, "reports", "report_provenance", "receipts", "release_checks"),
                         (0, 0, 0, 0))
        db.close()
        with closing(open_review_store(self.directory / "review.sqlite3")) as reopened:
            self.assertEqual(counts(reopened, "reports", "report_provenance", "receipts"),
                             (0, 0, 0))
            reopened.execute("DROP TRIGGER check_release")
            result = sign_comparison(reopened, task)
            self.assertEqual(counts(reopened, "reports", "report_provenance", "receipts"),
                             (1, 1, 1))
            self.assertEqual(get_comparison(reopened, result.issued.report_id), result.issued)

    def test_retrieve_by_original_id_after_correction_and_reopen(self):
        north, south = self._pair(CONTROL_GROUPS[0])
        archive = self.directory / "review.sqlite3"
        with closing(open_review_store(archive)) as db:
            task = prepare_comparison(db, north, south, BINDINGS, contrasts=B_CONTRAST)
            issued = sign_comparison(db, task).issued
            parent_ids = tuple(json.loads(payload)["id"] for payload in (north, south))
        with closing(open_ledger(self.directory / "north.sqlite3")) as source:
            trial = initialize_trial(source, TICKET, UNIT, STATIONS)
            first_revision = decode_station_artifact(north).revision_id
            correction = record_revision(
                source, trial.trial_id, "north", UNIT, "late correction",
                (), NORTH_ROWS, control_ids=["seam_read"], parent_id=first_revision)
            replacement = freeze_tiered_station(source, correction, TERMINALS)
            self.assertNotEqual(replacement.artifact_id, parent_ids[0])
        (self.directory / "north.sqlite3").unlink()
        (self.directory / "south.sqlite3").unlink()
        with closing(open_review_store(archive)) as reopened:
            retrieved = get_comparison(reopened, issued.report_id)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.payload, issued.payload)
            self.assertEqual(retrieved.provenance.artifact_ids, parent_ids)
            self.assertEqual(retrieved.receipt, issued.receipt)
            self.assertIsNone(get_comparison(reopened, issued.report_id + 999))

    def test_empty_terminals_and_empty_groups(self):
        north_rows = (ordinary("loose", {"B": 1}, 4),)
        north = tiered_freeze(self.directory, "north", (), north_rows, [], terminals=())
        south = tiered_freeze(self.directory, "south", (), (), [], terminals=())
        db = review_store(self, self.directory)
        task = prepare_comparison(db, north, south, (), references=(), contrasts=())
        result = sign_comparison(db, task)
        self.assertEqual(result.residuals.stations,
                         (("north", Fraction(0), Fraction(0)),
                          ("south", Fraction(0), Fraction(0))))
        self.assertEqual(json.loads(result.issued.payload)["total_residuals"],
                         {"control": "0", "production": "0"})

    def test_legacy_v1_database_opens_with_control_migration(self):
        import sqlite3

        legacy = self.directory / "legacy.sqlite3"
        raw = sqlite3.connect(legacy)
        try:
            raw.executescript('''
                CREATE TABLE trials (id TEXT PRIMARY KEY, ticket TEXT NOT NULL UNIQUE,
                    unit TEXT NOT NULL);
                CREATE TABLE trial_stations (trial_id TEXT NOT NULL REFERENCES trials(id),
                    station TEXT NOT NULL, PRIMARY KEY (trial_id, station));
                CREATE TABLE revisions (id TEXT PRIMARY KEY, trial_id TEXT NOT NULL,
                    station TEXT NOT NULL, name TEXT NOT NULL, parent_id TEXT REFERENCES revisions(id),
                    evidence TEXT NOT NULL, UNIQUE (trial_id, station, name),
                    FOREIGN KEY (trial_id, station) REFERENCES trial_stations(trial_id, station));
                CREATE TABLE station_artifacts (id TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL REFERENCES revisions(id), payload BLOB NOT NULL);
            ''')
            raw.commit()
        finally:
            raw.close()
        with closing(open_ledger(legacy)) as db:
            trial = initialize_trial(db, "legacy-ticket", UNIT, STATIONS)
            revision = record_revision(db, trial.trial_id, "north", UNIT, "legacy",
                                       (), NORTH_ROWS)
            self.assertIsNone(load_revision(db, revision).control_ids)
            artifact = freeze_station(db, revision, TERMINALS)
            self.assertEqual(artifact.version, 1)
