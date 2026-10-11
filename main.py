
from robot import Robot
from fastapi import FastAPI

app = FastAPI(title = "虚拟机器人设备服务")
robot = Robot()
#GET请求，获取机器人的状态
@app.get("/status")
async def get_status():
    return robot.get_status()
#GET请求，模拟传感器数据
@app.get("/sensor")
async def get_sensor():
    #这里可以先写死模拟传感器数据，先包含距离和温度
    return {"distance": 100, "temperature": 25}



