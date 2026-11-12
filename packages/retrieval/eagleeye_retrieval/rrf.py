"""Reciprocal Rank Fusion (C4 §4). Pure, order-stable."""

from collections.abc import Sequence

RRF_K = 60


def fuse(
    rankings: Sequence[Sequence[str]],
    weights: Sequence[float] | None = None,
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """score(id) = Σ_r w_r / (k + rank_r(id)), rank 1-based. Ties keep first-seen order."""
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights and rankings must have the same length")

    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    order = {item: i for i, item in enumerate(scores)}
    return sorted(scores.items(), key=lambda kv: (-kv[1], order[kv[0]]))
