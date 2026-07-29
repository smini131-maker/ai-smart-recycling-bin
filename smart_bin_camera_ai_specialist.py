from __future__ import annotations

from pathlib import Path
from typing import Any

import smart_bin_camera_ai as base
from pet_plastic_specialist_runtime import (
    PetPlasticSpecialist,
    recognize_pet_or_plastic,
)

PROJECT_DIR = Path("/home/smini131/smart_bin")
SPECIALIST_MODEL_PATH = (
    PROJECT_DIR
    / "model"
    / "pet_plastic_classifier.tflite"
)
SPECIALIST_LABELS_PATH = (
    PROJECT_DIR
    / "model"
    / "pet_plastic_labels.txt"
)

TARGET_PRIMARY_LABELS = {
    "clear_pet",
    "plastic",
}

_original_recognize_object = base.recognize_object
_specialist: PetPlasticSpecialist | None = None


def _find_camera(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any | None:
    camera = kwargs.get("picam2")

    if camera is not None and hasattr(camera, "capture_array"):
        return camera

    for value in args:
        if hasattr(value, "capture_array"):
            return value

    return None


def _get_primary_label(
    result: Any,
) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "", ""

    status = str(result.get("status", "")).strip()
    label = str(result.get("label", "")).strip()

    return status, label


def recognize_object_with_specialist(
    *args: Any,
    **kwargs: Any,
) -> Any:
    global _specialist

    primary_result = _original_recognize_object(
        *args,
        **kwargs,
    )

    primary_status, primary_label = _get_primary_label(
        primary_result
    )

    if primary_label not in TARGET_PRIMARY_LABELS:
        return primary_result

    if primary_status and primary_status != "confirmed":
        return primary_result

    if not isinstance(primary_result, dict):
        print(
            "[SECONDARY WARNING] Primary result is not a dictionary. "
            "The original result will be used."
        )
        return primary_result

    camera = _find_camera(args, kwargs)

    if camera is None:
        print(
            "[SECONDARY WARNING] Camera object was not found. "
            "The original result will be used."
        )
        return primary_result

    prepare_model_input = getattr(
        base,
        "prepare_model_input",
        None,
    )

    if not callable(prepare_model_input):
        print(
            "[SECONDARY WARNING] prepare_model_input was not found. "
            "The original result will be used."
        )
        return primary_result

    if _specialist is None:
        print("[SECONDARY INIT] Loading PET/plastic model")
        _specialist = PetPlasticSpecialist(
            SPECIALIST_MODEL_PATH,
            SPECIALIST_LABELS_PATH,
            num_threads=4,
        )
        print("[SECONDARY INIT] PET/plastic model ready")

    secondary_result = recognize_pet_or_plastic(
        picam2=camera,
        prepare_model_input=prepare_model_input,
        specialist=_specialist,
        history_size=7,
        required_votes=5,
        confidence_threshold=0.85,
        interval_sec=0.20,
    )

    merged_result = dict(primary_result)
    merged_result["primary_label"] = primary_label
    merged_result["primary_status"] = primary_status
    merged_result["secondary_used"] = True
    merged_result["secondary_result"] = dict(
        secondary_result
    )

    if secondary_result["status"] == "confirmed":
        merged_result["status"] = "confirmed"
        merged_result["label"] = secondary_result["label"]
        merged_result["confidence"] = secondary_result[
            "confidence"
        ]
        merged_result["mean_confidence"] = secondary_result[
            "mean_confidence"
        ]
        merged_result["votes"] = secondary_result["votes"]
        merged_result["vote_text"] = secondary_result[
            "vote_text"
        ]

        print(
            "[SECONDARY RESULT] "
            f"{primary_label} -> {merged_result['label']} "
            f"({merged_result['confidence'] * 100.0:.1f}%)"
        )
    else:
        merged_result["status"] = "uncertain"
        merged_result["label"] = secondary_result["label"]
        merged_result["confidence"] = secondary_result[
            "confidence"
        ]
        merged_result["mean_confidence"] = secondary_result[
            "mean_confidence"
        ]
        merged_result["votes"] = secondary_result["votes"]
        merged_result["vote_text"] = secondary_result[
            "vote_text"
        ]

        print(
            "[SECONDARY RESULT] Uncertain PET/plastic decision"
        )

    return merged_result


base.recognize_object = recognize_object_with_specialist


if __name__ == "__main__":
    try:
        raise SystemExit(base.main())
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")
        raise SystemExit(130)
