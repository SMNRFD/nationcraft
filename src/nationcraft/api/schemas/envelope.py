"""Standardized API envelope.

Every endpoint returns ``{"ok": bool, "data": ..., "error": ...}`` so the
client (Telegram bot) can parse responses uniformly.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    ok: bool = True
    data: T | None = None
    error: dict[str, Any] | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


def success(data: Any = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def error(code: str, message: str, details: dict | None = None) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message, "details": details}}
