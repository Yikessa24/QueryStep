"""Choose the next practice item from server-approved, pre-scored candidates."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

Action = Literal["foundation", "consolidate", "advance"]


@dataclass(frozen=True)
class Candidate:
    item_id: int
    action: Action
    probability: float


def choose_next(candidates: list[Candidate], *, can_advance: bool) -> Candidate | None:
    if any(not isfinite(item.probability) or not 0 <= item.probability <= 1
           for item in candidates):
        raise ValueError("Candidate probabilities must be in [0, 1].")

    tiers = [
        [item for item in candidates
         if item.action == "advance" and can_advance and 0.65 <= item.probability <= 0.85],
        [item for item in candidates if item.action == "consolidate" and item.probability >= 0.55],
        [item for item in candidates if item.action == "foundation"],
    ]
    for eligible in tiers:
        if eligible:
            return min(eligible, key=lambda item: (abs(item.probability - 0.75), item.item_id))
    return None
