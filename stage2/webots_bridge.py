"""FastAPI 访问 Ubuntu 本机 Webots 控制器的客户端。"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


CONTROLLER_STATUS_URL = "http://127.0.0.1:8765/status"


class WebotsUnavailable(Exception):
    pass


def get_webots_status():
    try:
        with urlopen(CONTROLLER_STATUS_URL, timeout=1.0) as response:
            status = json.load(response)
    except HTTPError as exc:
        try:
            error_data = json.load(exc)
            reason = error_data.get("error", "控制器未提供有效状态")
        except (ValueError, AttributeError):
            reason = "控制器未提供有效状态"
        raise WebotsUnavailable(reason) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WebotsUnavailable(
            "无法连接 Webots 控制器，请检查仿真和外部控制器是否正在运行"
        ) from exc
    except ValueError as exc:
        raise WebotsUnavailable("控制器返回的不是有效 JSON") from exc

    if not isinstance(status, dict) or not isinstance(status.get("position"), dict):
        raise WebotsUnavailable("控制器返回的状态缺少 position")

    return status