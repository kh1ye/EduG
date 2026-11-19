"""Run a synthetic TraceCon replay without an LLM or benchmark data."""

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .memory import Action, Fact, Feedback, MemoryStore, Support
from .rollout import Transition, ppo_targets


def require(condition, label):
    if not condition:
        raise AssertionError(label)
    return label


def observed_span(store, episode, step, text):
    store.observe(episode, step, text)
    return Support(step, 0, len(text), text)


def replay(store):
    checks = []
    london = Fact("home", "London", "turn:1", 0)
    paris = Fact("home", "Paris", "turn:2", 10)

    def prepare(episode, action, presented, claim):
        store.apply(episode, 1, Action.WRITE, london)
        store.apply(episode, 2, action, paris)
        store.record_answer(episode, "qa", 3, 12, "personal", {"home": claim}, presented)
        span = observed_span(store, episode, 4, "My home is London.")
        return Feedback("event", 4, "qa", "explicit", "retrospective", london, span, -1)

    event = prepare("write-error", Action.UPDATE, [2], "Paris")
    checks.append(require(store.lookup("write-error", "home", "personal", 9, 10)["value"] == "London",
                          "future-effective update preserves historical lookup"))
    checks.append(require(store.lookup("write-error", "home", "personal", 12, 2)["value"] == "London",
                          "unobserved update is invisible"))
    credited = store.credit("write-error", event, 4)
    checks.append(require(credited[0] == 2 and credited[1] < 0, "harmful overwrite receives credit"))
    checks.append(require(store.credit("write-error", event, 4) == credited, "feedback retry is idempotent"))
    checks.append(require(store.direct_rewards("write-error", 4) == {}, "rollout end is exclusive"))
    checks.append(require(store.direct_rewards("write-error", 5) == {2: credited[1]},
                          "completed rollout contains one credit"))
    event = prepare("retrieval-error", Action.UPDATE, [1], "London")
    event = replace(event, expected=paris)
    checks.append(require(store.credit("retrieval-error", event, 4)[2] == "current_version_not_presented",
                          "stale retrieval produces no write credit"))
    event = prepare("answer-error", Action.RETAIN, [1], "Paris")
    checks.append(require(store.credit("answer-error", event, 4)[2] == "claim_does_not_match_memory",
                          "generation mismatch produces no write credit"))

    store.apply("missed-update", 1, Action.WRITE, paris)
    store.apply("missed-update", 2, Action.RETAIN, replace(london, valid_from=10))
    store.record_answer("missed-update", "qa", 3, 12, "personal", {"home": "Paris"}, [1])
    span = observed_span(store, "missed-update", 4, "I live in London.")
    event = Feedback("event", 4, "qa", "explicit", "retrospective", london, span, -1)
    checks.append(require(store.credit("missed-update", event, 4)[0] is None,
                          "competing write and retain candidates cause abstention"))

    store.apply("retain-only", 1, Action.WRITE, replace(paris, valid_from=0))
    store.apply("retain-only", 2, Action.MERGE, replace(paris, valid_from=0, source="turn:3"))
    store.apply("retain-only", 3, Action.RETAIN, replace(london, valid_from=10))
    store.record_answer("retain-only", "qa", 4, 12, "personal", {"home": "Paris"}, [2])
    span = observed_span(store, "retain-only", 5, "Why did you pick Paris again?")
    event = Feedback("event", 5, "qa", "implicit", "retrospective", london, span, -1, link=span)
    checks.append(require(store.credit("retain-only", event, 5)[2] == "awaiting_implicit_support",
                          "implicit link alone cannot assign credit"))
    confirm = observed_span(store, "retain-only", 6, "I meant that my home is London.")
    credit = store.credit("retain-only", replace(event, confirmation=confirm), 6)
    checks.append(require(credit[0] == 3 and credit[1] < 0,
                          "later confirmation credits the supported missed update at its arrival"))

    store.apply("operations", 1, Action.SKIP)
    store.apply("operations", 2, Action.WRITE, paris)
    replacement = replace(paris, source="turn:extra")
    store.apply("operations", 3, Action.MERGE, replacement)
    merged = store.lookup("operations", "home", "personal", 10, 4)
    checks.append(require(json.loads(merged["sources"]) == ["turn:2", "turn:extra"],
                          "merge preserves both supporting sources"))
    store.apply("operations", 4, Action.ARCHIVE, replace(replacement, valid_from=20))
    checks.append(require(store.lookup("operations", "home", "personal", 20, 5) is None
                          and store.lookup("operations", "home", "personal", 19, 5) is not None,
                          "archiving removes only the selected interval from ordinary lookup"))
    checks.append(require(store.apply("operations", 4, Action.ARCHIVE,
                                       replace(replacement, valid_from=20)) == 4,
                          "operation retry is idempotent"))
    try:
        store.record_answer("unrelated", "qa", 5, 12, "personal", {"home": "Paris"}, [2])
    except ValueError:
        checks.append("answer traces cannot cite another episode's versions")
    else:
        raise AssertionError("episode isolation")
    try:
        store.apply("write-error", 0, Action.WRITE, paris)
    except ValueError:
        checks.append("out-of-order writes cannot change an earlier answer's evidence")
    else:
        raise AssertionError("historical operation was accepted")
    try:
        store.record_answer("write-error", "older-answer", 2, 12, "personal", {}, [])
    except ValueError:
        checks.append("late answer records cannot rewrite the timeline")
    else:
        raise AssertionError("out-of-order answer")
    try:
        bad_span = replace(confirm, quote="Fabricated confirmation")
        store.credit("retain-only", replace(event, confirmation=bad_span), 6)
    except ValueError:
        checks.append("unobserved evidence spans are rejected")
    else:
        raise AssertionError("unobserved evidence accepted")

    event = prepare("competing-evidence", Action.UPDATE, [1, 2], "Paris")
    checks.append(require(store.credit("competing-evidence", event, 4)[2]
                          == "supported_value_also_presented",
                          "correct competing evidence blocks negative write credit"))
    event = prepare("prospective", Action.UPDATE, [2], "Paris")
    checks.append(require(store.credit("prospective", replace(event, intent="prospective"), 4)[0]
                          is None, "a future request gives no historical credit"))
    event = prepare("positive", Action.UPDATE, [2], "Paris")
    accepted = observed_span(store, "positive", 5, "Yes, my new home is Paris.")
    event = replace(event, expected=paris, scope=accepted, arrival=5, signal=1)
    checks.append(require(store.credit("positive", event, 5)[0] == 2
                          and store.direct_rewards("positive", 6)[2] > 0,
                          "supported improvements receive positive credit"))

    unchanged = ppo_targets([Transition(1, 0, 0, 0.5), Transition(2, 1, 0, 0.5)], {})
    changed = ppo_targets([Transition(1, 0, 0, 0.5), Transition(2, 1, 0, 0.5)], {2: credited[1]})
    checks.append(require(unchanged[0] == changed[0]
                          and unchanged[1].critic_target == changed[1].critic_target
                          and changed[1].actor_advantage < unchanged[1].actor_advantage,
                          "operation credit changes only the corresponding actor advantage"))
    return checks


def main():
    with TemporaryDirectory() as folder:
        path = Path(folder) / "tracecon.sqlite3"
        store = MemoryStore(path)
        try:
            checks = replay(store)
        finally:
            store.close()
        store = MemoryStore(path)
        try:
            require(len(store.direct_rewards("write-error", 5)) == 1, "persisted credit ledger")
        finally:
            store.close()
    print(json.dumps({"passed": len(checks) + 1, "checks": [*checks, "persisted credit ledger"]},
                     indent=2))


if __name__ == "__main__":
    main()
