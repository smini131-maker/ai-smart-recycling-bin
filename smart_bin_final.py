from __future__ import annotations

import builtins
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")

from gpiozero import MotionSensor

import smart_bin_camera_ai_specialist as specialist_app
from smart_bin_hardware import SmartBinHardware


PROJECT_DIR = Path("/home/smini131/smart_bin")
CONFIG_PATH = PROJECT_DIR / "hardware_config.json"

base = specialist_app.base
_original_print_recognition_result = base.print_recognition_result

_hardware: SmartBinHardware | None = None
_pir_controller: "PirOneShotGreeting | None" = None

_camera_ready_event = threading.Event()
_system_ready_event = threading.Event()
_shutdown_event = threading.Event()

_state_lock = threading.Lock()
_current_state = "INITIALIZING"
_lock_started_at: float | None = None

# 카메라 로그의 LOCKED 문자열에 의존하지 않고,
# 분류 결과가 끝나는 순간부터 제거 안내 시간을 직접 측정한다.
_lock_watch_lock = threading.Lock()
_lock_watch_started_at: float | None = None
_lock_watch_generation = 0

STATE_PATTERN = re.compile(
    r"\b(INITIALIZING|WAITING|DETECTING|RECOGNIZING|"
    r"CONFIRMED|LOCKED|CLEARING)\b",
    re.IGNORECASE,
)


def load_config() -> dict[str, Any]:
    data = json.loads(
        CONFIG_PATH.read_text(encoding="utf-8")
    )

    if not isinstance(data, dict):
        raise TypeError(
            "hardware_config.json 형식이 올바르지 않습니다."
        )

    return data


def set_state(state: str) -> None:
    global _current_state
    global _lock_started_at

    normalized = state.upper()

    with _state_lock:
        _current_state = normalized

        if normalized == "LOCKED":
            if _lock_started_at is None:
                _lock_started_at = time.monotonic()

        elif normalized in {
            "INITIALIZING",
            "WAITING",
            "CLEARING",
        }:
            _lock_started_at = None

    if normalized == "WAITING":
        _camera_ready_event.set()

    if normalized in {
        "WAITING",
        "CLEARING",
        "INITIALIZING",
    }:
        clear_lock_watch()


def get_lock_started_at() -> float | None:
    with _state_lock:
        return _lock_started_at


def arm_lock_watch() -> tuple[int, float]:
    """
    분류 음성과 서보 동작이 끝난 직후 호출한다.
    카메라 로그에 LOCKED 문구가 없어도 제거 안내가 작동한다.
    """
    global _lock_watch_started_at
    global _lock_watch_generation

    with _lock_watch_lock:
        _lock_watch_generation += 1
        _lock_watch_started_at = time.monotonic()

        generation = _lock_watch_generation
        started_at = _lock_watch_started_at

    builtins.print(
        "[LOCK 감시] 분류 완료. "
        "물체가 계속 남아 있는지 확인합니다."
    )

    return generation, started_at


def clear_lock_watch() -> None:
    global _lock_watch_started_at

    with _lock_watch_lock:
        _lock_watch_started_at = None


def get_lock_watch() -> tuple[int, float | None]:
    with _lock_watch_lock:
        return (
            _lock_watch_generation,
            _lock_watch_started_at,
        )


def infer_state_from_message(message: str) -> None:
    match = STATE_PATTERN.search(message)

    if match:
        set_state(match.group(1))
        return

    lowered = message.lower()

    if any(
        token in message
        for token in (
            "다음 물체를 기다",
            "물체를 기다리는 중",
            "기준 배경 생성 완료",
            "배경 수집 완료",
        )
    ):
        set_state("WAITING")

    elif any(
        token in message
        for token in (
            "물체 진입 후보",
            "물체 진입 확인",
        )
    ):
        set_state("DETECTING")

    elif (
        "추론" in message
        or "분류 중" in message
        or "recognizing" in lowered
    ):
        set_state("RECOGNIZING")

    elif (
        "물체 제거" in message
        or "clearing" in lowered
    ):
        set_state("CLEARING")


def is_waiting_message(message: str) -> bool:
    upper = message.upper()

    return (
        "WAITING" in upper
        or "다음 물체를 기다" in message
        or "물체를 기다리는 중" in message
    )


