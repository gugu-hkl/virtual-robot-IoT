from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from robot import Robot
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Literal

# 定义基础目录路径，获取当前文件所在目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent
# 定义web目录路径，为基础目录下的web子目录
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title = "虚拟机器人设备服务")
robot = Robot()

# 使用FastAPI的mount方法挂载静态文件目录
# "/static" 是URL路径前缀，所有以/static开头的请求都会被处理
# StaticFiles(directory=str(WEB_DIR)) 指定静态文件的实际存储目录
# name="static" 为这个静态文件挂载点命名，方便在代码中引用
app.mount(
    "/static",  # URL路径前缀
    StaticFiles(directory=str(WEB_DIR)),  # 静态文件目录配置
    name="static",  # 挂载点名称
)

class MoveRequest(BaseModel):
    direction: Literal['forward', 'backward', 'left', 'right']
    speed: float = Field(gt=0, le=100, description="速度, cm/s")
    duration_s: float = Field(gt=0, le=60, description="持续时间, 秒")

class TaskRequest(BaseModel):
    name: Literal['forward', 'square']

@app.get("/", include_in_schema=False)
async def index():  # 定义一个异步函数index，用于处理首页请求
    return FileResponse(str(WEB_DIR / "index.html"))  # 返回index.html文件作为响应，使用FileResponse类型，并将WEB_DIR与"index.html"拼接为完整路径并转换为字符串

#GET请求，获取机器人的状态
@app.get("/status")
async def get_status():
    return robot.get_status()
#GET请求，模拟传感器数据
@app.get("/sensor")
async def get_sensor():
    #这里可以写死模拟传感器数据，先包含距离和温度
    return {"distance": 100, "temperature": 25}

#POST请求，控制机器人运动
@app.post("/move")
async def move(request: MoveRequest):
    robot.move_status(request.direction, request.speed, request.duration_s)
    return {"message": "运动指令已接受", "status": robot.get_status()}

@app.post("/stop")
async def stop():
    robot.stop()
    return {"message": "机器人已停止", "status": robot.get_status()}

@app.post("/task")
async def task(request: TaskRequest):
    robot.start_task(request.name)
    return {"message": f"机器人已接受预设任务: {request.name}", "status": robot.get_status()}


