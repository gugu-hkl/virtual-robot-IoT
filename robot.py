#首先初步写出机器人的设备运行状态打印
#应该包括机器人的初始状态，查询状态，运行控制，停止
class Robot:
    def __init__(self):
        #一开始机器人的各种状态:应该包括在线、运动、方向、速度
        self.online = False
        self.moving = False
        self.direction = None
        self.speed = 0
    #有了初始状态，如果变化，就要有接受状态的方法
    def get_status(self):
        return {
            'online': self.online,
            'moving': self.moving,
            'direction' : self.direction,
            'speed' : self.speed
        }
    #有了初始状态，就要有改变状态的方法
    def move_status(self, direction, speed):
        #只需要规定方向和速度，这样肯定是正在运动，然后方向和速度要规定，合规才能是运动状态
        try:
            if direction in ['forward', 'backward', 'left', 'right']:
                self.direction = direction
            else:
                raise ValueError("运动方向只能前进、后退、向左、向右")
            if speed >0 and speed <= 100:
                self.speed = speed
            else:
                raise ValueError("速度在0-100之间")
            self.online = True
            self.moving = True
        except ValueError as e:
            print(e)
            self.moving = False
    #然后需要让机器人停止的方法
    def stop(self):
        self.moving = False
        self.direction = None
        self.speed = 0

        
        

        