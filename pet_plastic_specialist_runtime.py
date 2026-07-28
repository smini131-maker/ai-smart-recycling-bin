from __future__ import annotations

import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np


def _load_interpreter_class():
    try:
        from ai_edge_litert.interpreter import Interpreter
        return Interpreter
    except ImportError:
        pass

    try:
        from tflite_runtime.interpreter import Interpreter
        return Interpreter
    except ImportError:
        pass

    try:
        from tensorflow.lite import Interpreter
        return Interpreter
    except ImportError as error:
        raise ImportError(
            "LiteRT interpreter is not installed. "
            "Activate the project virtual environment and install "
            "ai-edge-litert."
        ) from error


class PetPlasticSpecialist:
    """Second-stage LiteRT classifier for clear PET versus plastic."""

    def __init__(
        self,
        model_path: Path,
        labels_path: Path,
        *,
        num_threads: int = 4,
    ) -> None:
        model_path = Path(model_path)
        labels_path = Path(labels_path)

        if not model_path.is_file():
            raise FileNotFoundError(
                f"Second-stage model file not found: {model_path}"
            )

        if not labels_path.is_file():
            raise FileNotFoundError(
                f"Second-stage labels file not found: {labels_path}"
            )

        labels = [
            line.strip()
            for line in labels_path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        if labels != ["clear_pet", "plastic"]:
            raise ValueError(
                "Unexpected second-stage label order: "
                f"{labels}"
            )

        self.labels = labels
        Interpreter = _load_interpreter_class()

        try:
            self.interpreter = Interpreter(
                model_path=str(model_path),
                num_threads=num_threads,
            )
        except TypeError:
            self.interpreter = Interpreter(
                model_path=str(model_path)
            )

        self.interpreter.allocate_tensors()

        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()

        if len(input_details) != 1 or len(output_details) != 1:
            raise ValueError(
                "Unexpected number of model input/output tensors."
            )

        self.input_detail = input_details[0]
        self.output_detail = output_details[0]

        input_shape = tuple(
            int(value)
            for value in self.input_detail["shape"]
        )
        output_shape = tuple(
            int(value)
            for value in self.output_detail["shape"]
        )

        if input_shape != (1, 224, 224, 3):
            raise ValueError(
                f"Unexpected second-stage input shape: {input_shape}"
            )

        if output_shape != (1, 2):
            raise ValueError(
                f"Unexpected second-stage output shape: {output_shape}"
            )

        if np.dtype(self.input_detail["dtype"]) != np.float32:
            raise TypeError(
                "Second-stage input dtype must be float32."
            )

        if np.dtype(self.output_detail["dtype"]) != np.float32:
            raise TypeError(
                "Second-stage output dtype must be float32."
            )

    def predict(
        self,
        model_input: np.ndarray,
    ) -> tuple[str, float, np.ndarray, float]:
        model_input = np.asarray(
            model_input,
            dtype=np.float32,
        )

        if model_input.shape != (1, 224, 224, 3):
            raise ValueError(
                "Unexpected second-stage input shape: "
                f"{model_input.shape}"
            )

        self.interpreter.set_tensor(
            int(self.input_detail["index"]),
            model_input,
        )

        started_at = time.perf_counter()
        self.interpreter.invoke()
        elapsed_sec = time.perf_counter() - started_at

        probabilities = np.asarray(
            self.interpreter.get_tensor(
                int(self.output_detail["index"])
            ),
            dtype=np.float32,
        ).reshape(-1)

        if probabilities.size != 2:
            raise ValueError(
                "Unexpected second-stage output length: "
                f"{probabilities.size}"
            )

        if not np.all(np.isfinite(probabilities)):
            raise ValueError(
                "Second-stage output contains NaN or Inf."
            )

        probability_sum = float(
            np.sum(probabilities, dtype=np.float64)
        )

        if abs(probability_sum - 1.0) > 0.02:
            raise ValueError(
                "Second-stage probability sum is invalid: "
                f"{probability_sum:.8f}"
            )

        index = int(np.argmax(probabilities))

        return (
            self.labels[index],
            float(probabilities[index]),
            probabilities,
            elapsed_sec,
        )


def recognize_pet_or_plastic(
    *,
    picam2: Any,
    prepare_model_input: Any,
    specialist: PetPlasticSpecialist,
    history_size: int = 7,
    required_votes: int = 5,
    confidence_threshold: float = 0.85,
    interval_sec: float = 0.20,
) -> dict[str, Any]:
    history: deque[tuple[str, float]] = deque(
        maxlen=history_size
    )
    inference_times: list[float] = []
    started_at = time.monotonic()

    print("[SECONDARY] Rechecking clear_pet versus plastic")

    for frame_number in range(1, history_size + 1):
        loop_started_at = time.monotonic()

        frame_rgb = picam2.capture_array("main")
        model_input = prepare_model_input(frame_rgb)

        (
            label,
            confidence,
            probabilities,
            inference_sec,
        ) = specialist.predict(model_input)

        history.append((label, confidence))
        inference_times.append(inference_sec)

        print(
            f"[SECONDARY {frame_number}/{history_size}] "
            f"top={label} {confidence * 100.0:.1f}% "
            f"| clear_pet={probabilities[0] * 100.0:.1f}% "
            f"| plastic={probabilities[1] * 100.0:.1f}%"
        )

        sleep_time = max(
            0.0,
            interval_sec
            - (time.monotonic() - loop_started_at),
        )
        time.sleep(sleep_time)

    counts = Counter(
        label
        for label, _ in history
    )

    candidates: list[tuple[str, int, float]] = []

    for label in ("clear_pet", "plastic"):
        confidences = [
            confidence
            for history_label, confidence in history
            if history_label == label
        ]

        vote_count = len(confidences)
        mean_confidence = (
            float(np.mean(confidences))
            if confidences
            else 0.0
        )

        candidates.append(
            (label, vote_count, mean_confidence)
        )

    candidates.sort(
        key=lambda item: (-item[1], -item[2])
    )

    winner_label, winner_votes, winner_confidence = candidates[0]

    status = (
        "confirmed"
        if (
            winner_votes >= required_votes
            and winner_confidence >= confidence_threshold
        )
        else "uncertain"
    )

    vote_text = ", ".join(
        f"{label}={counts.get(label, 0)}"
        for label in ("clear_pet", "plastic")
    )

    return {
        "status": status,
        "label": winner_label,
        "confidence": winner_confidence,
        "mean_confidence": winner_confidence,
        "votes": winner_votes,
        "history_count": len(history),
        "vote_text": vote_text,
        "elapsed_sec": time.monotonic() - started_at,
        "average_inference_sec": (
            float(np.mean(inference_times))
            if inference_times
            else 0.0
        ),
    }
