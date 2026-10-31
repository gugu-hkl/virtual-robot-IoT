"""FastAPI 服务：网页、状态查询与机器人控制。"""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stage2.backend_bridge import (
    BACKEND,
    BackendError,
    get_backend_status,
    send_backend_command,
)
from stage3.state_bridge import get_robot_status
from stage3.display_selection import display_selection


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title=f"机器人设备服务（{BACKEND}）")
app.mount(
    "/static",
    StaticFiles(directory=str(WEB_DIR)),
    name="static",
)


class MoveRequest(BaseModel):
    direction: Literal[
        "forward",
        "backward",
        "left",
        "right",
    ]
    speed: float = Field(
        gt=0,
        le=20,
        description="轮缘目标速度，cm/s",
    )
    duration_s: float = Field(
        gt=0,
        le=60,
        description="仿真时长，秒",
    )


class TaskRequest(BaseModel):
    name: Literal["forward", "square", "circle"]


class DisplaySelectionRequest(BaseModel):
    robot_id: Literal["a", "b"] | None


def backend_error(exc):
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
    ) from exc


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/status")
def get_status():
    try:
        return get_backend_status()
    except BackendError as exc:
        backend_error(exc)


@app.get("/robots/{robot_id}/status")
def get_dual_robot_status(robot_id: str):
    """查询双机器人世界中 a 或 b 的最新里程计状态。"""
    if robot_id not in ("a", "b"):
        raise HTTPException(status_code=404, detail="机器人标号只能是 a 或 b")
    try:
        return get_robot_status(robot_id)
    except BackendError as exc:
        backend_error(exc)


@app.post("/display/selection")
def set_display_selection(request: DisplaySelectionRequest):
    """手动选择 OLED 显示 a、b，或用 null 清除选择。"""
    robot_id, revision = display_selection.select(request.robot_id)
    return {"selected_robot": robot_id, "selection_revision": revision}


@app.get("/display/state")
def get_display_state():
    """ESP32 轮询：只返回当前选中机器人的新鲜状态。"""
    robot_id, revision = display_selection.snapshot()
    if robot_id is None:
        return {
            "state": "waiting",
            "selected_robot": None,
            "selection_revision": revision,
        }

    try:
        status = get_robot_status(robot_id)
    except BackendError as exc:
        current_id, current_revision = display_selection.snapshot()
        if current_revision != revision:
            return {
                "state": "switching",
                "selected_robot": current_id,
                "selection_revision": current_revision,
            }
        if "数据过期" in exc.detail:
            code = "data_stale"
        elif exc.status_code == 502:
            code = "invalid_status"
        else:
            code = "backend_unavailable"
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": code,
                "selected_robot": robot_id,
                "message": exc.detail,
            },
        ) from exc

    current_id, current_revision = display_selection.snapshot()
    if current_revision != revision:
        return {
            "state": "switching",
            "selected_robot": current_id,
            "selection_revision": current_revision,
        }
    return {
        "state": "live",
        "selected_robot": robot_id,
        "selection_revision": revision,
        "status": status,
    }


@app.get("/sensor")
def get_sensor():
    # 固定模拟读数，不代表 Webots 真实传感器。
    return {
        "distance": 100,
        "temperature": 25,
    }


@app.post("/move")
def move(request: MoveRequest):
    try:
        return send_backend_command({
            "action": "move",
            "direction": request.direction,
            "speed": request.speed,
            "duration_s": request.duration_s,
        })
    except BackendError as exc:
        backend_error(exc)


@app.post("/stop")
def stop():
    try:
        return send_backend_command({
            "action": "stop",
        })
    except BackendError as exc:
        backend_error(exc)


@app.post("/task")
def task(request: TaskRequest):
    try:
        return send_backend_command({
            "action": "task",
            "name": request.name,
        })
    except BackendError as exc:
        backend_error(exc)
