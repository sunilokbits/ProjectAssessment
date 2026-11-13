"""Request identity.

Placeholder authorisation: the caller's identity and role come from headers
(``X-User-Name`` / ``X-User-Role``). Replace with the platform's SSO/OIDC
integration; the role checks below stay the same.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

ROLES = {"admin", "reviewer", "assessor", "viewer"}


@dataclass
class User:
    name: str
    role: str

    @property
    def can_review(self) -> bool:
        return self.role in ("admin", "reviewer")


def current_user(x_user_name: str | None = Header(default=None), x_user_role: str | None = Header(default=None)) -> User:
    role = (x_user_role or "assessor").lower()
    if role not in ROLES:
        raise HTTPException(400, f"unknown role '{role}'")
    return User(name=x_user_name or "anonymous", role=role)


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Domain Management requires the admin role")
    return user


def require_reviewer(user: User = Depends(current_user)) -> User:
    if not user.can_review:
        raise HTTPException(403, "this action requires an authorised reviewer (reviewer or admin role)")
    return user


def require_editor(user: User = Depends(current_user)) -> User:
    if user.role == "viewer":
        raise HTTPException(403, "viewers cannot modify assessments")
    return user