def monitored_print(
    *args: object,
    **kwargs: Any,
) -> None:
    """
    카메라 상태는 내부적으로 감시하되,
    원본 WAITING 문구는 화면에 표시하지 않는다.

    준비 완료 표시는 PIR 안정화와 배경 수집이 모두 끝난 뒤
    이 파일에서 한 번만 명확하게 출력한다.
    """
    message = " ".join(
        str(value)
        for value in args
    )

    infer_state_from_message(message)

    if is_waiting_message(message):
        return

    builtins.print(*args, **kwargs)


# base와 specialist 어느 모듈에서 출력하더라도 상태를 감시한다.
base.print = monitored_print
specialist_app.print = monitored_print


def apply_detection_sensitivity() -> None:
    target_ratio = 0.07
    changed = 0

    for name, value in list(vars(base).items()):
        if isinstance(value, bool):
            continue

        if not isinstance(value, (int, float)):
            continue

        upper = name.upper()

        if "CONFIDENCE" in upper:
            continue

        if not any(
            token in upper
            for token in (
                "ENTER",
                "ENTRY",
                "TRIGGER",
                "DETECT",
            )
        ):
            continue

        if not any(
            token in upper
            for token in (
                "CHANGE",
                "RATIO",
                "THRESHOLD",
                "PERCENT",
            )
        ):
            continue

        old = float(value)

        if 0.08 <= old <= 0.30:
            setattr(base, name, target_ratio)
            builtins.print(
                f"[감지 민감도] {name}: "
                f"{old} → {target_ratio}"
            )
            changed += 1

        elif 8.0 <= old <= 30.0:
            setattr(base, name, 7.0)
            builtins.print(
                f"[감지 민감도] {name}: "
                f"{old} → 7.0"
            )
            changed += 1

    if changed == 0:
        builtins.print(
            "[감지 민감도 경고] "
            "자동 변경할 진입 임계값을 찾지 못했습니다."
        )



def collect_result_tokens(value: Any) -> list[str]:
    tokens: list[str] = []

    if isinstance(value, dict):
        for key, item in value.items():
            tokens.extend(
                collect_result_tokens(key)
            )
            tokens.extend(
                collect_result_tokens(item)
            )

    elif isinstance(value, (list, tuple, set)):
        for item in value:
            tokens.extend(
                collect_result_tokens(item)
            )

    elif value is not None:
        text = str(
            getattr(value, "name", value)
        ).strip().lower()

        if text:
            tokens.append(text)

    return tokens


def is_other_result(
    result: dict[str, Any],
) -> bool:
    """
    결과 딕셔너리 형식이 달라도 other/기타/거부 결과를 찾는다.
    """
    tokens = collect_result_tokens(result)

    exact_other = {
        "other",
        "기타",
        "rejected",
        "reject",
        "unsupported",
    }

    for token in tokens:
        normalized = token.replace("-", "_").strip()

        if normalized in exact_other:
            return True

        if normalized.endswith("_other"):
            return True

        if normalized.startswith("other_"):
            return True

    return False


def play_named_audio(name: str) -> None:
    if _hardware is None:
        raise RuntimeError(
            "하드웨어 컨트롤러가 초기화되지 않았습니다."
        )

    audio = getattr(_hardware, "audio", None)

    if (
        audio is not None
        and hasattr(audio, "play")
    ):
        audio.play(name)
        return

    method = getattr(
        _hardware,
        "play_audio",
        None,
    )

    if callable(method):
        method(name)
        return

    raise RuntimeError(
        "오디오 재생기를 찾지 못했습니다."
    )


