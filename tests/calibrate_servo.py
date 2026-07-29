from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/home/smini131/smart_bin")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adafruit_servokit import ServoKit


CONFIG_PATH = PROJECT_ROOT / "hardware_config.json"
VALID_LABELS = (
    "can",
    "clear_pet",
    "plastic",
    "paper",
)


def save_config(
    config: dict,
) -> None:
    CONFIG_PATH.write_text(
        json.dumps(
            config,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "사용법: python tests/calibrate_servo.py "
            "can|clear_pet|plastic|paper"
        )
        return 1

    label = sys.argv[1].strip()

    if label not in VALID_LABELS:
        print(f"[오류] 지원하지 않는 분류: {label}")
        return 1

    config = json.loads(
        CONFIG_PATH.read_text(
            encoding="utf-8"
        )
    )

    servo_config = config["servo"]
    item = servo_config["channels"][label]

    channel = int(item["channel"])
    closed_angle = float(item["closed_angle"])
    open_angle = float(item["open_angle"])

    kit = ServoKit(
        channels=16,
        address=int(
            servo_config.get(
                "i2c_address",
                "0x40",
            ),
            0,
        ),
        frequency=int(
            servo_config.get(
                "frequency_hz",
                50,
            )
        ),
    )

    servo = kit.servo[channel]

    servo.set_pulse_width_range(
        int(
            servo_config.get(
                "min_pulse_us",
                600,
            )
        ),
        int(
            servo_config.get(
                "max_pulse_us",
                2400,
            )
        ),
    )

    current_angle = closed_angle

    print("=" * 60)
    print("서보 각도 보정")
    print("=" * 60)
    print(f"분류       : {label}")
    print(f"PCA9685 채널: {channel}")
    print(f"현재 닫힘값 : {closed_angle:.1f}도")
    print(f"현재 열림값 : {open_angle:.1f}도")
    print()
    print("명령")
    print("  숫자       : 해당 각도로 이동, 예: 95")
    print("  +          : 현재 각도에서 1도 증가")
    print("  -          : 현재 각도에서 1도 감소")
    print("  +5         : 현재 각도에서 5도 증가")
    print("  -5         : 현재 각도에서 5도 감소")
    print("  c          : 현재 각도를 닫힘값으로 저장")
    print("  o          : 현재 각도를 열림값으로 저장")
    print("  show       : 현재 저장값 확인")
    print("  q          : PWM 해제 후 종료")
    print()
    print("처음에는 5도, 근접하면 1도씩 조절하세요.")
    print("서보가 끝에서 버티거나 윙윙거리면 즉시 반대로 이동하세요.")
    print()

    servo.angle = current_angle
    time.sleep(0.7)

    try:
        while True:
            command = input(
                f"[현재 {current_angle:.1f}도] 명령: "
            ).strip().lower()

            if command == "q":
                break

            if command == "show":
                print(
                    f"저장된 닫힘={closed_angle:.1f}도, "
                    f"열림={open_angle:.1f}도"
                )
                continue

            if command == "c":
                closed_angle = current_angle
                item["closed_angle"] = round(
                    closed_angle,
                    1,
                )
                save_config(config)

                print(
                    f"[저장 완료] {label} 닫힘 각도 "
                    f"{closed_angle:.1f}도"
                )
                continue

            if command == "o":
                open_angle = current_angle
                item["open_angle"] = round(
                    open_angle,
                    1,
                )
                save_config(config)

                print(
                    f"[저장 완료] {label} 열림 각도 "
                    f"{open_angle:.1f}도"
                )
                continue

            try:
                if command.startswith(("+", "-")):
                    target_angle = (
                        current_angle
                        + float(command)
                    )
                else:
                    target_angle = float(command)

            except ValueError:
                print("[오류] 올바른 명령이 아닙니다.")
                continue

            if not 10.0 <= target_angle <= 170.0:
                print(
                    "[차단] 안전을 위해 "
                    "10도~170도만 허용합니다."
                )
                continue

            servo.angle = target_angle
            current_angle = target_angle

            time.sleep(0.3)

    finally:
        servo.angle = None
        print("[완료] PWM 해제")

    print()
    print(
        f"최종 저장값: 닫힘 {closed_angle:.1f}도, "
        f"열림 {open_angle:.1f}도"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
