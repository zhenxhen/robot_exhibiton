import sys
import os
import glob
sys.path.insert(0, os.path.abspath('.'))

import math

from lib.interface import Interface

def find_robot_port():
    ports = glob.glob('/dev/cu.usbserial-*') + glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    if not ports:
        raise RuntimeError("❌ usbserial 포트를 찾을 수 없습니다. 로봇 케이블을 확인하세요.")
    print(f"🔌 로봇 포트 자동 감지: {ports[0]}")
    return ports[0]

bot = Interface(find_robot_port())

print('Bot status:', 'connected' if bot.connected() else 'not connected')

params = bot.get_continous_trajectory_params()
print('Params:', params)

[start_x, start_y, start_z, start_r] = bot.get_pose()[0:4]

# 가속도와 속도 한계치를 높여 전체적인 속도 제한을 풉니다.
bot.set_continous_trajectory_real_time_params(50, 150, 10)
# 시작 위치
cx = start_x
cy = start_y
cz = start_z

# 원 그리기 세팅
radius = 70
steps = 40
import time

bot.stop_queue()
bot.clear_queue()

# 대각선 방향을 설정합니다.
angle_xy = math.pi / 2

# 시작점으로 천천히 이동 (대각선 원의 시작점, theta=0)
start_x_circle = cx + radius * math.cos(0) * math.cos(angle_xy)
start_y_circle = cy + radius * math.cos(0) * math.sin(angle_xy)
start_z_circle = cz + radius * math.sin(0)
bot.set_continous_trajectory_command(1, start_x_circle, start_y_circle, start_z_circle, start_r)
bot.start_queue()
time.sleep(1)

print('Drawing continuous diagonal circle...')
cycle_count = 0
while True:
    cycle_count += 1
    print(f'Circle count: {cycle_count}')
    
    last_index = 0
    for i in range(1, steps + 1):
        # theta에 마이너스를 붙여서 회전 방향을 반대로(반시계 방향) 바꿉니다.
        theta = -2 * math.pi * i / steps
        
        # X, Y가 동시에 변하면서 대각선 방향을 만들고, Z가 위아래 높이를 만듭니다.
        x = cx + radius * math.cos(theta) * math.cos(angle_xy)
        y = cy + radius * math.cos(theta) * math.sin(angle_xy)
        z = cz + radius * math.sin(theta)
        
        # 5번째 파라미터는 속도(velocity)입니다. 그리는 속도를 높이기 위해 150으로 설정합니다.
        res = bot.set_continous_trajectory_command(1, x, y, z, 150)
        if res:
            last_index = res[0] if isinstance(res, (list, tuple)) else res

    while True:
        curr = bot.get_current_queue_index()
        if curr:
            curr_val = curr[0] if isinstance(curr, (list, tuple)) else curr
            if curr_val >= last_index:
                break
        time.sleep(0.1)
        
    print('Cycle complete. Resting for 1 seconds...')
    time.sleep(0)
