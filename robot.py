#首先初步写出机器人的设备运行状态打印
#应该包括机器人的初始状态，查询状态，运行控制，停止
#然后定义出任务状态
class Robot:
    VALID_DRICTIONS = ['forward', 'backward', 'left', 'right']
    #定义预设任务为/task准备
    VALID_TASKS = ['forward', 'square']

    def __init__(self):
        #一开始机器人的各种状态:应该包括在线、运动、方向、速度
        #定义任务状态
        self.online = True
        self.moving = False
        self.direction = None
        self.speed = 0
        self.current_task = None
    #有了初始状态，如果变化，就要有接受状态的方法
    def get_status(self):
        return {
            'online': self.online,
            'moving': self.moving,
            'direction' : self.direction,
            'speed' : self.speed,
            'current_task': self.current_task
        }
    #有了初始状态，就要有改变状态的方法
    def move_status(self, direction, speed):
        #只需要规定方向和速度，这样肯定是正在运动，然后方向和速度要规定，合规才能是运动状态
        if direction not in self.VALID_DRICTIONS:
            raise ValueError("运动方向只能前进、后退、向左、向右")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool):
            raise ValueError("速度必须是数字")
        if not 0 < speed <= 100:
            raise ValueError("速度在0-100之间")
        self.online = True
        self.moving = True
        self.direction = direction
        self.speed = speed
        #设置了速度和方向，那么当前任务就应该停下来
        self.current_task = None
      

    #然后需要让机器人停止的方法
    def stop(self):
        self.moving = False
        self.direction = None
        self.speed = 0
        self.current_task = None
    #需要定义机器人的任务状态
    def start_task(self, name):
        if name not in self.VALID_TASKS:
            raise ValueError("任务名称无效")
        self.current_task = name
        self.moving = False
        self.direction = None
        self.speed = 0

        
        

        