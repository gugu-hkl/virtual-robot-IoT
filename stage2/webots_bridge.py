"""FastAPI 与 Ubuntu 本机 Webots 控制器之间的 HTTP 通信。"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CONTROLLER_URL = "http://127.0.0.1:8765"


class WebotsError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def request_controller(method, path, payload=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{CONTROLLER_URL}{path}",
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
            detail = error_data.get("error", "Webots 控制器拒绝请求")
        except (ValueError, AttributeError):
            detail = "Webots 控制器拒绝请求"
        raise WebotsError(exc.code, detail) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WebotsError(
            503,
            "无法连接 Webots 控制器，或等待控制器响应超时",
        ) from exc
    except ValueError as exc:
        raise WebotsError(502, "控制器返回的不是有效 JSON") from exc

    if not isinstance(result, dict):
        raise WebotsError(502, "控制器返回的数据格式无效")

    return result


def get_webots_status():
    status = request_controller("GET", "/status")

    if not isinstance(status.get("position"), dict):
        raise WebotsError(502, "控制器状态缺少 position")

    return status


def send_webots_command(payload):
    result = request_controller("POST", "/command", payload)

    if not isinstance(result.get("status"), dict):
        raise WebotsError(502, "控制器响应缺少 status")

    return result