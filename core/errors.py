"""统一错误类型与错误码。

HTTP 层把 ``ApiError`` 转成 ``{"ok":false,"error":{...}}``；
services 层只抛 ``ApiError``，不关心 HTTP 细节。
"""

from __future__ import annotations

from typing import Any

# 错误码 -> HTTP 状态码（契约见 docs/API.md）
STATUS_BY_CODE: dict[str, int] = {
    "UNAUTHORIZED": 401,
    "RATE_LIMITED": 429,
    "VALIDATION_ERROR": 400,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "QUOTA_EXCEEDED": 409,
    "UPSTREAM_ERROR": 502,
    "INTERNAL": 500,
}


class ApiError(Exception):
    """业务错误：携带稳定错误码、可读消息与字段级细节。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_BY_CODE.get(code, 500)
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return error

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"ApiError({self.code}, {self.message!r}, status={self.status})"


def unauthorized(message: str = "令牌无效或已失效") -> ApiError:
    return ApiError("UNAUTHORIZED", message)


def not_found(message: str = "资源不存在") -> ApiError:
    return ApiError("NOT_FOUND", message)


def invalid(message: str, details: Any = None) -> ApiError:
    return ApiError("VALIDATION_ERROR", message, details=details)


def conflict(message: str) -> ApiError:
    return ApiError("CONFLICT", message)


def quota(message: str) -> ApiError:
    return ApiError("QUOTA_EXCEEDED", message)


def upstream(message: str) -> ApiError:
    return ApiError("UPSTREAM_ERROR", message)
