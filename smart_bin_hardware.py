from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "hardware_config.json"
AUDIO_DIR = PROJECT_DIR / "audio"

RECYCLABLE_LABELS = (
    "can",
    "clear_pet",
    "plastic",
    "paper",
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"설정 파일이 없습니다: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise TypeError("하드웨어 설정의 최상위 값은 객체여야 합니다.")

    return data


def _parse_i2c_address(value: Any) -> int:
    if isinstance(value, int):
        address = value
    elif isinstance(value, str):
        address = int(value, 0)
    else:
        raise TypeError("I2C 주소는 정수 또는 문자열이어야 합니다.")

    if not 0x03 <= address <= 0x77:
        raise ValueError(f"잘못된 I2C 주소입니다: {address:#x}")

    return address


class AudioController:
    """WAV files are played synchronously with ALSA aplay."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        audio_dir: Path = AUDIO_DIR,
    ) -> None:
        self.config = config
        self.audio_dir = Path(audio_dir)
        self.enabled = bool(config.get("enabled", True))
        self.player = str(config.get("player", "aplay"))
        self.device_setting = str(
            config.get("device", "auto_usb")
        )
        self.files = dict(config.get("files", {}))
        self.device: str | None = None

        if not self.enabled:
            print("[오디오] 설정에서 비활성화됨")
            return

        if shutil.which(self.player) is None:
            raise RuntimeError(
                f"오디오 재생 프로그램이 없습니다: {self.player}\n"
                "sudo apt install -y alsa-utils"
            )

        self.device = self._resolve_device()

        print(
            "[오디오] 출력 장치: "
            f"{self.device if self.device else 'ALSA default'}"
        )

    @staticmethod
    def list_cards() -> str:
        command = ["aplay", "-l"]

        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        output = (completed.stdout + completed.stderr).strip()

        if completed.returncode != 0:
            raise RuntimeError(
                "ALSA 재생 장치 목록을 읽지 못했습니다.\n"
                + output
            )

        return output

    @staticmethod
    def _find_usb_device(card_listing: str) -> str | None:
        pattern = re.compile(
            r"card\s+(\d+):.*?,\s+device\s+(\d+):",
            re.IGNORECASE,
        )

        matches: list[tuple[str, str, str]] = []

        for line in card_listing.splitlines():
            match = pattern.search(line)

            if match:
                matches.append(
                    (
                        match.group(1),
                        match.group(2),
                        line,
                    )
                )

        for card, device, line in matches:
            lowered = line.lower()

            if (
                "usb" in lowered
                or "device" in lowered
                or "headset" in lowered
            ):
                return f"plughw:{card},{device}"

        if matches:
            card, device, _ = matches[0]
            return f"plughw:{card},{device}"

        return None

    def _resolve_device(self) -> str | None:
        if self.device_setting in ("", "default"):
            return None

        if self.device_setting == "auto_usb":
            listing = self.list_cards()
            selected = self._find_usb_device(listing)

            if selected is None:
                raise RuntimeError(
                    "사용 가능한 ALSA 재생 장치를 찾지 못했습니다.\n"
                    + listing
                )

            return selected

        return self.device_setting

    def play(
        self,
        key: str,
        *,
        required: bool = True,
    ) -> bool:
        if not self.enabled:
            return False

        filename = self.files.get(key)

        if not filename:
            if required:
                raise KeyError(
                    f"오디오 파일 설정이 없습니다: {key}"
                )
            return False

        path = self.audio_dir / str(filename)

        if not path.is_file():
            if required:
                raise FileNotFoundError(
                    f"오디오 파일이 없습니다: {path}"
                )
            return False

        command = [
            self.player,
            "-q",
        ]

        if self.device:
            command.extend(
                [
                    "-D",
                    self.device,
                ]
            )

        command.append(str(path))

        print(f"[오디오] 재생: {key} ({path.name})")

        completed = subprocess.run(
            command,
            check=False,
        )

        if completed.returncode != 0:
            if required:
                raise RuntimeError(
                    f"오디오 재생 실패: {key}, "
                    f"종료 코드 {completed.returncode}"
                )
            return False

        return True


class ServoController:
    """PCA9685 and MG90S lid controller."""

    def __init__(
        self,
        config: dict[str, Any],
    ) -> None:
        self.config = config
        self.enabled = bool(config.get("enabled", True))
        self.kit: Any | None = None
        self.current_angles: dict[str, float] = {}

        if not self.enabled:
            print("[서보] 설정에서 비활성화됨")
            return

        try:
            from adafruit_servokit import ServoKit
        except ImportError as error:
            raise RuntimeError(
                "adafruit_servokit이 설치되지 않았습니다.\n"
                "source .venv/bin/activate\n"
                "python -m pip install "
                "adafruit-circuitpython-servokit"
            ) from error

        address = _parse_i2c_address(
            config.get("i2c_address", "0x40")
        )
        frequency = int(config.get("frequency_hz", 50))

        self.kit = ServoKit(
            channels=16,
            address=address,
            frequency=frequency,
        )

        self.min_pulse_us = int(
            config.get("min_pulse_us", 600)
        )
        self.max_pulse_us = int(
            config.get("max_pulse_us", 2400)
        )
        self.step_degrees = max(
            1,
            int(config.get("step_degrees", 1)),
        )
        self.step_delay_sec = max(
            0.0,
            float(config.get("step_delay_sec", 0.03)),
        )
        self.open_hold_sec = max(
            0.0,
            float(config.get("open_hold_sec", 4.0)),
        )
        self.detach_after_close = bool(
            config.get("detach_after_close", True)
        )
        self.assume_closed_at_start = bool(
            config.get("assume_closed_at_start", True)
        )
        self.channels = dict(config.get("channels", {}))

        self._validate_channels()
        self._configure_pulse_ranges()

        if self.assume_closed_at_start:
            for label, item in self.channels.items():
                self.current_angles[label] = float(
                    item["closed_angle"]
                )

        print(
            "[서보] PCA9685 초기화 완료 "
            f"| address={address:#04x} "
            f"| frequency={frequency}Hz"
        )

    def _validate_channels(self) -> None:
        missing = [
            label
            for label in RECYCLABLE_LABELS
            if label not in self.channels
        ]

        if missing:
            raise ValueError(
                "서보 채널 설정 누락: "
                + ", ".join(missing)
            )

        used_channels: set[int] = set()

        for label in RECYCLABLE_LABELS:
            item = self.channels[label]
            channel = int(item["channel"])
            closed_angle = float(item["closed_angle"])
            open_angle = float(item["open_angle"])

            if not 0 <= channel <= 15:
                raise ValueError(
                    f"{label} 채널 범위 오류: {channel}"
                )

            if channel in used_channels:
                raise ValueError(
                    f"중복 PCA9685 채널: {channel}"
                )

            used_channels.add(channel)

            for name, angle in (
                ("closed_angle", closed_angle),
                ("open_angle", open_angle),
            ):
                if not 0.0 <= angle <= 180.0:
                    raise ValueError(
                        f"{label} {name} 범위 오류: {angle}"
                    )

            if closed_angle == open_angle:
                raise ValueError(
                    f"{label} 열림·닫힘 각도가 같습니다."
                )

    def _configure_pulse_ranges(self) -> None:
        assert self.kit is not None

        for label in RECYCLABLE_LABELS:
            channel = int(
                self.channels[label]["channel"]
            )
            servo = self.kit.servo[channel]
            servo.set_pulse_width_range(
                self.min_pulse_us,
                self.max_pulse_us,
            )

    def _get_servo(self, label: str) -> Any:
        if not self.enabled or self.kit is None:
            raise RuntimeError("서보 컨트롤러가 비활성화되었습니다.")

        if label not in self.channels:
            raise KeyError(f"지원하지 않는 서보 라벨: {label}")

        channel = int(self.channels[label]["channel"])
        return self.kit.servo[channel]

    def move_slowly(
        self,
        label: str,
        target_angle: float,
        *,
        start_angle: float | None = None,
    ) -> None:
        servo = self._get_servo(label)

        if start_angle is None:
            start_angle = self.current_angles.get(label)

        if start_angle is None:
            start_angle = float(
                self.channels[label]["closed_angle"]
            )
            servo.angle = start_angle
            time.sleep(0.5)

        start = float(start_angle)
        target = float(target_angle)
        difference = target - start

        if abs(difference) < 0.01:
            servo.angle = target
            self.current_angles[label] = target
            return

        direction = 1.0 if difference > 0.0 else -1.0
        angle = start

        while (
            angle < target
            if direction > 0
            else angle > target
        ):
            servo.angle = angle
            self.current_angles[label] = angle
            time.sleep(self.step_delay_sec)
            angle += direction * self.step_degrees

        servo.angle = target
        self.current_angles[label] = target

    def close_lid(self, label: str) -> None:
        closed_angle = float(
            self.channels[label]["closed_angle"]
        )

        print(
            f"[서보] {label} 닫기 "
            f"| angle={closed_angle:.1f}"
        )

        self.move_slowly(
            label,
            closed_angle,
        )

        if self.detach_after_close:
            self._get_servo(label).angle = None

    def open_lid(self, label: str) -> None:
        open_angle = float(
            self.channels[label]["open_angle"]
        )

        print(
            f"[서보] {label} 열기 "
            f"| angle={open_angle:.1f}"
        )

        self.move_slowly(
            label,
            open_angle,
        )

    def cycle_lid(self, label: str) -> None:
        if label not in RECYCLABLE_LABELS:
            raise KeyError(
                f"뚜껑이 없는 분류 라벨입니다: {label}"
            )

        self.open_lid(label)

        print(
            f"[서보] {self.open_hold_sec:.1f}초 동안 열림 유지"
        )
        time.sleep(self.open_hold_sec)

        try:
            self.close_lid(label)
        except Exception:
            print(
                "[서보 오류] 닫기 실패. "
                "전원을 끄고 기구물을 확인하세요."
            )
            raise

    def release_all(self) -> None:
        if not self.enabled or self.kit is None:
            return

        for label in RECYCLABLE_LABELS:
            try:
                self._get_servo(label).angle = None
            except Exception:
                pass


class SmartBinHardware:
    """Audio and lid action for one final recognition result."""

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.config_path = Path(config_path)
        self.config = _load_json(self.config_path)

        self.behavior = dict(
            self.config.get("behavior", {})
        )

        self.audio = AudioController(
            dict(self.config.get("audio", {}))
        )
        self.servo = ServoController(
            dict(self.config.get("servo", {}))
        )
        self.lock = threading.Lock()

    def play_ready(self) -> None:
        try:
            self.audio.play("ready")
        except Exception as error:
            if bool(
                self.behavior.get(
                    "continue_if_audio_fails",
                    True,
                )
            ):
                print(f"[오디오 경고] {error}")
            else:
                raise

    def _play_result_audio(
        self,
        key: str,
    ) -> None:
        try:
            self.audio.play(key)
        except Exception as error:
            if bool(
                self.behavior.get(
                    "continue_if_audio_fails",
                    True,
                )
            ):
                print(f"[오디오 경고] {error}")
            else:
                raise

    def handle_result(
        self,
        result: dict[str, Any],
    ) -> None:
        with self.lock:
            status = str(
                result.get("status", "")
            ).strip()
            label = str(
                result.get("label", "")
            ).strip()

            if status == "timeout":
                self._play_result_audio("timeout")
                return

            if status != "confirmed":
                self._play_result_audio("uncertain")
                return

            if label == "other":
                self._play_result_audio("other")
                return

            if label == "background":
                self._play_result_audio("background")
                return

            if label not in RECYCLABLE_LABELS:
                self._play_result_audio("uncertain")
                return

            audio_first = bool(
                self.behavior.get(
                    "play_audio_before_opening",
                    True,
                )
            )

            if audio_first:
                self._play_result_audio(label)

            try:
                self.servo.cycle_lid(label)
            except Exception as error:
                if bool(
                    self.behavior.get(
                        "continue_if_servo_fails",
                        False,
                    )
                ):
                    print(f"[서보 경고] {error}")
                else:
                    raise

            if not audio_first:
                self._play_result_audio(label)

    def cleanup(self) -> None:
        self.servo.release_all()
