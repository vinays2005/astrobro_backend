"""One error type for the marketplace services: a message for people, a status code, and a short code the app can act on."""
from __future__ import annotations

from fastapi import HTTPException


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400, code: str | None = None, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra

    def to_http(self) -> HTTPException:
        """Plain text for simple errors; a {error, message, ...} object when the app should react to a code."""
        if self.code is None:
            return HTTPException(status_code=self.status, detail=self.message)
        return HTTPException(status_code=self.status, detail={"error": self.code, "message": self.message, **self.extra})
