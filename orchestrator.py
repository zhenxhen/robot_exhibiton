import sys
import os
import time
import math
import subprocess
from datetime import datetime
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types
from escpos.printer import Usb

# 로봇 라이브러리 경로 추가 (lib 폴더 내 interface 등을 사용하기 위함)
sys.path.insert(0, os.path.abspath('.'))
from lib.interface import Interface

load_dotenv()

# ==========================================
# 타이밍 및 제어 변수 설정
# ==========================================
ROBOT_MOVE_DELAY = 0.0              # (옵션) 시작점으로 이동 후 잠시 대기
ADB_CAPTURE_DELAY = 0.0             # 로봇 팔 움직임 정지 후 ADB 캡처까지 대기 시간 (초)
PRINT_START_DELAY = 4.0             # 로봇 팔 재가동 후 영수증 출력까지 대기 시간 (초)

# 원 그리기 설정 (기존 설정 활용)
RADIUS = 70
STEPS = 40
VELOCITY = 150

# ==========================================
# 환경 설정 및 프롬프트
# ==========================================
CAPTURE_DIR = "./captures"
os.makedirs(CAPTURE_DIR, exist_ok=True)

ANALYSIS_PROMPT = """
Please analyze this short-form video screenshot.
Without any other introductory text, you must output the response in the following format:

[Title]
A 2-3 words philosophical and romantic summary of the video content.

[Author]
Account handle (if not visible, "Unidentified").

[Category]
Choose one: (Food / Travel / Comedy / Beauty / Sports / Gaming / Education / Movie / Anime / Animals / Fashion / Nature / Technology / History / Other).

[Content]
Write a One-sentence narrative about the video's content, imitating the literary style of Alain de Botton.

[Review]
A short one-sentence critique written as if by a world-renowned critic—philosophical, profound, and evocative.

[Engagement]
Like and Comment counts (if visible).
"""

# ── 1. 초기화 함수들 ─────────────────────────────
def setup_environment():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("❌ GEMINI_API_KEY environment variable not set.")
    client = genai.Client(api_key=api_key)
    model = client

    # ADB 확인
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    lines = [l for l in result.stdout.strip().splitlines() if "device" in l and "List" not in l]
    if not lines:
        raise RuntimeError("❌ ADB 장치 없음! 케이블 및 디버깅을 확인하세요.")
    print(f"✅ ADB 연결됨: {lines[0].split()[0]}")

    # 영수증 프린터 확인
    try:
        printer = Usb(0x0fe6, 0x811e, out_ep=3)
        print("🖨️  영수증 프린터(CSN-A4L) 연결 완료!")
    except Exception as e:
        print(f"⚠️ 영수증 프린터 연결 실패: {e}")
        printer = None

    return model, printer

def find_robot_port():
    """usbserial 포트를 자동으로 탐색 (macOS 및 Linux/라즈베리파이 지원)"""
    import glob
    ports = glob.glob('/dev/cu.usbserial-*') + glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    if not ports:
        raise RuntimeError("❌ usbserial 포트를 찾을 수 없습니다. 로봇 케이블을 확인하세요.")
    if len(ports) > 1:
        print(f"⚠️  여러 포트 발견: {ports} → 첫 번째 사용: {ports[0]}")
    print(f"🔌 로봇 포트 자동 감지: {ports[0]}")
    return ports[0]

def setup_robot():
    port = find_robot_port()
    bot = Interface(port)
    if not bot.connected():
        print("❌ 로봇이 연결되지 않았습니다.")
        sys.exit(1)
    print('🤖 로봇 연결됨')
    bot.set_continous_trajectory_real_time_params(50, 150, 10)
    bot.stop_queue()
    bot.clear_queue()
    return bot

# ── 2. 작업 함수들 ────────────────────────────────
def enqueue_trajectory(bot, start_x, start_y, start_z, start_r):
    angle_xy = math.pi / 2
    
    # 궤적 시작점으로 한 번 이동 (이동이 튀는 것을 방지하기 위함)
    start_x_circle = start_x + RADIUS * math.cos(0) * math.cos(angle_xy)
    start_y_circle = start_y + RADIUS * math.cos(0) * math.sin(angle_xy)
    start_z_circle = start_z + RADIUS * math.sin(0)
    bot.set_continous_trajectory_command(1, start_x_circle, start_y_circle, start_z_circle, start_r)
    
    last_index = 0
    # 원 그리기 큐 생성
    for i in range(1, STEPS + 1):
        theta = -2 * math.pi * i / STEPS
        x = start_x + RADIUS * math.cos(theta) * math.cos(angle_xy)
        y = start_y + RADIUS * math.cos(theta) * math.sin(angle_xy)
        z = start_z + RADIUS * math.sin(theta)
        
        res = bot.set_continous_trajectory_command(1, x, y, z, VELOCITY)
        if res is not None:
            last_index = res[0] if isinstance(res, (list, tuple)) else res
            
    return last_index

def wait_for_robot(bot, target_index):
    # 로봇의 큐 인덱스가 우리가 마지막으로 입력한 target_index보다 커질 때까지 대기
    while True:
        curr = bot.get_current_queue_index()
        if curr is not None:
            curr_val = curr[0] if isinstance(curr, (list, tuple)) else curr
            if curr_val >= target_index:
                break
        time.sleep(0.1)

def capture_screen(index: int) -> str:
    ts   = datetime.now().strftime("%H%M%S")
    path = os.path.join(CAPTURE_DIR, f"frame_{index:04d}_{ts}.png")
    subprocess.run(["adb", "shell", "screencap", "-p", "/sdcard/cap.png"], check=True, timeout=5)
    subprocess.run(["adb", "pull", "/sdcard/cap.png", path], check=True, timeout=5)
    return path

def analyze(model, image_path: str) -> str:
    img = Image.open(image_path)
    # 전송 전 리사이즈 (최대 720px, 비율 유지) → 업로드 용량 대폭 감소
    img.thumbnail((720, 1280), Image.LANCZOS)
    response = model.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=[ANALYSIS_PROMPT, img],
        config=types.GenerateContentConfig(max_output_tokens=600, temperature=0.2)
    )
    return response.text

def print_to_receipt(printer, index, path, analysis):
    if not printer:
        return
    try:
        printer.text("=" * 32 + "\n\n")
        printer.text(analysis.strip() + "\n\n")
        printer.text("=" * 32 + "\n\n")
        printer.cut()
    except Exception as e:
        print(f"⚠️ 영수증 출력 실패: {e}")

# ── 3. 메인 오케스트레이션 루프 ─────────────────────
def main():
    print("\n🚀 Orchestrator 시작")
    bot = setup_robot()

    current_pose = bot.get_pose()[0:4]
    cx, cy, cz, cr = current_pose
    print(f"📍 현재 로봇 위치 기준점: ({cx:.2f}, {cy:.2f}, {cz:.2f})")

    for cycle_count in range(1, 81):
        try:
            print(f"\n" + "━" * 60)
            print(f"🔄 [Cycle {cycle_count}/80] 시작")
            print("━" * 60)

            bot.stop_queue()
            bot.clear_queue()
            last_idx = enqueue_trajectory(bot, cx, cy, cz, cr)

            print("  🤖 로봇 움직임 시작")
            bot.start_queue()

            wait_for_robot(bot, last_idx)
            print("  🛑 로봇 움직임 정지 완료")

            print("  ⏳ 5초 대기 중...")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\n🛑 사용자 중단 - 오케스트레이터를 종료합니다.")
            break
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")
            time.sleep(2)

    print("\n✅ 80회 완료")

if __name__ == "__main__":
    main()
