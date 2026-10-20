"""FastAPI 服务：提供网页，并将状态查询转发给 Webots 控制器。"""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stage2.webots_bridge import WebotsUnavailable, get_webots_status


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Webots 机器人设备服务")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class MoveRequest(BaseModel):
    direction: Literal["forward", "backward", "left", "right"]
    speed: float = Field(gt=0, le=100, description="速度，cm/s")
    duration_s: float = Field(gt=0, le=60, description="持续时间，秒")


class TaskRequest(BaseModel):
    name: Literal["forward", "square"]


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/status")
def get_status():
    try:
        return get_webots_status()
    except WebotsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/sensor")
def get_sensor():
    # 仍是第一阶段的固定模拟读数，不代表 Webots 传感器。
    return {"distance": 100, "temperature": 25}


@app.post("/move")
def move(request: MoveRequest):
    raise HTTPException(
        status_code=503,
        detail="Webots 车轮控制尚未接入，请先验收状态通信",
    )


@app.post("/stop")
def stop():
    raise HTTPException(
        status_code=503,
        detail="Webots 停止控制尚未接入，请先验收状态通信",
    )


@app.post("/task")
def task(request: TaskRequest):
    raise HTTPException(
        status_code=503,
        detail="Webots 预设轨迹尚未接入，请先验收状态通信",
    )