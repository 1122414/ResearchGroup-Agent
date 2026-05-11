import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .logger import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.perf_counter()
        method = request.method
        path = request.url.path
        query = str(request.url.query)

        logger.info(
            "[REQ %s] %s %s%s | client=%s",
            request_id,
            method,
            path,
            f"?{query}" if query else "",
            request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
            duration = (time.perf_counter() - start) * 1000
            logger.info(
                "[RES %s] %s %s | status=%d | duration=%.2fms",
                request_id,
                method,
                path,
                response.status_code,
                duration,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            logger.error(
                "[ERR %s] %s %s | exception=%s | duration=%.2fms",
                request_id,
                method,
                path,
                exc,
                duration,
                exc_info=True,
            )
            raise