class PirOneShotGreeting:
    """
    ready.wav는 프로그램 실행 후 단 한 번만 재생한다.

    재생 조건:
    1. PIR 안정화 완료
    2. 카메라 배경 수집 완료
    3. PIR이 LOW로 2초 연속 유지
    4. 이후 실제 움직임 감지

    한 번 재생한 뒤 PIR 안내 스레드는 종료되므로,
    같은 사용자가 물건을 내려놓거나 움직여도
    분리수거 도중 ready.wav가 다시 재생되지 않는다.
    """

    def __init__(
        self,
        hardware: SmartBinHardware,
        config: dict[str, Any],
    ) -> None:
        self.hardware = hardware
        self.enabled = bool(
            config.get("enabled", True)
        )
        self.gpio_pin = int(
            config.get("gpio_pin", 17)
        )
        self.warmup_sec = max(
            45.0,
            float(
                config.get(
                    "warmup_sec",
                    45.0,
                )
            ),
        )
        self.initial_low_sec = max(
            1.0,
            float(
                config.get(
                    "initial_low_sec",
                    2.0,
                )
            ),
        )

        self.sensor: MotionSensor | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            builtins.print(
                "[PIR] 설정에서 비활성화됨"
            )
            return

        self.sensor = MotionSensor(
            self.gpio_pin,
            queue_len=1,
            sample_rate=10,
            threshold=0.5,
        )

        self.thread = threading.Thread(
            target=self._run,
            name="pir-one-shot-greeting",
            daemon=True,
        )
        self.thread.start()

        builtins.print(
            f"[PIR] GPIO{self.gpio_pin} 감시 시작"
        )

    def wait_for_stable_low(
        self,
        stable_seconds: float,
    ) -> bool:
        assert self.sensor is not None

        low_started_at: float | None = None

        while not self.stop_event.is_set():
            now = time.monotonic()

            if self.sensor.motion_detected:
                low_started_at = None
            else:
                if low_started_at is None:
                    low_started_at = now

                if (
                    now - low_started_at
                    >= stable_seconds
                ):
                    return True

            time.sleep(0.05)

        return False

    def _run(self) -> None:
        assert self.sensor is not None

        builtins.print(
            f"[PIR] 센서 안정화 중 "
            f"({self.warmup_sec:.0f}초)"
        )

        if self.stop_event.wait(
            self.warmup_sec
        ):
            return

        builtins.print(
            "[PIR] 센서 안정화 완료"
        )
        builtins.print(
            "[카메라] 배경 수집 완료를 기다립니다."
        )

        while not self.stop_event.is_set():
            if _camera_ready_event.wait(
                timeout=0.25
            ):
                break

        if self.stop_event.is_set():
            return

        if not self.wait_for_stable_low(
            self.initial_low_sec
        ):
            return

        _system_ready_event.set()

        builtins.print("=" * 68)
        builtins.print(
            "[시스템 준비 완료] "
            "이제 사람이 접근하면 안내 음성이 한 번 재생됩니다."
        )
        builtins.print(
            "[인식 상태] 물체를 보여주기 전 대기 중"
        )
        builtins.print("=" * 68)

        while not self.stop_event.is_set():
            detected = self.sensor.wait_for_motion(
                timeout=0.5
            )

            if not detected:
                continue

            time.sleep(0.2)

            if not self.sensor.motion_detected:
                continue

            acquired = self.hardware.lock.acquire(
                blocking=False
            )

            if not acquired:
                # 분류 음성이나 서보가 이미 동작 중이라면
                # 안내를 생략하고 다시 기다린다.
                continue

            try:
                builtins.print(
                    "[PIR] 사람 접근 감지 "
                    "→ ready.wav 1회 재생"
                )
                self.hardware.play_ready()
                builtins.print(
                    "[PIR] 시작 안내 완료. "
                    "이번 실행에서는 다시 재생하지 않습니다."
                )

            finally:
                self.hardware.lock.release()

            # 핵심: 한 번 재생 후 스레드를 끝낸다.
            return

    def stop(self) -> None:
        self.stop_event.set()

        if self.sensor is not None:
            try:
                self.sensor.close()
            except Exception:
                pass

        if (
            self.thread is not None
            and self.thread.is_alive()
        ):
            self.thread.join(timeout=2.0)

        builtins.print("[PIR] 종료")


