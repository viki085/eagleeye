"""Clerk Backend API calls for admin user management (create / delete sign-in accounts,
company organisation membership).

The secret key never leaves the server. Errors are mapped to short, user-safe messages; Clerk's
raw response is logged, not returned.
"""

import logging
import re
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

CLERK_API = "https://api.clerk.com/v1"
TIMEOUT_S = 10.0
USERNAME_TRIES = 5  # jane_doe, jane_doe2 … jane_doe5


class ClerkError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def base_username(email: str) -> str:
    """A memorable username from the email's local part: jane.doe@corp.com -> jane_doe.
    Clerk usernames are 4-64 characters of letters, digits, '_' and '-'."""
    local = re.sub(r"[^a-z0-9_-]+", "_", email.split("@", 1)[0].lower()).strip("_-") or "user"
    if len(local) < 4:
        local = f"{local}_user"
    return local[:60]


def _errors(resp: httpx.Response) -> list[dict]:
    try:
        return list(resp.json().get("errors") or [])
    except (ValueError, AttributeError):
        return []


def _about(resp: httpx.Response, param: str) -> list[dict]:
    """Errors in a Clerk response that concern one request field."""
    out = []
    for err in _errors(resp):
        meta = err.get("meta") or {}
        params = [*(meta.get("param_names") or []), meta.get("param_name") or ""]
        if param in params:
            out.append(err)
    return out


class ClerkAdmin:
    def __init__(self, secret_key: str, organization_id: str = "") -> None:
        if not secret_key:
            logger.warning("CLERK_SECRET_KEY is not set: adding and deleting users will fail")
        self._headers = {"Authorization": f"Bearer {secret_key}"}
        # "" = not looked up yet; None = the instance has no organisation to join
        self._org_id: str | None = organization_id or ""

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                return await client.request(
                    method, f"{CLERK_API}{path}", headers=self._headers, **kwargs
                )
        except httpx.HTTPError as exc:
            logger.warning("clerk %s %s failed: %s", method, path, exc)
            raise ClerkError(502, "The sign-in service is unavailable. Try again.") from exc

    async def _find_user(self, email: str) -> dict | None:
        resp = await self._request("GET", f"/users?email_address={quote(email)}&limit=1")
        if resp.status_code != 200:
            logger.warning("clerk user lookup failed: %s %s", resp.status_code, resp.text[:300])
            raise ClerkError(502, "Could not check the sign-in service. Try again.")
        users = resp.json()
        return users[0] if users else None

    async def create_user(
        self, email: str, first_name: str, last_name: str, username: str | None = None
    ) -> tuple[str, bool, str | None]:
        """Returns (clerk_user_id, created, username). People sign in with the username or
        their email. A derived username that is taken gets a number; a chosen one does not.
        An existing Clerk account for the email is reused (created=False)."""
        body: dict[str, object] = {
            "email_address": [email],
            "first_name": first_name or None,
            "last_name": last_name or None,
            "skip_password_requirement": True,  # sign-in by email code or Google
        }
        base = username or base_username(email)
        candidates = (
            [base] if username else [base, *(f"{base}{n}" for n in range(2, USERNAME_TRIES + 1))]
        )
        for name in candidates:
            resp = await self._request("POST", "/users", json={**body, "username": name})
            if resp.status_code in (200, 201):
                return resp.json()["id"], True, name
            username_errors = _about(resp, "username")
            if any(e.get("code") == "form_identifier_exists" for e in username_errors):
                if username:
                    raise ClerkError(422, f'The username "{username}" is already taken.')
                continue  # try the next numbered variant
            if username_errors:  # this instance doesn't use usernames
                resp = await self._request("POST", "/users", json=body)
                if resp.status_code in (200, 201):
                    return resp.json()["id"], True, None
            return await self._create_failed(resp, email)
        raise ClerkError(422, f'Usernames based on "{base}" are taken; choose one in the form.')

    async def _create_failed(
        self, resp: httpx.Response, email: str
    ) -> tuple[str, bool, str | None]:
        if any(e.get("code") == "form_identifier_exists" for e in _about(resp, "email_address")):
            existing = await self._find_user(email)
            if existing:
                return existing["id"], False, existing.get("username")
        if resp.status_code == 429:
            raise ClerkError(
                429, "The sign-in service is rate limiting us. Wait a minute and retry."
            )
        if resp.status_code == 422:
            message = next((e.get("long_message") or e.get("message") for e in _errors(resp)), None)
            raise ClerkError(422, message or "The sign-in service rejected this user.")
        logger.warning("clerk create user failed: %s %s", resp.status_code, resp.text[:300])
        raise ClerkError(502, "Could not create the sign-in account. Try again.")

    async def _organization_id(self) -> str | None:
        """The company organisation new users join: configured, or discovered when the
        instance has exactly one. (Instances that require membership otherwise park a new
        user's session on a 'choose organisation' step.)"""
        if self._org_id != "":
            return self._org_id
        resp = await self._request("GET", "/organizations?limit=2")
        if resp.status_code != 200:
            logger.warning(
                "clerk organisations lookup failed (%s); skipping membership", resp.status_code
            )
            return None
        body = resp.json()
        orgs = body.get("data", []) if isinstance(body, dict) else body
        if len(orgs) > 1:
            raise ClerkError(500, "Several Clerk organisations exist: set CLERK_ORGANIZATION_ID.")
        self._org_id = orgs[0]["id"] if orgs else None
        return self._org_id

    async def add_to_organization(self, clerk_user_id: str) -> None:
        org_id = await self._organization_id()
        if org_id is None:
            return
        resp = await self._request(
            "POST",
            f"/organizations/{quote(org_id)}/memberships",
            json={"user_id": clerk_user_id, "role": "org:member"},  # app roles live in EagleEye
        )
        if resp.status_code in (200, 201):
            return
        if any("already" in str(e.get("code", "")) for e in _errors(resp)):
            return
        logger.warning("clerk add membership failed: %s %s", resp.status_code, resp.text[:300])
        raise ClerkError(502, "Could not add the user to your organisation in the sign-in service.")

    async def delete_user(self, clerk_user_id: str) -> None:
        resp = await self._request("DELETE", f"/users/{quote(clerk_user_id)}")
        if resp.status_code in (200, 404):  # 404: already gone, which is the goal
            return
        logger.warning("clerk delete user failed: %s %s", resp.status_code, resp.text[:300])
        raise ClerkError(502, "Could not remove the sign-in account. Try again.")
