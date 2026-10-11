
from robot import Robot
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Literal

app = FastAPI(title = "虚拟机器人设备服务")
robot = Robot()

class MoveRequest(BaseModel):
    direction: Literal['forward', 'backward', 'left', 'right']
    speed: int = Field(gt=0, le=100)

class TaskRequest(BaseModel):
    name: Literal['forward', 'square']

#GET请求，获取机器人的状态
@app.get("/status")
async def get_status():
    return robot.get_status()
#GET请求，模拟传感器数据
@app.get("/sensor")
async def get_sensor():
    #这里可以先写死模拟传感器数据，先包含距离和温度
    return {"distance": 100, "temperature": 25}

#POST请求，控制机器人运动
@app.post("/move")
async def move(request: MoveRequest):
    robot.move_status(request.direction, request.speed)
    return {"message": "机器人正在运动,运动指令已接受", "status": robot.get_status()}

@app.post("/stop")
async def stop():
    robot.stop()
    return {"message": "机器人已停止", "status": robot.get_status()}

@app.post("/task")
async def task(request: TaskRequest):
    robot.start_task(request.name)
    return {"message": f"机器人已接受预设任务: {request.name}", "status": robot.get_status()}


