"""TraceCon's versioned executor and evidence-based credit ledger."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import Enum
import json
import math
import sqlite3


class Action(str, Enum):
    SKIP = "skip"
    WRITE = "write"
    MERGE = "merge"
    UPDATE = "update"
    RETAIN = "retain"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class Fact:
    target: str
    value: str
    source: str
    valid_from: int
    valid_until: int | None = None
    context: str = "personal"

    def __post_init__(self):
        if not all(part.strip() for part in (self.target, self.value, self.source, self.context)):
            raise ValueError("Facts require a target, value, source and context.")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Validity intervals are half-open and must be nonempty.")

    def covers(self, reference):
        return self.valid_from <= reference and (
            self.valid_until is None or reference < self.valid_until
        )


@dataclass(frozen=True)
class Support:
    """A span of an observed dialogue turn, using Python character offsets."""

    step: int
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class Feedback:
    event_id: str
    arrival: int
    answer_id: str
    channel: str
    intent: str
    expected: Fact
    scope: Support
    signal: float
    link: Support | None = None
    rationale: Support | None = None
    confirmation: Support | None = None

    def __post_init__(self):
        if not self.event_id or self.channel not in ("explicit", "implicit"):
            raise ValueError("Feedback requires an ID and a valid channel.")
        if self.intent not in ("retrospective", "prospective", "unresolved"):
            raise ValueError("Unknown feedback intent.")
        if not -1 <= self.signal <= 1:
            raise ValueError("Signal must be in [-1, 1].")


SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    episode TEXT, step INTEGER, text TEXT NOT NULL, PRIMARY KEY (episode, step)
);
CREATE TABLE IF NOT EXISTS operations (
    episode TEXT, step INTEGER, request TEXT NOT NULL, before_step INTEGER,
    after_step INTEGER, PRIMARY KEY (episode, step)
);
CREATE TABLE IF NOT EXISTS versions (
    episode TEXT, step INTEGER, target TEXT NOT NULL, context TEXT NOT NULL,
    valid_from INTEGER NOT NULL, valid_until INTEGER, value TEXT,
    sources TEXT NOT NULL, PRIMARY KEY (episode, step),
    FOREIGN KEY (episode, step) REFERENCES operations(episode, step)
);
CREATE INDEX IF NOT EXISTS version_scope ON versions(episode, target, context, step);
CREATE TABLE IF NOT EXISTS answers (
    episode TEXT, answer_id TEXT, step INTEGER NOT NULL, reference INTEGER NOT NULL,
    context TEXT NOT NULL, claims TEXT NOT NULL, presented TEXT NOT NULL,
    PRIMARY KEY (episode, answer_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    episode TEXT, event_id TEXT, core TEXT NOT NULL, evidence TEXT NOT NULL,
    checked_at INTEGER NOT NULL, credited_step INTEGER, discounted_credit REAL NOT NULL,
    reason TEXT NOT NULL, PRIMARY KEY (episode, event_id)
);
"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class MemoryStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    def observe(self, episode, step, text):
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO turns VALUES (?, ?, ?)", (episode, step, text))
            stored = self.db.execute(
                "SELECT text FROM turns WHERE episode=? AND step=?", (episode, step)
            ).fetchone()
            if stored["text"] != text:
                raise ValueError("An observed turn cannot be replaced.")

    def _versions(self, episode, target, context, before):
        return list(self.db.execute(
            """SELECT * FROM versions WHERE episode=? AND target=? AND context=? AND step<?
            ORDER BY step DESC""", (episode, target, context, before)
        ))

    @staticmethod
    def _winner(versions, reference):
        return next((v for v in versions if v["valid_from"] <= reference and (
            v["valid_until"] is None or reference < v["valid_until"]
        )), None)

    def lookup(self, episode, target, context, reference, before):
        """Resolve the effective value from versions observed before the reader's step."""
        row = self._winner(self._versions(episode, target, context, before), reference)
        return dict(row) if row is not None and row["value"] is not None else None

    def allowed(self, episode, step, candidate):
        """All valid operations for this scope, in a stable order."""
        if candidate is None:
            return (Action.SKIP,)
        versions = self._versions(episode, candidate.target, candidate.context, step)
        first = self._winner(versions, candidate.valid_from)
        first_id = first["step"] if first else None
        bounds = {point for v in versions for point in (v["valid_from"], v["valid_until"])
                  if point is not None and candidate.covers(point)}
        for point in bounds:
            other = self._winner(versions, point)
            if (other["step"] if other else None) != first_id:
                return (Action.SKIP,)
        if first is None or first["value"] is None:
            return (Action.SKIP, Action.WRITE)
        change = Action.MERGE if first["value"] == candidate.value else Action.UPDATE
        return (Action.SKIP, Action.RETAIN, change, Action.ARCHIVE)

    def _last_decision(self, episode):
        return self.db.execute(
            """SELECT max(step) FROM (
                SELECT step FROM operations WHERE episode=?
                UNION ALL SELECT step FROM answers WHERE episode=?
                UNION ALL SELECT checked_at AS step FROM feedback WHERE episode=?
            )""", (episode, episode, episode)
        ).fetchone()[0]

    def apply(self, episode, step, action, candidate=None):
        action = Action(action)
        request = _json({"action": action, "candidate": asdict(candidate) if candidate else None})
        with self.transaction():
            saved = self.db.execute(
                "SELECT * FROM operations WHERE episode=? AND step=?", (episode, step)
            ).fetchone()
            if saved is not None:
                if saved["request"] != request:
                    raise ValueError("The operation step is already committed.")
                return saved["after_step"]
            last = self._last_decision(episode)
            if last is not None and step <= last:
                raise ValueError("Operations must follow the recorded episode timeline.")
            if action not in self.allowed(episode, step, candidate):
                raise ValueError("The operation is incompatible with the candidate or its interval.")
            prior = self.lookup(episode, candidate.target, candidate.context,
                                candidate.valid_from, step) if candidate else None
            before = prior["step"] if prior else None
            after = before
            if action in (Action.WRITE, Action.UPDATE, Action.MERGE, Action.ARCHIVE):
                after = step
            self.db.execute("INSERT INTO operations VALUES (?,?,?,?,?)",
                            (episode, step, request, before, after))
            if after == step:
                sources = [candidate.source]
                if action in (Action.MERGE, Action.ARCHIVE):
                    sources = sorted(set([*json.loads(prior["sources"]), *sources]))
                self.db.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?)", (
                    episode, step, candidate.target, candidate.context, candidate.valid_from,
                    candidate.valid_until, None if action is Action.ARCHIVE else candidate.value,
                    _json(sources)
                ))
            return after

    def record_answer(self, episode, answer_id, step, reference, context, claims, presented):
        presented = tuple(dict.fromkeys(presented))
        record = (episode, answer_id, step, reference, context, _json(claims), _json(presented))
        with self.transaction():
            saved = self.db.execute("SELECT * FROM answers WHERE episode=? AND answer_id=?",
                                    (episode, answer_id)).fetchone()
            if saved is not None:
                if tuple(saved) != record:
                    raise ValueError("The answer trace is already committed.")
                return
            last = self._last_decision(episode)
            if last is not None and step <= last:
                raise ValueError("Answers must follow the recorded episode timeline.")
            for version_step in presented:
                if version_step >= step or self._version(episode, version_step) is None:
                    raise ValueError("Presented versions must exist in the answer's visible history.")
            self.db.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?)", record)

    def _version(self, episode, step):
        return self.db.execute("SELECT * FROM versions WHERE episode=? AND step=?",
                               (episode, step)).fetchone()

    def _verify_span(self, episode, support, now):
        if support.step > now:
            raise ValueError("Evidence must have been observed before credit is evaluated.")
        row = self.db.execute("SELECT text FROM turns WHERE episode=? AND step=?",
                              (episode, support.step)).fetchone()
        if row is None or not 0 <= support.start < support.end <= len(row["text"]):
            raise ValueError("Evidence offsets must identify a nonempty observed span.")
        if row["text"][support.start:support.end] != support.quote:
            raise ValueError("The evidence quote disagrees with the recorded dialogue.")

    def credit(self, episode, event, now, *, gamma=0.95,
               implicit_weights=(1 / 3, 1 / 3, 1 / 3),
               explicit_scale=1.0, implicit_scale=1.0):
        """Store a delayed reward once. Return the credited operation, amount and reason."""
        if not 0 <= gamma < 1 or len(implicit_weights) != 3 or not all(
            math.isfinite(w) and w >= 0 for w in implicit_weights
        ) or not math.isclose(sum(implicit_weights), 1.0):
            raise ValueError("Invalid discount or implicit reliability weights.")
        if not all(math.isfinite(w) and w >= 0 for w in (explicit_scale, implicit_scale)):
            raise ValueError("Feedback scales must be finite and nonnegative.")
        if now < event.arrival or event.scope.step != event.arrival:
            raise ValueError("The scope span must accompany the observed feedback turn.")
        derived = (event.link, event.rationale, event.confirmation)
        if event.confirmation and event.confirmation.step <= event.arrival:
            raise ValueError("Confirmation must follow feedback arrival.")
        with self.transaction():
            for evidence in (event.scope, *derived):
                if evidence is not None:
                    self._verify_span(episode, evidence, now)
            core = _json([event.arrival, event.answer_id, event.channel, event.intent,
                          asdict(event.expected), asdict(event.scope), event.signal,
                          gamma, tuple(implicit_weights), explicit_scale, implicit_scale])
            evidence = _json([asdict(s) if s is not None else None for s in derived])
            previous = self.db.execute("SELECT * FROM feedback WHERE episode=? AND event_id=?",
                                       (episode, event.event_id)).fetchone()
            if previous is not None:
                if core != previous["core"] or now < previous["checked_at"]:
                    raise ValueError("Feedback event identity and settings must stay fixed.")
                for old, new in zip(json.loads(previous["evidence"]), json.loads(evidence)):
                    if old is not None and old != new:
                        raise ValueError("Evidence for a feedback event can only be appended.")
                if previous["reason"] != "awaiting_implicit_support":
                    return previous["credited_step"], previous["discounted_credit"], previous["reason"]
            last = self._last_decision(episode)
            if last is not None and now < last:
                raise ValueError("New feedback credit cannot be backdated.")
            answer = self.db.execute("SELECT * FROM answers WHERE episode=? AND answer_id=?",
                                     (episode, event.answer_id)).fetchone()
            if answer is None or answer["step"] >= event.arrival:
                raise ValueError("Historical credit requires an earlier answer in the same episode.")
            reliability = 1.0
            if event.channel == "implicit":
                reliability = sum(weight for weight, span in zip(implicit_weights, derived) if span)
            step, reason = self._attribute(episode, event, answer, reliability)
            factor = explicit_scale if event.channel == "explicit" else implicit_scale * reliability
            amount = factor * event.signal * gamma ** (now - step) if step is not None else 0.0
            self.db.execute(
                """INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(episode,event_id) DO UPDATE SET evidence=excluded.evidence,
                  checked_at=excluded.checked_at, credited_step=excluded.credited_step,
                  discounted_credit=excluded.discounted_credit, reason=excluded.reason""",
                (episode, event.event_id, core, evidence, now, step, amount, reason)
            )
            return step, amount, reason

    def _attribute(self, episode, event, answer, reliability):
        fact, reference = event.expected, answer["reference"]
        if event.intent != "retrospective" or event.signal == 0:
            return None, "no_historical_signal"
        if fact.context != answer["context"] or not fact.covers(reference):
            return None, "scope_mismatch"
        if event.channel == "implicit" and (
            event.link is None or (event.rationale is None and event.confirmation is None)
            or reliability == 0
        ):
            return None, "awaiting_implicit_support"
        claim = json.loads(answer["claims"]).get(fact.target)
        current = self.lookup(episode, fact.target, fact.context, reference, answer["step"])
        presented = [self._version(episode, step) for step in json.loads(answer["presented"])]
        if current is None or not any(v["step"] == current["step"] for v in presented):
            return None, "current_version_not_presented"
        if claim is None or claim != current["value"]:
            return None, "claim_does_not_match_memory"
        correct = claim == fact.value
        if correct != (event.signal > 0):
            return None, "effect_disagrees_with_feedback"
        if not correct and any(
            v["target"] == fact.target and v["context"] == fact.context
            and v["value"] == fact.value and v["valid_from"] <= reference
            and (v["valid_until"] is None or reference < v["valid_until"]) for v in presented
        ):
            return None, "supported_value_also_presented"
        operations = self.db.execute(
            "SELECT * FROM operations WHERE episode=? AND step<? AND after_step=?",
            (episode, answer["step"], current["step"])).fetchall()
        matches = []
        for op in operations:
            request = json.loads(op["request"])
            before = self._version(episode, op["before_step"]) if op["before_step"] is not None else None
            if request["action"] in (Action.WRITE, Action.UPDATE):
                if correct and (before is None or before["value"] != fact.value):
                    matches.append(op["step"])
                elif not correct and (before is None or before["value"] == fact.value):
                    matches.append(op["step"])
            if request["action"] == Action.RETAIN and not correct:
                rejected = Fact(**request["candidate"])
                if rejected.covers(reference) and rejected.value == fact.value:
                    matches.append(op["step"])
        if len(matches) != 1:
            return None, "ambiguous_operation" if matches else "no_supported_effect"
        return matches[0], "assigned"

    def direct_rewards(self, episode, end):
        """Discounted actor-only credit for an exclusive rollout end."""
        return dict(self.db.execute(
            """SELECT credited_step, sum(discounted_credit) FROM feedback
            WHERE episode=? AND checked_at<? AND credited_step IS NOT NULL
            GROUP BY credited_step""", (episode, end)
        ).fetchall())

