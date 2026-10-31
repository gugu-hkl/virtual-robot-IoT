"""FastAPI 到双机器人 ROS 2 状态网关的本机 HTTP 通信。"""

from stage2.backend_bridge import BackendError, request_backend


DUAL_STATE_URL = "http://127.0.0.1:8767"


def get_robot_status(robot_id):
    result = request_backend(
        "GET",
        f"/robots/{robot_id}/status",
        base_url=DUAL_STATE_URL,
    )

    if (
        result.get("robot_id") != robot_id
        or result.get("position_source") != "odom"
        or not isinstance(result.get("position_m"), dict)
        or not all(key in result["position_m"] for key in ("x", "y"))
        or not isinstance(result.get("linear_m_s"), (int, float))
        or not isinstance(result.get("angular_rad_s"), (int, float))
        or not isinstance(result.get("yaw_deg"), (int, float))
    ):
        raise BackendError(502, "双机器人状态网关返回的数据格式无效")

    return result
