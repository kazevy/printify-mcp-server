import functools

import httpx


def handle_errors(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            details = {}
            content_type = e.response.headers.get("content-type", "")
            if content_type.startswith("application/json"):
                try:
                    details = e.response.json()
                except Exception:
                    pass
            return {
                "error": True,
                "status_code": e.response.status_code,
                "message": str(e),
                "details": details,
            }
        except ValueError as e:
            return {
                "error": True,
                "status_code": 400,
                "message": str(e),
                "details": {},
            }

    return wrapper
