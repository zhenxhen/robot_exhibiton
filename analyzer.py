import subprocess
import time
import os
import google.generativeai as genai
from PIL import Image
from datetime import datetime
from dotenv import load_dotenv
from escpos.printer import Usb

load_dotenv()

# ── 설정 ────────────────────────────────────────────────
CAPTURE_DIR   = "./captures"
WATCH_SECONDS = 10.0  # 캡처 간격 (초)  # 프로그램은 무한히 캡처합니다.

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
# ────────────────────────────────────────────────────────

os.makedirs(CAPTURE_DIR, exist_ok=True)

# Gemini 설정 (GEMINI_API_KEY 환경변수 자동 로드)
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("❌ GEMINI_API_KEY environment variable not set. Please set it before running the script.")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-flash-lite-latest")


# ── ADB 연결 확인 ────────────────────────────────────────
def check_adb():
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    lines = [l for l in result.stdout.strip().splitlines()
             if "device" in l and "List" not in l]
    if not lines:
        raise RuntimeError("❌ ADB 장치 없음!\n"
                           "   → USB 케이블 연결 확인\n"
                           "   → USB 디버깅 ON 확인\n"
                           "   → 폰 화면 팝업 '항상 허용' 확인")
    print(f"✅ ADB 연결됨: {lines[0].split()[0]}")


# ── 화면 캡처 ────────────────────────────────────────────
def capture_screen(index: int) -> str:
    ts   = datetime.now().strftime("%H%M%S")
    path = os.path.join(CAPTURE_DIR, f"frame_{index:04d}_{ts}.png")

    subprocess.run(
        ["adb", "shell", "screencap", "-p", "/sdcard/cap.png"],
        check=True, timeout=5
    )
    subprocess.run(
        ["adb", "pull", "/sdcard/cap.png", path],
        check=True, timeout=5
    )
    return path


# ── Gemini 3.1 Flash Vision 분석 ─────────────────────────
def analyze(image_path: str) -> str:
    img = Image.open(image_path)
    # 전송 전 리사이즈 (최대 720px, 비율 유지) → 업로드 용량 대폭 감소
    img.thumbnail((720, 1280), Image.LANCZOS)

    response = model.generate_content(
        [ANALYSIS_PROMPT, img],
        generation_config=genai.GenerationConfig(
            max_output_tokens=600,
            temperature=0.2,
        )
    )
    return response.text


# ── 터미널 출력 ──────────────────────────────────────────
def print_result(index: int, total: int, path: str, analysis: str):
    now = datetime.now().strftime("%H:%M:%S")
    print("\n" + "━" * 60)
    print(f"  📱 [{index+1:03d}/{total}]  {now}  |  {os.path.basename(path)}")
    print("━" * 60)
    for line in analysis.strip().splitlines():
        print(f"  {line}")
    print("━" * 60)

# ── 영수증 프린터 출력 ───────────────────────────────────
def get_printer():
    try:
        # CSN-A4L / Gprinter (Vendor: 0x0fe6, Product: 0x811e)
        return Usb(0x0fe6, 0x811e, out_ep=3)
    except Exception as e:
        print(f"⚠️ 영수증 프린터 연결 실패: {e}")
        return None

def print_to_receipt(printer, index, path, analysis):
    if not printer:
        return
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        printer.text("=" * 32 + "\n\n")
        
        # 분석 내용 출력
        # python-escpos는 기본적으로 내부 magicencode를 사용하여 프린터에 맞게 인코딩 시도
        printer.text(analysis.strip() + "\n\n")
        
        printer.text("=" * 32 + "\n\n")
        # 출력 후 용지 절단
        printer.cut()
    except Exception as e:
        print(f"⚠️ 영수증 출력 실패: {e}")



# ── 메인 ─────────────────────────────────────────────────
def main():
    print("\n🚀 ShortForm Analyzer 시작 (Gemini 3.1 Flash)")
    print(f"   📁 저장 경로 : {os.path.abspath(CAPTURE_DIR)}")
    print(f"   ⏱  캡처 간격 : {WATCH_SECONDS}초")
    print("   ▶️ 무한 캡처 모드 (Ctrl+C 로 종료)\n")

    check_adb()

    # 프린터 초기화
    printer = get_printer()
    if printer:
        print("🖨️  영수증 프린터(CSN-A4L) 연결 완료!")

    i = 0
    while True:
        try:
            # 1. 캡처 대기
            print(f"\n⏳ [{i+1}] 캡처 대기 중 ({WATCH_SECONDS}초)...", end="", flush=True)
            time.sleep(WATCH_SECONDS)

            # 2. 캡처
            path = capture_screen(i)
            print("  📸 캡처 완료")

            # 3. 분석
            print("  🔍 Gemini 분석 중...", end="", flush=True)
            result = analyze(path)

            # 4. 터미널 출력 및 영수증 인쇄
            print_result(i, 0, path, result)
            print("  🖨️  영수증 출력 중...", end="", flush=True)
            print_to_receipt(printer, i, path, result)
            print(" 완료!")

            i += 1
        except KeyboardInterrupt:
            print("\n🛑 사용자 중단 - 종료합니다.")
            break
        except subprocess.TimeoutExpired:
            print(f"\n⚠️  [{i+1}] ADB 타임아웃 - 스킵")
            continue
        except Exception as e:
            print(f"\n❌ [{i+1}] 오류: {e}")
            continue

    print("\n🎉 캡처를 중단했습니다.")
    print(f"   캡처 파일 위치: {os.path.abspath(CAPTURE_DIR)}\n")


if __name__ == "__main__":
    main()