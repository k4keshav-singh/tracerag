"""Reciprocal rank fusion.

RRF combines ranked lists using only *positions*, never the underlying scores.
That is exactly what this project needs: BM25 scores and cosine similarities
live on different, non-comparable scales, so any score-level combination would
need a normalisation step that is itself a tuning decision. Ranks sidestep it.

Reference: Cormack, Clarke and Buettcher, "Reciprocal Rank Fusion outperforms
Condorcet and individual Rank Learning Methods" (SIGIR 2009).
"""

from __future__ import annotations


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked ID lists into one ranking.

    Each list contributes ``1 / (k + rank)`` for each item, with ``rank``
    starting at 1. Items missing from a list simply contribute nothing from it.

    ``k`` damps the influence of the very top positions; 60 is the value from the
    original paper and the de-facto default.

    Ties are broken by the item's best (lowest) rank across the input lists, and
    then by ID, so the output is fully deterministic.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[str, float] = {}
    best_rank: dict[str, int] = {}

    for ranked in ranked_lists:
        for position, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + position)
            if item_id not in best_rank or position < best_rank[item_id]:
                best_rank[item_id] = position

    fused = sorted(
        scores.items(),
        key=lambda item: (-item[1], best_rank[item[0]], item[0]),
    )
    return fused[:top_k] if top_k is not None else fused
