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