class LockReminderController:
    """
    결과 처리가 끝난 뒤 지정 시간 동안 물체가 제거되지 않으면
    remove_wait.wav를 한 번 재생한다.

    LOCKED 로그 출력 여부와 무관하게 작동한다.
    WAITING 또는 CLEARING으로 돌아오면 즉시 취소된다.
    """

    def __init__(
        self,
        hardware: SmartBinHardware,
        reminder_sec: float,
    ) -> None:
        self.hardware = hardware
        self.reminder_sec = max(
            1.0,
            float(reminder_sec),
        )
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="lock-reminder",
            daemon=True,
        )
        self.announced_generation: int | None = None

    def start(self) -> None:
        self.thread.start()
        builtins.print(
            "[LOCK 안내] "
            f"물체가 {self.reminder_sec:.1f}초 이상 남으면 안내"
        )

    def _run(self) -> None:
        while not self.stop_event.wait(0.2):
            generation, started_at = get_lock_watch()

            if started_at is None:
                continue

            if (
                self.announced_generation
                == generation
            ):
                continue

            elapsed = (
                time.monotonic()
                - started_at
            )

            if elapsed < self.reminder_sec:
                continue

            acquired = self.hardware.lock.acquire(
                blocking=False
            )

            if not acquired:
                continue

            try:
                current_generation, current_started = (
                    get_lock_watch()
                )

                if (
                    current_started is None
                    or current_generation != generation
                    or current_started != started_at
                ):
                    continue

                builtins.print(
                    "[LOCK 안내] "
                    "물체 제거 및 재투입 안내 재생"
                )
                play_named_audio("remove_wait")
                self.announced_generation = generation

            except Exception as error:
                builtins.print(
                    "[LOCK 안내 오류] "
                    f"{type(error).__name__}: {error}"
                )
                self.announced_generation = generation

            finally:
                self.hardware.lock.release()

    def stop(self) -> None:
        self.stop_event.set()

        if self.thread.is_alive():
            self.thread.join(timeout=2.0)


def print_recognition_result_with_hardware(
    result: dict[str, Any],
) -> None:
    _original_print_recognition_result(
        result
    )

    if _hardware is None:
        raise RuntimeError(
            "하드웨어 컨트롤러가 초기화되지 않았습니다."
        )

    if is_other_result(result):
        builtins.print(
            "[OTHER 안내] other 결과 확인 "
            "→ 전용 안내 음성 재생"
        )

        # other는 어떤 뚜껑도 열지 않는다.
        play_named_audio("other")

    else:
        _hardware.handle_result(result)

    # 분류 안내와 서보 동작이 모두 끝난 시점부터
    # 물체 제거 대기 시간을 직접 측정한다.
    arm_lock_watch()


base.print_recognition_result = (
    print_recognition_result_with_hardware
)


def main() -> int:
    global _hardware
    global _pir_controller

    apply_detection_sensitivity()

    hardware_disabled = (
        os.environ.get(
            "SMART_BIN_NO_HARDWARE",
            "0",
        )
        == "1"
    )

    if hardware_disabled:
        builtins.print(
            "[테스트 모드] 하드웨어 비활성화"
        )
        return int(base.main())

    config = load_config()
    production = config.get(
        "production",
        {},
    )

    builtins.print("=" * 76)
    builtins.print(
        "스마트 분리수거함 실전 통합 프로그램 V6"
    )
    builtins.print("=" * 76)
    builtins.print(
        "[안내] 시작 및 준비 중 ready.wav 재생 안 함"
    )
    builtins.print(
        "[안내] 준비 완료 뒤 첫 접근에서 한 번만 재생"
    )
    builtins.print(
        "[안내] 이후 분리수거 중에는 절대 반복하지 않음"
    )
    builtins.print(
        "[표시] 원본 WAITING 문구는 숨김"
    )
    builtins.print("=" * 76)

    _hardware = SmartBinHardware()

    _pir_controller = PirOneShotGreeting(
        _hardware,
        config.get("pir", {}),
    )
    _pir_controller.start()

    lock_controller = LockReminderController(
        _hardware,
        float(
            production.get(
                "lock_reminder_sec",
                8.0,
            )
        ),
    )
    lock_controller.start()

    try:
        return int(base.main())

    finally:
        _shutdown_event.set()

        lock_controller.stop()

        if _pir_controller is not None:
            _pir_controller.stop()

        if _hardware is not None:
            _hardware.cleanup()


if __name__ == "__main__":
    try:
        raise SystemExit(main())

    except KeyboardInterrupt:
        builtins.print(
            "\n[종료] 사용자가 Ctrl+C를 눌렀습니다."
        )
        raise SystemExit(130)
