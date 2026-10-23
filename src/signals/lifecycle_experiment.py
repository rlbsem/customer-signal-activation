"""Durable randomized assignment and conservative synthetic outcome measurement."""

import hashlib
import json
import math
from contextlib import nullcontext
from .contracts import canonical, digest
from .remote import connect
from .store import Refused

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiment(id TEXT PRIMARY KEY, body TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS experiment_assignment(id TEXT PRIMARY KEY, experiment TEXT NOT NULL,
 brand TEXT NOT NULL,person TEXT NOT NULL,enrollment TEXT NOT NULL,epoch INTEGER NOT NULL,
 assigned_at INTEGER NOT NULL,arm TEXT NOT NULL,eligibility TEXT NOT NULL,evidence TEXT NOT NULL,
 UNIQUE(brand,person),UNIQUE(experiment,brand,person));
CREATE TABLE IF NOT EXISTS experiment_observation(id TEXT,revision INTEGER,brand TEXT,person TEXT,
 after_time INTEGER,through_time INTEGER,observed INTEGER,hash TEXT,PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS experiment_value(id TEXT,revision INTEGER,brand TEXT,person TEXT,
 conversion_ref TEXT,cents INTEGER,currency TEXT,kind TEXT,observed INTEGER,hash TEXT,PRIMARY KEY(id,revision));
"""
TABLES = ["experiment", "experiment_assignment", "experiment_observation", "experiment_value"]


def initialize(c):
    c.executescript(SCHEMA)
    for table in TABLES:
        for op in ["UPDATE", "DELETE"]:
            c.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable experiment record'); END"
            )


def arm(seed, brand, person):
    # One exclusion unit across journeys and versions; version is deliberately not a rerandomization salt.
    number = int(hashlib.sha256(canonical([seed, brand, person]).encode()).hexdigest()[:16], 16)
    return "treatment" if number < 2**63 else "holdout"


def guard(c, e, now):
    a = c.execute(
        "SELECT * FROM experiment_assignment WHERE brand=? AND person=?", (e["brand"], e["person"])
    ).fetchone()
    if not a:
        return None
    if a["arm"] == "holdout":
        return "experiment_holdout"
    if a["enrollment"] != e["id"]:
        return "experiment_overlap"
    if a["epoch"] != e["epoch"]:
        return "experiment_epoch_changed"
    spec = json.loads(c.execute("SELECT body FROM experiment WHERE id=?", (a["experiment"],)).fetchone()[0])
    if now >= a["assigned_at"] + spec["window"]:
        return "experiment_window_closed"
    return None


class Experiments:
    def __init__(self, engine):
        self.engine = engine

    def register(self, key, *, version=1, seed="lifecycle-study/v1", journey="quiet", window=7 * 86400):
        if (
            not isinstance(key, str)
            or not key
            or type(version) is not int
            or version < 1
            or journey not in {"quiet", "onboarding", "expansion"}
            or type(window) is not int
            or window <= 0
            or not isinstance(seed, str)
            or not seed
        ):
            raise Refused("experiment_contract")
        body = canonical(
            {
                "version": version,
                "seed": seed,
                "journey": journey,
                "window": window,
                "allocation": "sha256-first64-half-v1",
                "exclusion_unit": "brand/person/all-marketing-journeys",
            }
        )
        with connect(self.engine.path) as c:
            old = c.execute("SELECT body FROM experiment WHERE id=?", (key,)).fetchone()
            if old and old[0] != body:
                raise Refused("experiment_version_collision")
            c.execute("INSERT OR IGNORE INTO experiment VALUES(?,?,?)", (key, body, digest(json.loads(body))))

    def assign(self, key, enrollment, now, *, _connection=None):
        if _connection is None:
            self.engine.tick(now)
        with connect(self.engine.path) if _connection is None else nullcontext(_connection) as c:
            config = c.execute("SELECT body FROM experiment WHERE id=?", (key,)).fetchone()
            e = c.execute("SELECT * FROM enrollment WHERE id=?", (enrollment,)).fetchone()
            if not config or not e:
                raise Refused("unknown_experiment_or_enrollment")
            config = json.loads(config[0])
            old = c.execute(
                "SELECT * FROM experiment_assignment WHERE brand=? AND person=?", (e["brand"], e["person"])
            ).fetchone()
            if old:
                if old["experiment"] != key or old["enrollment"] != enrollment or old["epoch"] != e["epoch"]:
                    raise Refused("overlapping_assignment")
                return dict(old)
            if e["journey"] != config["journey"]:
                raise Refused("wrong_experiment_journey")
            if c.execute(
                "SELECT 1 FROM actions a JOIN enrollment e ON e.id=a.enrollment WHERE e.brand=? AND e.person=? AND a.reserved IS NOT NULL",
                (e["brand"], e["person"]),
            ).fetchone():
                raise Refused("prior_contact_contamination")
            f = self.engine.facts(c, e["brand"], e["person"], now)
            if "identity" not in f:
                raise Refused("unverified_experiment_identity")
            reason = self.engine.eligibility(f, e["journey"], now)
            if e["state"] != "active":
                reason = "enrollment_exited"
            value = (
                digest([key, e["brand"], e["person"]]),
                key,
                e["brand"],
                e["person"],
                enrollment,
                e["epoch"],
                now,
                arm(config["seed"], e["brand"], e["person"]),
                reason,
                digest(f),
            )
            c.execute("INSERT INTO experiment_assignment VALUES(?,?,?,?,?,?,?,?,?,?)", value)
            return dict(c.execute("SELECT * FROM experiment_assignment WHERE id=?", (value[0],)).fetchone())

    def assign_all(self, key, now):
        self.engine.tick(now)
        with connect(self.engine.path) as c:
            record = c.execute("SELECT body FROM experiment WHERE id=?", (key,)).fetchone()
            if not record:
                raise Refused("unknown_experiment")
            config = json.loads(record[0])
            enrollments = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM enrollment WHERE journey=? ORDER BY id", (config["journey"],)
                )
            ]
            return [self.assign(key, e, now, _connection=c) for e in enrollments]

    def coverage(self, key, revision, brand, person, after, through, observed):
        if (
            not all(type(t) is int for t in [revision, after, through, observed])
            or revision < 1
            or after > through
            or through > observed
        ):
            raise Refused("outcome_coverage_contract")
        value = (key, revision, brand, person, after, through, observed)
        with connect(self.engine.path) as c:
            old = c.execute(
                "SELECT * FROM experiment_observation WHERE id=? AND revision=?", (key, revision)
            ).fetchone()
            previous = c.execute(
                "SELECT brand,person FROM experiment_observation WHERE id=? LIMIT 1", (key,)
            ).fetchone()
            if previous and tuple(previous) != (brand, person):
                raise Refused("coverage_identity_collision")
            h = digest(value)
            if old and old["hash"] != h:
                raise Refused("coverage_collision")
            c.execute("INSERT OR IGNORE INTO experiment_observation VALUES(?,?,?,?,?,?,?,?)", (*value, h))

    def value(self, key, revision, brand, person, conversion_ref, cents, observed):
        # Explicit synthetic CRM opportunity value. This API never treats it as invoice, cash or revenue.
        if (
            type(cents) is not int
            or cents < 0
            or type(revision) is not int
            or revision < 1
            or type(observed) is not int
        ):
            raise Refused("value_contract")
        row = (key, revision, brand, person, conversion_ref, cents, "USD", "pipeline", observed)
        with connect(self.engine.path) as c:
            old = c.execute(
                "SELECT * FROM experiment_value WHERE id=? AND revision=?", (key, revision)
            ).fetchone()
            prior = c.execute(
                "SELECT brand,person FROM experiment_value WHERE id=? LIMIT 1", (key,)
            ).fetchone()
            if prior and tuple(prior) != (brand, person):
                raise Refused("value_identity_collision")
            if old and old["hash"] != digest(row):
                raise Refused("value_collision")
            c.execute(
                "INSERT OR IGNORE INTO experiment_value VALUES(?,?,?,?,?,?,?,?,?,?)", (*row, digest(row))
            )

    def measure(self, key, now):
        with connect(self.engine.path) as c:
            record = c.execute("SELECT body FROM experiment WHERE id=?", (key,)).fetchone()
            if not record:
                raise Refused("unknown_experiment")
            config = json.loads(record[0])
            assignments = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM experiment_assignment WHERE experiment=? AND assigned_at<=? ORDER BY id",
                    (key, now),
                )
            ]
            events = [dict(r) for r in c.execute("SELECT * FROM events WHERE observed<=?", (now,))]
            observations = [
                dict(r) for r in c.execute("SELECT * FROM experiment_observation WHERE observed<=?", (now,))
            ]
            values = [dict(r) for r in c.execute("SELECT * FROM experiment_value WHERE observed<=?", (now,))]
            actions = [
                dict(r)
                for r in c.execute(
                    "SELECT a.*,e.brand,e.person FROM actions a JOIN enrollment e ON e.id=a.enrollment"
                )
            ]
            histories = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM history WHERE event IN ('accepted','approved','attempt') AND at<=?", (now,)
                )
            ]

        def latest(rows, keys):
            result = {}
            for row in rows:
                k = tuple(row[f] for f in keys)
                if k not in result or row["revision"] > result[k]["revision"]:
                    result[k] = row
            return list(result.values())

        events = latest(events, ["brand", "source", "event_id"])
        observations = latest(observations, ["id"])
        values = latest(values, ["id"])
        rows = []
        exceptions = []
        for a in assignments:
            end = a["assigned_at"] + config["window"]
            coverage = any(
                o["brand"] == a["brand"]
                and o["person"] == a["person"]
                and o["after_time"] <= a["assigned_at"]
                and o["through_time"] >= end
                for o in observations
            )
            mature = now >= end
            conversions = [
                e
                for e in events
                if e["brand"] == a["brand"]
                and e["person"] == a["person"]
                and e["kind"] == "conversion"
                and json.loads(e["body"])["converted"]
                and a["assigned_at"] <= e["effective"] < end
            ]
            target = [v for v in actions if v["enrollment"] == a["enrollment"] and v["epoch"] == a["epoch"]]
            exposed = []
            for action in target:
                receipts = [json.loads(h["body"]) for h in histories if h["action"] == action["id"]]
                valid = any(
                    r.get("id") == action["id"]
                    and r.get("accepted") is True
                    and r.get("payload_hash") == digest(json.loads(action["payload"]))
                    for r in receipts
                )
                if valid:
                    exposed.append(action["id"])
                if action["state"] == "accepted" and not valid:
                    exceptions.append({"assignment": a["id"], "reason": "accepted_without_verified_receipt"})
            other_exposure = any(
                v["id"] not in {r["id"] for r in target}
                and v["brand"] == a["brand"]
                and v["person"] == a["person"]
                and any(
                    h["action"] == v["id"]
                    and h["at"] >= a["assigned_at"]
                    and h["event"] == "accepted"
                    and json.loads(h["body"]).get("accepted") is True
                    and json.loads(h["body"]).get("id") == v["id"]
                    and json.loads(h["body"]).get("payload_hash") == digest(json.loads(v["payload"]))
                    for h in histories
                )
                for v in actions
            )
            if other_exposure:
                exceptions.append({"assignment": a["id"], "reason": "cross_journey_contamination"})
            if a["arm"] == "holdout" and exposed:
                exceptions.append({"assignment": a["id"], "reason": "holdout_contamination"})
            linked = []
            for v in values:
                if v["brand"] == a["brand"] and v["person"] == a["person"]:
                    if any(e["event_id"] == v["conversion_ref"] for e in conversions):
                        linked.append(v)
                    else:
                        exceptions.append(
                            {
                                "assignment": a["id"],
                                "source": v["id"],
                                "reason": "unreconciled_commercial_relationship",
                            }
                        )
            # Multiple values may be legitimate, each source identity contributes once after revision selection.
            rows.append(
                a
                | {
                    "mature": mature,
                    "coverage": coverage,
                    "converted": bool(conversions),
                    "conversion_refs": [e["event_id"] for e in conversions],
                    "approved": any(
                        h["event"] == "approved" and h["action"] in {v["id"] for v in target}
                        for h in histories
                    ),
                    "accepted": bool(exposed),
                    "receipt_actions": exposed,
                    "unresolved": bool(
                        any(
                            h["event"] == "attempt" and h["action"] in {v["id"] for v in target}
                            for h in histories
                        )
                        and not exposed
                    ),
                    "pipeline_cents": sum(v["cents"] for v in linked),
                }
            )
        populations = {}
        for group in ["treatment", "holdout"]:
            chosen = [r for r in rows if r["arm"] == group]
            populations[group] = {
                "assigned": len(chosen),
                "eligible_at_assignment": sum(r["eligibility"] == "eligible" for r in chosen),
                "approved": sum(r["approved"] for r in chosen),
                "accepted": sum(r["accepted"] for r in chosen),
                "conversions": sum(r["converted"] for r in chosen),
                "mature_covered": sum(r["mature"] and r["coverage"] for r in chosen),
                "pipeline_cents": sum(r["pipeline_cents"] for r in chosen),
            }
        complete = bool(rows) and all(r["mature"] and r["coverage"] for r in rows)
        estimate = None
        interval = None
        t, h = populations["treatment"], populations["holdout"]
        if (
            complete
            and t["assigned"]
            and h["assigned"]
            and not any(
                e["reason"]
                in {
                    "holdout_contamination",
                    "cross_journey_contamination",
                    "accepted_without_verified_receipt",
                }
                for e in exceptions
            )
        ):
            pt, ph = t["conversions"] / t["assigned"], h["conversions"] / h["assigned"]
            estimate = pt - ph

            # Conservative Wilson interval subtraction; descriptive synthetic uncertainty, not a commercial claim.
            def wilson(k, n):
                z = 2.241403  # Bonferroni-adjusted 97.5% Wilson intervals; approximate joint 95%.
                p = k / n
                d = 1 + z * z / n
                center = (p + z * z / (2 * n)) / d
                radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
                return center - radius, center + radius

            tl, tu = wilson(t["conversions"], t["assigned"])
            hl, hu = wilson(h["conversions"], h["assigned"])
            interval = [tl - hu, tu - hl]
        return {
            "experiment": key,
            "configuration": config,
            "as_of": now,
            "population": populations,
            "assignments": rows,
            "exceptions": exceptions,
            "source_records": {
                "conversions": [e for e in events if e["kind"] == "conversion"],
                "coverage": observations,
                "commercial": values,
                "receipts": [h for h in histories if h["event"] == "accepted"],
            },
            "measurement_complete": complete,
            "itt_rate_difference": estimate,
            "conservative_95_interval": interval,
            "commercial_incremental_revenue": None,
            "scope": "Synthetic randomized fixture; acceptance is not contact, pipeline is not revenue; no observed commercial uplift",
        }
