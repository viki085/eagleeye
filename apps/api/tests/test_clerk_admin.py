"""ClerkAdmin against a mocked Clerk Backend API (httpx MockTransport)."""

import json

import httpx
import pytest
from app.services import clerk_admin
from app.services.clerk_admin import ClerkAdmin, ClerkError, base_username

REAL_CLIENT = httpx.AsyncClient  # captured once, so patching twice in a test doesn't nest


def _patch(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:  # noqa: ANN001
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        kwargs["transport"] = httpx.MockTransport(record)
        return REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(clerk_admin.httpx, "AsyncClient", client)
    return seen


def _taken(param: str) -> httpx.Response:
    return httpx.Response(
        422, json={"errors": [{"code": "form_identifier_exists", "meta": {"param_name": param}}]}
    )


def test_base_username_is_clean_and_memorable() -> None:
    assert base_username("Jane.Doe@corp.com") == "jane_doe"
    assert base_username("sam+clerk_test@corp.com") == "sam_clerk_test"
    assert base_username("al@corp.com") == "al_user"  # Clerk needs at least 4 characters
    assert len(base_username(("x" * 80) + "@corp.com")) <= 60


async def test_create_sends_the_derived_username(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _patch(monkeypatch, lambda r: httpx.Response(200, json={"id": "user_1"}))
    result = await ClerkAdmin("sk").create_user("jane.doe@corp.com", "Jane", "Doe")
    assert result == ("user_1", True, "jane_doe")
    assert json.loads(seen[0].content)["username"] == "jane_doe"


async def test_taken_derived_username_gets_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["username"]
        return (
            _taken("username")
            if name in ("jane_doe", "jane_doe2")
            else httpx.Response(200, json={"id": "user_1"})
        )

    _patch(monkeypatch, handler)
    assert (await ClerkAdmin("sk").create_user("jane.doe@corp.com", "", ""))[2] == "jane_doe3"


async def test_a_chosen_username_that_is_taken_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, lambda r: _taken("username"))
    with pytest.raises(ClerkError) as exc:
        await ClerkAdmin("sk").create_user("j@corp.com", "", "", username="boss")
    assert exc.value.status == 422 and "boss" in exc.value.message


async def test_instances_without_usernames_retry_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "username" in json.loads(request.content):
            return httpx.Response(
                422,
                json={
                    "errors": [{"code": "form_param_unknown", "meta": {"param_name": "username"}}]
                },
            )
        return httpx.Response(200, json={"id": "user_1"})

    _patch(monkeypatch, handler)
    assert await ClerkAdmin("sk").create_user("a@corp.com", "", "") == ("user_1", True, None)


async def test_create_reuses_an_existing_clerk_account(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _taken("email_address")
        return httpx.Response(200, json=[{"id": "user_old", "username": "old_name"}])

    _patch(monkeypatch, handler)
    assert await ClerkAdmin("sk").create_user("x@corp.com", "", "") == (
        "user_old",
        False,
        "old_name",
    )


async def test_organization_is_discovered_when_there_is_exactly_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "org_1"}], "total_count": 1})
        return httpx.Response(200, json={"id": "mem_1"})

    seen = _patch(monkeypatch, handler)
    admin = ClerkAdmin("sk")
    await admin.add_to_organization("user_1")
    await admin.add_to_organization("user_2")
    assert [r.method for r in seen].count("GET") == 1  # discovered once, then cached
    assert seen[-1].url.path.endswith("/organizations/org_1/memberships")
    assert json.loads(seen[-1].content) == {"user_id": "user_2", "role": "org:member"}


async def test_organization_membership_is_idempotent_and_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        lambda r: httpx.Response(
            422, json={"errors": [{"code": "already_a_member_in_organization"}]}
        ),
    )
    await ClerkAdmin("sk", organization_id="org_x").add_to_organization("user_1")  # no raise
    _patch(monkeypatch, lambda r: httpx.Response(200, json={"data": [], "total_count": 0}))
    await ClerkAdmin("sk").add_to_organization("user_1")  # no organisations: nothing to join


async def test_several_organizations_without_config_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        lambda r: httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}], "total_count": 2}),
    )
    with pytest.raises(ClerkError) as exc:
        await ClerkAdmin("sk").add_to_organization("user_1")
    assert "CLERK_ORGANIZATION_ID" in exc.value.message


async def test_delete_treats_404_as_done_and_maps_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, lambda r: httpx.Response(404))
    await ClerkAdmin("sk").delete_user("user_gone")
    _patch(monkeypatch, lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(ClerkError) as exc:
        await ClerkAdmin("sk").delete_user("user_x")
    assert exc.value.status == 502 and "boom" not in exc.value.message
