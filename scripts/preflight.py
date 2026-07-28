from __future__ import annotations

import argparse
import compileall
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SOURCE = (
    "smart_bin_final.py",
    "smart_bin_hardware.py",
    "smart_bin_camera_ai.py",
    "smart_bin_camera_ai_specialist.py",
    "pet_plastic_specialist_runtime.py",
    "hardware_config.json",
    "model/labels.txt",
    "model/model_metadata.json",
    "model/pet_plastic_labels.txt",
    "model/pet_plastic_metadata.json",
)

RUNTIME_ASSETS = (
    "model/garbage_classifier.tflite",
    "model/pet_plastic_classifier.tflite",
    "audio/ready.wav",
    "audio/can.wav",
    "audio/clear_pet.wav",
    "audio/plastic.wav",
    "audio/paper.wav",
    "audio/other.wav",
    "audio/remove_wait.wav",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--print-hashes", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_SOURCE:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"필수 소스 없음: {relative}")
        elif path.stat().st_size == 0:
            errors.append(f"빈 파일: {relative}")

    for relative in RUNTIME_ASSETS:
        path = ROOT / relative
        if not path.is_file():
            message = f"실행 자산 없음: {relative}"
            if args.source_only:
                warnings.append(message)
            else:
                errors.append(message)

    try:
        config = json.loads(
            (ROOT / "hardware_config.json").read_text(encoding="utf-8")
        )
        channels = config["servo"]["channels"]
        expected = {"can": 0, "clear_pet": 4, "plastic": 11, "paper": 15}
        actual = {label: int(channels[label]["channel"]) for label in expected}
        if actual != expected:
            errors.append(f"서보 채널 불일치: {actual} != {expected}")

        audio_files = config["audio"]["files"]
        for key in ("ready", "can", "clear_pet", "plastic", "paper", "other", "remove_wait"):
            if not audio_files.get(key):
                errors.append(f"오디오 설정 없음: {key}")
    except Exception as error:
        errors.append(f"hardware_config.json 검사 실패: {error}")

    if not compileall.compile_dir(ROOT, quiet=1, force=True):
        errors.append("Python 문법 검사 실패")

    if args.print_hashes:
        for relative in RUNTIME_ASSETS:
            path = ROOT / relative
            if path.is_file():
                print(f"{sha256(path)}  {relative}")

    for warning in warnings:
        print(f"[WARNING] {warning}")

    if errors:
        print("[PRE-FLIGHT FAILED]")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[PRE-FLIGHT PASS]")
    print("소스, 설정, 서보 채널, 오디오 등록 및 Python 문법 정상")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
