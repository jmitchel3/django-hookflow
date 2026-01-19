from __future__ import annotations

import functools
import logging
import time
from collections import defaultdict
from typing import Any
from typing import Callable

from django.conf import settings
from django.http import HttpRequest
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter storage
# Format: {ip_address: [(timestamp, ...], ...}
_rate_limit_storage: dict[str, list[float]] = defaultdict(list)


def _get_api_auth_required() -> bool:
    """Check if API authentication is required."""
    return getattr(settings, "HOOKFLOW_API_AUTH_REQUIRED", True)


def _get_api_auth_backend() -> str | None:
    """Get the configured authentication backend."""
    return getattr(settings, "HOOKFLOW_API_AUTH_BACKEND", None)


def _get_api_key() -> str | None:
    """Get the configured API key for simple auth."""
    return getattr(settings, "HOOKFLOW_API_KEY", None)


def _authenticate_django_user(request: HttpRequest) -> bool:
    """
    Authenticate using Django's built-in authentication.

    Returns True if the user is authenticated.
    """
    return hasattr(request, "user") and request.user.is_authenticated


def _authenticate_api_key(request: HttpRequest) -> bool:
    """
    Authenticate using an API key from the Authorization header.

    Expects header format: "Bearer <api_key>" or "Api-Key <api_key>"
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning(
            "HOOKFLOW_API_KEY not configured but API key auth enabled"
        )
        return False

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        provided_key = auth_header[7:]
    elif auth_header.startswith("Api-Key "):
        provided_key = auth_header[8:]
    else:
        return False

    return provided_key == api_key


def _authenticate_custom(request: HttpRequest) -> bool:
    """
    Authenticate using a custom backend function.

    The backend should be a dotted path to a function that takes
    a request and returns True if authenticated.
    """
    backend_path = _get_api_auth_backend()
    if not backend_path:
        return False

    try:
        module_path, func_name = backend_path.rsplit(".", 1)
        import importlib

        module = importlib.import_module(module_path)
        auth_func = getattr(module, func_name)
        return auth_func(request)
    except (ValueError, ImportError, AttributeError):
        logger.exception(
            "Failed to load custom auth backend '%s'", backend_path
        )
        return False


def _authenticate_request(request: HttpRequest) -> bool:
    """
    Authenticate a request using the configured authentication method.

    Authentication methods are tried in order:
    1. Custom backend (if HOOKFLOW_API_AUTH_BACKEND is set)
    2. API key (if HOOKFLOW_API_KEY is set)
    3. Django user authentication

    Returns True if any authentication method succeeds.
    """
    backend = _get_api_auth_backend()

    # If custom backend is configured, use it exclusively
    if backend:
        return _authenticate_custom(request)

    # Try API key auth first
    api_key = _get_api_key()
    if api_key:
        if _authenticate_api_key(request):
            return True

    # Fall back to Django user auth
    return _authenticate_django_user(request)


def require_api_auth(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to require authentication for API endpoints.

    If HOOKFLOW_API_AUTH_REQUIRED is False (default True), authentication
    is bypassed.

    Authentication methods:
    - Custom backend: Set HOOKFLOW_API_AUTH_BACKEND to dotted path
    - API key: Set HOOKFLOW_API_KEY and send Authorization header
    - Django auth: Uses request.user.is_authenticated

    Returns:
        401 response if authentication fails, otherwise calls view
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        # Check if auth is required
        if not _get_api_auth_required():
            return view_func(request, *args, **kwargs)

        # Authenticate the request
        if not _authenticate_request(request):
            logger.warning(
                "API authentication failed for %s %s from %s",
                request.method,
                request.path,
                request.META.get("REMOTE_ADDR", "unknown"),
            )
            return JsonResponse(
                {"error": "Authentication required"},
                status=401,
            )

        return view_func(request, *args, **kwargs)

    return wrapper


def _get_rate_limit() -> tuple[int, int] | None:
    """
    Get rate limit configuration.

    Returns tuple of (max_requests, window_seconds) or None if disabled.
    """
    config = getattr(settings, "HOOKFLOW_RATE_LIMIT", None)
    if config is None:
        return None

    if isinstance(config, tuple) and len(config) == 2:
        return config

    # Default: 100 requests per minute
    if config is True:
        return (100, 60)

    return None


def _get_client_ip(request: HttpRequest) -> str:
    """Get the client IP address from the request."""
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _is_rate_limited(ip: str, max_requests: int, window_seconds: int) -> bool:
    """
    Check if the IP is rate limited.

    Uses a sliding window approach with in-memory storage.
    """
    now = time.time()
    cutoff = now - window_seconds

    # Clean old entries
    _rate_limit_storage[ip] = [
        ts for ts in _rate_limit_storage[ip] if ts > cutoff
    ]

    # Check limit
    if len(_rate_limit_storage[ip]) >= max_requests:
        return True

    # Record this request
    _rate_limit_storage[ip].append(now)
    return False


def rate_limit(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to apply rate limiting to API endpoints.

    Configure via HOOKFLOW_RATE_LIMIT setting:
    - None or False: No rate limiting
    - True: Default rate limit (100 requests/minute)
    - (max_requests, window_seconds): Custom limit

    Returns:
        429 response if rate limited, otherwise calls view
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        limit_config = _get_rate_limit()
        if limit_config is None:
            return view_func(request, *args, **kwargs)

        max_requests, window_seconds = limit_config
        client_ip = _get_client_ip(request)

        if _is_rate_limited(client_ip, max_requests, window_seconds):
            logger.warning(
                "Rate limit exceeded for %s on %s %s",
                client_ip,
                request.method,
                request.path,
            )
            return JsonResponse(
                {"error": "Rate limit exceeded"},
                status=429,
            )

        return view_func(request, *args, **kwargs)

    return wrapper
