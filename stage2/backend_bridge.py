"""FastAPI 到本机机器人后端的 HTTP 通信。"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND = os.getenv("ROBOT_BACKEND", "direct").strip().lower()

BACKEND_URLS = {
    "direct": "http://127.0.0.1:8765",
    "ros": "http://127.0.0.1:8766",
}

if BACKEND not in BACKEND_URLS:
    raise RuntimeError(
        "ROBOT_BACKEND 只能是 direct 或 ros"
    )

BACKEND_URL = BACKEND_URLS[BACKEND]


class BackendError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def request_backend(method, path, payload=None, base_url=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base_url or BACKEND_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=2.0) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            error_data = json.load(exc)
            detail = error_data.get(
                "error",
                "机器人后端拒绝了请求",
            )
        except (ValueError, AttributeError):
            detail = "机器人后端拒绝了请求"

        raise BackendError(exc.code, detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        backend_name = "双机器人状态网关" if base_url else f"{BACKEND} 后端"
        raise BackendError(
            503,
            f"无法连接{backend_name}，或等待响应超时",
        ) from exc
    except ValueError as exc:
        raise BackendError(
            502,
            "机器人后端返回的不是有效 JSON",
        ) from exc

    if not isinstance(result, dict):
        raise BackendError(
            502,
            "机器人后端返回的数据格式无效",
        )

    return result


def get_backend_status():
    status = request_backend("GET", "/status")

    if not isinstance(status.get("position"), dict):
        raise BackendError(
            502,
            "机器人状态缺少 position",
        )

    return status


def send_backend_command(payload):
    result = request_backend(
        "POST",
        "/command",
        payload,
    )

    if not isinstance(result.get("status"), dict):
        raise BackendError(
            502,
            "控制响应缺少 status",
        )

    return result
