from __future__ import annotations

from typing import Protocol


class OidcIdentity(Protocol):
    provider: str
    external_id: str
    username: str
    display_name: str
    email: str | None
    department: str | None


class OidcAdapter(Protocol):
    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Return the provider authorization URL."""

    def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        """Exchange an authorization code for a provider access token."""

    def identity(self, *, access_token: str) -> OidcIdentity:
        """Resolve the provider identity into local user fields."""
