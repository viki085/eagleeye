"""Largest-Triangle-Three-Buckets: keeps the visual shape of a long series in few points."""

from collections.abc import Sequence


def lttb(points: Sequence[tuple[float, float]], threshold: int) -> list[int]:
    """Indices of the points to keep (always the first and last). `points` sorted by x."""
    n = len(points)
    if threshold >= n or threshold < 3:
        return list(range(n))
    keep = [0]
    bucket = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        start = int(i * bucket) + 1
        end = min(int((i + 1) * bucket) + 1, n - 1)
        nxt_end = min(int((i + 2) * bucket) + 1, n)
        nxt = points[end:nxt_end] or [points[-1]]
        avg_x = sum(p[0] for p in nxt) / len(nxt)
        avg_y = sum(p[1] for p in nxt) / len(nxt)
        ax, ay = points[a]
        best, best_area = start, -1.0
        for j in range(start, max(end, start + 1)):
            px, py = points[j]
            area = abs((ax - avg_x) * (py - ay) - (ax - px) * (avg_y - ay))
            if area > best_area:
                best, best_area = j, area
        keep.append(best)
        a = best
    keep.append(n - 1)
    return keep
