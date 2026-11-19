"""Build PPO targets from frozen rollouts and a separate direct-credit ledger."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Transition:
    step: int
    outcome: float
    value: float
    old_probability: float


@dataclass(frozen=True)
class PolicyTarget:
    step: int
    old_probability: float
    critic_target: float
    actor_advantage: float


def ppo_targets(transitions, direct_credit, gamma=0.95):
    transitions = tuple(transitions)
    steps = [row.step for row in transitions]
    if steps != sorted(set(steps)) or not set(direct_credit) <= set(steps):
        raise ValueError("Transitions must be ordered and credit must reference their steps.")
    if not 0 <= gamma < 1:
        raise ValueError("Gamma must be in [0, 1).")
    result = []
    future_return = 0.0
    next_step = None
    for row in reversed(transitions):
        feedback = direct_credit.get(row.step, 0.0)
        if not (0 < row.old_probability <= 1 and all(
            math.isfinite(v) for v in (row.outcome, row.value, feedback)
        )):
            raise ValueError("Rollout probabilities and rewards must be valid.")
        if next_step is not None:
            future_return *= gamma ** (next_step - row.step)
        future_return += row.outcome
        result.append(PolicyTarget(
            row.step, row.old_probability, future_return, future_return - row.value + feedback
        ))
        next_step = row.step
    return tuple(reversed(result))
