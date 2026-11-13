from app.repos.admin_overview import database_health, fold_models, rate
from app.services.health_checks import ServiceHealth


def test_fold_models_keeps_the_biggest_and_sums_the_rest_into_other() -> None:
    rows = [
        {"model_id": m, "cost_usd": c, "tokens": 10, "calls": 1}
        for m, c in [("a", 5.0), ("b", 4.0), ("c", 3.0), ("d", 2.0), ("e", 1.0), ("f", 0.5)]
    ]
    folded = fold_models(rows, keep=3)
    assert [r["model_id"] for r in folded] == ["a", "b", "c", "Other"]
    assert folded[-1] == {"model_id": "Other", "cost_usd": 3.5, "tokens": 30, "calls": 3}


def test_fold_models_leaves_short_lists_alone() -> None:
    rows = [{"model_id": "a", "cost_usd": 1.0, "tokens": 1, "calls": 1}]
    assert fold_models(rows, keep=5) == rows


def test_rate_handles_empty_periods() -> None:
    assert rate(3, 4) == 0.75
    assert rate(0, 0) is None


def test_database_health_summarises_the_pings() -> None:
    up = database_health(
        [ServiceHealth("supabase-pg", "up", 12), ServiceHealth("qdrant", "up", 30)]
    )
    assert up["status"] == "healthy" and up["up"] == 2 and up["total"] == 2
    assert up["primary_latency_ms"] == 12
    down = database_health([ServiceHealth("supabase-pg", "up", 9), ServiceHealth("qdrant", "down")])
    assert down["status"] == "degraded" and down["up"] == 1
    assert database_health([ServiceHealth("supabase-pg", "down")])["status"] == "down"
