"""FastAPI 服务：网页、状态查询与 Webots 手动控制。"""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stage2.webots_bridge import (
    WebotsError,
    get_webots_status,
    send_webots_command,
)


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Webots 机器人设备服务")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class MoveRequest(BaseModel):
    direction: Literal["forward", "backward", "left", "right"]
    speed: float = Field(gt=0, le=20, description="轮缘目标速度，cm/s")
    duration_s: float = Field(gt=0, le=60, description="Webots 仿真时长，秒")


class TaskRequest(BaseModel):
    name: Literal["forward", "square", "circle"]


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/status")
def get_status():
    try:
        return get_webots_status()
    except WebotsError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@app.get("/sensor")
def get_sensor():
    # 第一阶段保留的固定模拟读数；不是 Webots 障碍物检测。
    return {"distance": 100, "temperature": 25}


@app.post("/move")
def move(request: MoveRequest):
    try:
        return send_webots_command({
            "action": "move",
            "direction": request.direction,
            "speed": request.speed,
            "duration_s": request.duration_s,
        })
    except WebotsError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@app.post("/stop")
def stop():
    try:
        return send_webots_command({"action": "stop"})
    except WebotsError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc


@app.post("/task")
def task(request: TaskRequest):
    try:
        return send_webots_command({
            "action": "task",
            "name": request.name,
        })
    except WebotsError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc