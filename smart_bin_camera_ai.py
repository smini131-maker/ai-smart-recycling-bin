from __future__ import annotations

import sys
import time
from collections import Counter, deque
from enum import Enum, auto
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter
from libcamera import controls
from picamera2 import Picamera2


# ============================================================
# 파일 경로
# ============================================================

PROJECT_DIR = Path("/home/smini131/smart_bin")
MODEL_PATH = PROJECT_DIR / "model" / "garbage_classifier.tflite"
LABELS_PATH = PROJECT_DIR / "model" / "labels.txt"

MINIMUM_MODEL_SIZE_BYTES = 100_000


# ============================================================
# 카메라 설정
# ============================================================

# AI 분류용 컬러 영상
MAIN_CAMERA_SIZE = (1280, 720)

# Picamera2에서 BGR888을 요청하면 capture_array() 배열은
# Python에서 RGB 채널 순서로 사용할 수 있다.
MAIN_CAMERA_FORMAT = "BGR888"

# 물체 진입 감지용 저해상도 영상
DETECTION_CAMERA_SIZE = (640, 360)
DETECTION_CAMERA_FORMAT = "YUV420"

CAMERA_WARMUP_SEC = 4.0


# ============================================================
# 임시 인식 구역 ROI
#
# 실제 분리수거함 구조물이 완성되면 반드시 다시 조정한다.
# ============================================================

ROI_X1_RATIO = 0.20
ROI_Y1_RATIO = 0.10
ROI_X2_RATIO = 0.80
ROI_Y2_RATIO = 0.90


# ============================================================
# 기준 배경 생성
# ============================================================

BACKGROUND_FRAME_COUNT = 20
BACKGROUND_FRAME_INTERVAL_SEC = 0.15
BACKGROUND_UPDATE_ALPHA = 0.02


# ============================================================
# 카메라 영상 기반 물체 감지
# ============================================================

DETECTION_IMAGE_SIZE = (240, 160)
GAUSSIAN_BLUR_RADIUS = 2.0

PIXEL_DIFF_THRESHOLD = 18.0

DETECT_THRESHOLD = 0.12

# 변화율뿐 아니라 평균 픽셀 차이도 함께 검사한다.
# 자동 초점이나 미세한 영상 흔들림에 의한 빈 화면 오감지를 줄인다.
DETECT_MEAN_DIFFERENCE_THRESHOLD = 8.0

CLEAR_THRESHOLD = 0.04

DETECT_CONSECUTIVE_FRAMES = 3
CLEAR_CONSECUTIVE_FRAMES = 4

MIN_OBJECT_PRESENT_SEC = 1.0
MIN_CLEAR_SEC = 1.5

IDLE_CHECK_INTERVAL_SEC = 0.50
ACTIVE_CHECK_INTERVAL_SEC = 0.25
STATUS_PRINT_INTERVAL_SEC = 3.0


# ============================================================
# AI 다중 프레임 안정화 판정
# ============================================================

HISTORY_SIZE = 7
REQUIRED_VOTES = 5
CONFIDENCE_THRESHOLD = 0.80

RECOGNITION_INTERVAL_SEC = 0.20
RECOGNITION_TIMEOUT_SEC = 5.0
MAX_RECOGNITION_FRAMES = 7

TFLITE_THREADS = 4


# ============================================================
# 모델 명세
# ============================================================

EXPECTED_INPUT_SHAPE = (1, 224, 224, 3)
EXPECTED_INPUT_DTYPE = np.dtype(np.float32)

EXPECTED_OUTPUT_SHAPE = (1, 6)
EXPECTED_OUTPUT_DTYPE = np.dtype(np.float32)

EXPECTED_LABELS = (
    "background",
    "can",
    "clear_pet",
    "plastic",
    "paper",
    "other",
)

KOREAN_NAMES = {
    "background": "물체 없음",
    "can": "캔",
    "clear_pet": "투명 페트병",
    "plastic": "플라스틱",
    "paper": "종이류",
    "other": "분류 대상 아님",
}

PROBABILITY_SUM_TOLERANCE = 0.02


class State(Enum):
    """스마트 분리수거함 카메라 AI 상태."""

    INITIALIZING = auto()
    WAITING = auto()
    DETECTING = auto()
    RECOGNIZING = auto()
    CONFIRMED = auto()
    LOCKED = auto()
    CLEARING = auto()


def validate_settings() -> None:
    """프로그램 설정값을 검사한다."""
    roi_values = (
        ROI_X1_RATIO,
        ROI_Y1_RATIO,
        ROI_X2_RATIO,
        ROI_Y2_RATIO,
    )

    if not all(0.0 <= value <= 1.0 for value in roi_values):
        raise ValueError("ROI 비율은 0.0~1.0 범위여야 합니다.")

    if ROI_X1_RATIO >= ROI_X2_RATIO:
        raise ValueError(
            "ROI_X1_RATIO는 ROI_X2_RATIO보다 작아야 합니다."
        )

    if ROI_Y1_RATIO >= ROI_Y2_RATIO:
        raise ValueError(
            "ROI_Y1_RATIO는 ROI_Y2_RATIO보다 작아야 합니다."
        )

    if CLEAR_THRESHOLD >= DETECT_THRESHOLD:
        raise ValueError(
            "CLEAR_THRESHOLD는 DETECT_THRESHOLD보다 작아야 합니다."
        )

    if REQUIRED_VOTES > HISTORY_SIZE:
        raise ValueError(
            "REQUIRED_VOTES는 HISTORY_SIZE보다 클 수 없습니다."
        )

    if MAX_RECOGNITION_FRAMES < HISTORY_SIZE:
        raise ValueError(
            "MAX_RECOGNITION_FRAMES는 HISTORY_SIZE 이상이어야 합니다."
        )

    if not 0.0 <= CONFIDENCE_THRESHOLD <= 1.0:
        raise ValueError(
            "CONFIDENCE_THRESHOLD는 0.0~1.0 범위여야 합니다."
        )


def check_required_files() -> None:
    """모델과 라벨 파일을 검사한다."""
    print("[초기화] 모델 파일 확인 중")

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"모델 파일이 없습니다: {MODEL_PATH}"
        )

    if not LABELS_PATH.is_file():
        raise FileNotFoundError(
            f"라벨 파일이 없습니다: {LABELS_PATH}"
        )

    model_size = MODEL_PATH.stat().st_size

    if model_size < MINIMUM_MODEL_SIZE_BYTES:
        raise ValueError(
            "모델 파일 크기가 지나치게 작습니다. "
            f"현재 크기: {model_size:,} bytes"
        )

    print(f"  모델: {MODEL_PATH}")
    print(f"  모델 크기: {model_size:,} bytes")
    print(f"  라벨: {LABELS_PATH}")


def load_labels() -> list[str]:
    """빈 줄을 제거하여 labels.txt를 읽는다."""
    text = LABELS_PATH.read_text(
        encoding="utf-8"
    )

    labels = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if not labels:
        raise ValueError("labels.txt에 라벨이 없습니다.")

    if tuple(labels) != EXPECTED_LABELS:
        raise ValueError(
            "labels.txt의 라벨 순서가 예상과 다릅니다.\n"
            f"현재: {labels}\n"
            f"예상: {list(EXPECTED_LABELS)}"
        )

    print("[초기화] 라벨 확인 완료")

    for index, label in enumerate(labels):
        print(
            f"  {index}: {label} "
            f"({KOREAN_NAMES[label]})"
        )

    return labels


def load_interpreter_class() -> tuple[type[Any], str]:
    """사용 가능한 LiteRT/TFLite Interpreter를 찾는다."""
    import_errors: list[str] = []

    try:
        from ai_edge_litert.interpreter import Interpreter

        return Interpreter, "ai-edge-litert"
    except (ImportError, ModuleNotFoundError) as exc:
        import_errors.append(
            f"ai-edge-litert: {exc}"
        )

    try:
        from tflite_runtime.interpreter import Interpreter

        return Interpreter, "tflite-runtime"
    except (ImportError, ModuleNotFoundError) as exc:
        import_errors.append(
            f"tflite-runtime: {exc}"
        )

    try:
        from tensorflow.lite import Interpreter

        return Interpreter, "TensorFlow Lite"
    except (ImportError, ModuleNotFoundError) as exc:
        import_errors.append(
            f"TensorFlow Lite: {exc}"
        )

    error_text = "\n".join(
        f"  - {error}"
        for error in import_errors
    )

    raise RuntimeError(
        "사용 가능한 LiteRT/TFLite Interpreter가 없습니다.\n"
        f"{error_text}"
    )


def shape_to_tuple(
    tensor_detail: dict[str, Any],
) -> tuple[int, ...]:
    """Tensor shape를 정수 튜플로 변환한다."""
    return tuple(
        int(value)
        for value in tensor_detail["shape"]
    )


def create_interpreter(
    labels: list[str],
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """TFLite 모델을 불러오고 입출력 정보를 검사한다."""
    print("[초기화] TFLite 모델 로딩 중")

    interpreter_class, runtime_name = load_interpreter_class()

    print(f"  런타임: {runtime_name}")

    try:
        interpreter = interpreter_class(
            model_path=str(MODEL_PATH),
            num_threads=TFLITE_THREADS,
        )
    except TypeError:
        print(
            "  num_threads 옵션을 지원하지 않아 "
            "기본 설정으로 로딩합니다."
        )

        interpreter = interpreter_class(
            model_path=str(MODEL_PATH)
        )

    interpreter.allocate_tensors()

    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    if len(input_details) != 1:
        raise ValueError(
            f"입력 tensor가 1개가 아닙니다: {len(input_details)}개"
        )

    if len(output_details) != 1:
        raise ValueError(
            f"출력 tensor가 1개가 아닙니다: {len(output_details)}개"
        )

    input_detail = input_details[0]
    output_detail = output_details[0]

    input_shape = shape_to_tuple(input_detail)
    output_shape = shape_to_tuple(output_detail)

    input_dtype = np.dtype(
        input_detail["dtype"]
    )
    output_dtype = np.dtype(
        output_detail["dtype"]
    )

    print("[초기화] 모델 입출력 정보")
    print(f"  입력 shape: {input_shape}")
    print(f"  입력 dtype: {input_dtype}")
    print(f"  출력 shape: {output_shape}")
    print(f"  출력 dtype: {output_dtype}")

    if input_shape != EXPECTED_INPUT_SHAPE:
        raise ValueError(
            "모델 입력 shape가 예상과 다릅니다. "
            f"현재: {input_shape}, 예상: {EXPECTED_INPUT_SHAPE}"
        )

    if input_dtype != EXPECTED_INPUT_DTYPE:
        raise TypeError(
            "모델 입력 dtype이 float32가 아닙니다. "
            f"현재: {input_dtype}"
        )

    if output_shape != EXPECTED_OUTPUT_SHAPE:
        raise ValueError(
            "모델 출력 shape가 예상과 다릅니다. "
            f"현재: {output_shape}, 예상: {EXPECTED_OUTPUT_SHAPE}"
        )

    if output_dtype != EXPECTED_OUTPUT_DTYPE:
        raise TypeError(
            "모델 출력 dtype이 float32가 아닙니다. "
            f"현재: {output_dtype}"
        )

    output_class_count = int(
        np.prod(output_shape[1:])
    )

    if output_class_count != len(labels):
        raise ValueError(
            "모델 출력 클래스 수와 라벨 수가 다릅니다. "
            f"출력: {output_class_count}, 라벨: {len(labels)}"
        )

    print("[초기화] TFLite 모델 준비 완료")

    return interpreter, input_detail, output_detail


def calculate_roi_coordinates(
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """ROI 비율을 실제 픽셀 좌표로 변환한다."""
    x1 = int(round(width * ROI_X1_RATIO))
    y1 = int(round(height * ROI_Y1_RATIO))
    x2 = int(round(width * ROI_X2_RATIO))
    y2 = int(round(height * ROI_Y2_RATIO))

    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))

    return x1, y1, x2, y2


def extract_luma_from_yuv420(
    yuv_array: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """YUV420 배열에서 밝기 정보인 Y 평면만 꺼낸다."""
    if not isinstance(yuv_array, np.ndarray):
        raise TypeError(
            "저해상도 카메라 결과가 NumPy 배열이 아닙니다."
        )

    if yuv_array.ndim != 2:
        raise ValueError(
            "YUV420 배열이 2차원이 아닙니다. "
            f"현재 shape: {yuv_array.shape}"
        )

    if yuv_array.shape[0] < height:
        raise ValueError(
            "YUV420 배열 높이가 예상보다 작습니다. "
            f"현재: {yuv_array.shape}, 예상 높이: {height}"
        )

    if yuv_array.shape[1] < width:
        raise ValueError(
            "YUV420 배열 너비가 예상보다 작습니다. "
            f"현재: {yuv_array.shape}, 예상 너비: {width}"
        )

    luma = yuv_array[:height, :width]

    if luma.dtype != np.uint8:
        luma = luma.astype(
            np.uint8,
            copy=False,
        )

    return np.ascontiguousarray(luma)


def preprocess_detection_frame(
    yuv_array: np.ndarray,
    width: int,
    height: int,
) -> np.ndarray:
    """저해상도 영상에서 ROI를 잘라 감지용 영상으로 만든다."""
    luma = extract_luma_from_yuv420(
        yuv_array,
        width,
        height,
    )

    x1, y1, x2, y2 = calculate_roi_coordinates(
        width,
        height,
    )

    roi_luma = luma[y1:y2, x1:x2]

    if roi_luma.size == 0:
        raise ValueError(
            "물체 감지 ROI가 비어 있습니다."
        )

    pil_image = Image.fromarray(
        roi_luma
    )

    resized = pil_image.resize(
        DETECTION_IMAGE_SIZE,
        resample=Image.Resampling.BILINEAR,
    )

    blurred = resized.filter(
        ImageFilter.GaussianBlur(
            radius=GAUSSIAN_BLUR_RADIUS
        )
    )

    processed = np.asarray(
        blurred,
        dtype=np.float32,
    )

    expected_shape = (
        DETECTION_IMAGE_SIZE[1],
        DETECTION_IMAGE_SIZE[0],
    )

    if processed.shape != expected_shape:
        raise ValueError(
            "감지 영상 shape가 예상과 다릅니다. "
            f"현재: {processed.shape}, 예상: {expected_shape}"
        )

    if not np.all(np.isfinite(processed)):
        raise ValueError(
            "감지 영상에 NaN 또는 Inf가 있습니다."
        )

    return processed


def build_background(
    picam2: Picamera2,
    detection_width: int,
    detection_height: int,
) -> np.ndarray:
    """여러 빈 프레임의 중앙값으로 기준 배경을 생성한다."""
    print("[초기화] 기준 배경 생성 중")
    print("[주의] 인식 구역을 비운 상태로 유지하세요.")

    frames: list[np.ndarray] = []

    for index in range(BACKGROUND_FRAME_COUNT):
        yuv_array = picam2.capture_array(
            "lores"
        )

        processed = preprocess_detection_frame(
            yuv_array,
            detection_width,
            detection_height,
        )

        frames.append(processed)

        current_count = index + 1

        if (
            current_count == 1
            or current_count % 5 == 0
            or current_count == BACKGROUND_FRAME_COUNT
        ):
            print(
                f"  기준 배경 수집: "
                f"{current_count}/{BACKGROUND_FRAME_COUNT}"
            )

        time.sleep(
            BACKGROUND_FRAME_INTERVAL_SEC
        )

    stacked = np.stack(
        frames,
        axis=0,
    )

    background = np.median(
        stacked,
        axis=0,
    ).astype(np.float32)

    variation = float(
        np.mean(
            np.std(stacked, axis=0)
        )
    )

    print("[초기화] 기준 배경 생성 완료")
    print(
        f"  평균 밝기: "
        f"{float(np.mean(background)):.2f}"
    )
    print(
        f"  수집 중 평균 표준편차: "
        f"{variation:.2f}"
    )

    return background


def calculate_change(
    background: np.ndarray,
    current: np.ndarray,
) -> tuple[float, float, float]:
    """기준 배경과 현재 ROI의 변화량을 계산한다."""
    if background.shape != current.shape:
        raise ValueError(
            "기준 배경과 현재 영상의 shape가 다릅니다."
        )

    brightness_shift = float(
        np.median(current - background)
    )

    brightness_corrected = (
        current - brightness_shift
    )

    difference = np.abs(
        brightness_corrected - background
    )

    changed_ratio = float(
        np.mean(
            difference >= PIXEL_DIFF_THRESHOLD
        )
    )

    mean_difference = float(
        np.mean(difference)
    )

    return (
        changed_ratio,
        mean_difference,
        brightness_shift,
    )


def update_background(
    background: np.ndarray,
    current: np.ndarray,
    alpha: float = BACKGROUND_UPDATE_ALPHA,
) -> np.ndarray:
    """빈 상태에서 기준 배경을 천천히 갱신한다."""
    updated = (
        (1.0 - alpha) * background
        + alpha * current
    )

    return updated.astype(
        np.float32,
        copy=False,
    )


def prepare_model_input(
    frame_rgb: np.ndarray,
) -> np.ndarray:
    """
    전체 RGB 프레임에서 ROI를 자른 뒤 중앙 정사각형 크롭하고
    224×224 float32 0~255 입력을 만든다.
    """
    if not isinstance(frame_rgb, np.ndarray):
        raise TypeError(
            "분류용 카메라 프레임이 NumPy 배열이 아닙니다."
        )

    if frame_rgb.ndim != 3:
        raise ValueError(
            "분류용 카메라 프레임이 3차원이 아닙니다. "
            f"현재: {frame_rgb.shape}"
        )

    if frame_rgb.shape[2] != 3:
        raise ValueError(
            "분류용 카메라 프레임의 채널 수가 3개가 아닙니다."
        )

    if frame_rgb.dtype != np.uint8:
        raise TypeError(
            "분류용 카메라 프레임 dtype이 uint8이 아닙니다. "
            f"현재: {frame_rgb.dtype}"
        )

    height, width, _ = frame_rgb.shape

    x1, y1, x2, y2 = calculate_roi_coordinates(
        width,
        height,
    )

    roi_rgb = frame_rgb[y1:y2, x1:x2]

    if roi_rgb.size == 0:
        raise ValueError(
            "분류용 ROI가 비어 있습니다."
        )

    roi_height, roi_width, _ = roi_rgb.shape
    square_size = min(
        roi_width,
        roi_height,
    )

    square_x1 = (
        roi_width - square_size
    ) // 2

    square_y1 = (
        roi_height - square_size
    ) // 2

    square_x2 = square_x1 + square_size
    square_y2 = square_y1 + square_size

    cropped_rgb = roi_rgb[
        square_y1:square_y2,
        square_x1:square_x2,
    ]

    if cropped_rgb.size == 0:
        raise ValueError(
            "분류용 중앙 크롭 결과가 비어 있습니다."
        )

    pil_image = Image.fromarray(
        cropped_rgb
    )

    resized = pil_image.resize(
        (224, 224),
        resample=Image.Resampling.BILINEAR,
    )

    resized_rgb = np.asarray(
        resized,
        dtype=np.uint8,
    )

    if resized_rgb.shape != (224, 224, 3):
        raise ValueError(
            "224×224 리사이즈 결과가 올바르지 않습니다. "
            f"현재: {resized_rgb.shape}"
        )

    model_input = resized_rgb.astype(
        np.float32,
        copy=False,
    )

    model_input = np.expand_dims(
        model_input,
        axis=0,
    )

    if model_input.shape != EXPECTED_INPUT_SHAPE:
        raise ValueError(
            "모델 입력 shape가 잘못되었습니다. "
            f"현재: {model_input.shape}"
        )

    if model_input.dtype != np.float32:
        raise TypeError(
            "모델 입력 dtype이 float32가 아닙니다."
        )

    if not np.all(np.isfinite(model_input)):
        raise ValueError(
            "모델 입력에 NaN 또는 Inf가 있습니다."
        )

    minimum = float(
        np.min(model_input)
    )
    maximum = float(
        np.max(model_input)
    )

    if minimum < 0.0 or maximum > 255.0:
        raise ValueError(
            "모델 입력 범위가 0~255를 벗어났습니다. "
            f"현재: {minimum:.2f}~{maximum:.2f}"
        )

    return model_input


def run_single_inference(
    interpreter: Any,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    model_input: np.ndarray,
    labels: list[str],
) -> tuple[str, float, np.ndarray, float]:
    """한 프레임의 TFLite 추론을 실행한다."""
    interpreter.set_tensor(
        int(input_detail["index"]),
        model_input,
    )

    inference_started_at = time.perf_counter()

    interpreter.invoke()

    inference_elapsed_sec = (
        time.perf_counter()
        - inference_started_at
    )

    raw_output = interpreter.get_tensor(
        int(output_detail["index"])
    )

    probabilities = np.asarray(
        raw_output,
        dtype=np.float32,
    ).reshape(-1)

    if probabilities.size != len(labels):
        raise ValueError(
            "출력 확률 개수와 라벨 수가 다릅니다. "
            f"출력: {probabilities.size}, 라벨: {len(labels)}"
        )

    if not np.all(np.isfinite(probabilities)):
        raise ValueError(
            "모델 출력에 NaN 또는 Inf가 있습니다."
        )

    probability_sum = float(
        np.sum(
            probabilities,
            dtype=np.float64,
        )
    )

    if (
        abs(probability_sum - 1.0)
        > PROBABILITY_SUM_TOLERANCE
    ):
        raise ValueError(
            "모델 출력 확률 합이 1과 크게 다릅니다. "
            f"현재: {probability_sum:.8f}"
        )

    best_index = int(
        np.argmax(probabilities)
    )

    best_label = labels[best_index]
    best_confidence = float(
        probabilities[best_index]
    )

    return (
        best_label,
        best_confidence,
        probabilities,
        inference_elapsed_sec,
    )


def format_vote_counts(
    history: deque[tuple[str, float]],
) -> str:
    """현재까지의 클래스별 투표 수를 문자열로 만든다."""
    counts = Counter(
        label
        for label, _ in history
    )

    parts: list[str] = []

    for label in EXPECTED_LABELS:
        count = counts.get(label, 0)

        if count > 0:
            parts.append(
                f"{label}={count}"
            )

    return ", ".join(parts)


def recognize_object(
    picam2: Picamera2,
    interpreter: Any,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    labels: list[str],
) -> dict[str, Any]:
    """7개의 추론 결과를 모아 최종 분류를 결정한다."""
    history: deque[tuple[str, float]] = deque(
        maxlen=HISTORY_SIZE
    )

    recognition_started_at = time.monotonic()
    inference_times: list[float] = []

    frame_number = 0

    print("[인식] AI 분류 중")
    print(
        f"[인식] {HISTORY_SIZE}개 프레임을 수집합니다."
    )

    while (
        frame_number < MAX_RECOGNITION_FRAMES
        and len(history) < HISTORY_SIZE
    ):
        if (
            time.monotonic()
            - recognition_started_at
            >= RECOGNITION_TIMEOUT_SEC
        ):
            break

        loop_started_at = time.monotonic()

        frame_rgb = picam2.capture_array(
            "main"
        )

        model_input = prepare_model_input(
            frame_rgb
        )

        (
            best_label,
            best_confidence,
            probabilities,
            inference_elapsed_sec,
        ) = run_single_inference(
            interpreter,
            input_detail,
            output_detail,
            model_input,
            labels,
        )

        history.append(
            (
                best_label,
                best_confidence,
            )
        )

        inference_times.append(
            inference_elapsed_sec
        )

        frame_number += 1

        probability_text = " | ".join(
            f"{label}={float(probability) * 100.0:.1f}%"
            for label, probability
            in zip(labels, probabilities)
        )

        print(
            f"[인식 {frame_number}/{HISTORY_SIZE}] "
            f"최고={best_label} "
            f"{best_confidence * 100.0:.1f}% "
            f"| 추론 {inference_elapsed_sec * 1000.0:.2f}ms"
        )

        print(
            f"  확률: {probability_text}"
        )

        print(
            f"  현재 투표: "
            f"{format_vote_counts(history)}"
        )

        loop_elapsed_sec = (
            time.monotonic()
            - loop_started_at
        )

        sleep_time = max(
            0.0,
            RECOGNITION_INTERVAL_SEC
            - loop_elapsed_sec,
        )

        time.sleep(sleep_time)

    total_elapsed_sec = (
        time.monotonic()
        - recognition_started_at
    )

    if len(history) < HISTORY_SIZE:
        return {
            "status": "timeout",
            "history_count": len(history),
            "elapsed_sec": total_elapsed_sec,
            "average_inference_sec": (
                float(np.mean(inference_times))
                if inference_times
                else 0.0
            ),
        }

    counts = Counter(
        label
        for label, _ in history
    )

    candidate_data: list[
        tuple[str, int, float]
    ] = []

    for label, vote_count in counts.items():
        confidences = [
            confidence
            for history_label, confidence in history
            if history_label == label
        ]

        mean_confidence = float(
            np.mean(confidences)
        )

        candidate_data.append(
            (
                label,
                vote_count,
                mean_confidence,
            )
        )

    label_order = {
        label: index
        for index, label in enumerate(EXPECTED_LABELS)
    }

    candidate_data.sort(
        key=lambda item: (
            -item[1],
            -item[2],
            label_order[item[0]],
        )
    )

    winner_label, winner_votes, winner_mean_confidence = (
        candidate_data[0]
    )

    consensus_ok = (
        winner_votes >= REQUIRED_VOTES
        and winner_mean_confidence
        >= CONFIDENCE_THRESHOLD
    )

    return {
        "status": (
            "confirmed"
            if consensus_ok
            else "uncertain"
        ),
        "label": winner_label,
        "votes": winner_votes,
        "mean_confidence": winner_mean_confidence,
        "history_count": len(history),
        "vote_text": format_vote_counts(history),
        "elapsed_sec": total_elapsed_sec,
        "average_inference_sec": (
            float(np.mean(inference_times))
            if inference_times
            else 0.0
        ),
    }


def print_recognition_result(
    result: dict[str, Any],
) -> None:
    """다중 프레임 판정 결과를 한국어로 출력한다."""
    print("=" * 76)

    status = str(
        result["status"]
    )

    if status == "timeout":
        print(
            "[실패] AI 인식 시간이 초과되었습니다."
        )

        print(
            f"  수집 프레임: "
            f"{result['history_count']}/{HISTORY_SIZE}"
        )

        print(
            f"  경과 시간: "
            f"{result['elapsed_sec']:.2f}초"
        )

        print(
            "[불확실] 물체를 제거한 뒤 다시 보여주세요."
        )

    elif status == "uncertain":
        label = str(
            result["label"]
        )

        print(
            "[불확실] 물체를 다시 보여주세요."
        )

        print(
            f"  최다 클래스: "
            f"{KOREAN_NAMES.get(label, label)}"
        )

        print(
            f"  투표: "
            f"{result['votes']}/{HISTORY_SIZE}"
        )

        print(
            f"  평균 신뢰도: "
            f"{result['mean_confidence'] * 100.0:.2f}%"
        )

        print(
            f"  전체 투표: "
            f"{result['vote_text']}"
        )

        print(
            "  확정 조건: "
            f"{REQUIRED_VOTES}/{HISTORY_SIZE}표 이상, "
            f"평균 {CONFIDENCE_THRESHOLD * 100.0:.0f}% 이상"
        )

    else:
        label = str(
            result["label"]
        )

        votes = int(
            result["votes"]
        )

        mean_confidence = float(
            result["mean_confidence"]
        )

        korean_name = KOREAN_NAMES.get(
            label,
            label,
        )

        if label in (
            "can",
            "clear_pet",
            "plastic",
            "paper",
        ):
            print(
                f"[확정] {korean_name} / "
                f"신뢰도 {mean_confidence * 100.0:.1f}%"
            )

        elif label == "other":
            print(
                f"[거부] 분류 대상 아님 / "
                f"신뢰도 {mean_confidence * 100.0:.1f}%"
            )

        elif label == "background":
            print(
                f"[불확실] 물체 위치를 다시 맞춰주세요 / "
                f"신뢰도 {mean_confidence * 100.0:.1f}%"
            )

        print(
            f"  투표: {votes}/{HISTORY_SIZE}"
        )

        print(
            f"  전체 투표: "
            f"{result['vote_text']}"
        )

        print(
            f"  전체 인식 시간: "
            f"{result['elapsed_sec']:.2f}초"
        )

        average_inference_sec = float(
            result["average_inference_sec"]
        )

        print(
            f"  평균 TFLite 추론 시간: "
            f"{average_inference_sec * 1000.0:.2f}ms"
        )

        if average_inference_sec > 0.0:
            print(
                f"  추론 환산 속도: "
                f"{1.0 / average_inference_sec:.2f} FPS"
            )

    print("=" * 76)


def print_settings(
    main_size: tuple[int, int],
    detection_size: tuple[int, int],
) -> None:
    """현재 프로그램의 주요 설정을 출력한다."""
    print("[설정] 카메라 AI 통합 프로그램")
    print(
        f"  분류 영상: "
        f"{main_size[0]}×{main_size[1]} "
        f"{MAIN_CAMERA_FORMAT}"
    )
    print(
        f"  감지 영상: "
        f"{detection_size[0]}×{detection_size[1]} "
        f"{DETECTION_CAMERA_FORMAT}"
    )
    print(
        f"  ROI: "
        f"x={ROI_X1_RATIO:.2f}~{ROI_X2_RATIO:.2f}, "
        f"y={ROI_Y1_RATIO:.2f}~{ROI_Y2_RATIO:.2f}"
    )
    print(
        f"  진입 임계값: "
        f"{DETECT_THRESHOLD * 100.0:.1f}%"
    )
    print(
        f"  제거 임계값: "
        f"{CLEAR_THRESHOLD * 100.0:.1f}%"
    )
    print(
        f"  판정 조건: "
        f"{HISTORY_SIZE}회 중 {REQUIRED_VOTES}회 이상, "
        f"평균 신뢰도 "
        f"{CONFIDENCE_THRESHOLD * 100.0:.0f}% 이상"
    )
    print("  디버그 사진 저장: 사용하지 않음")


def run_state_machine(
    picam2: Picamera2,
    interpreter: Any,
    input_detail: dict[str, Any],
    output_detail: dict[str, Any],
    labels: list[str],
    background: np.ndarray,
    detection_width: int,
    detection_height: int,
) -> None:
    """감지, 분류, 잠금, 제거 확인 상태 머신을 실행한다."""
    state = State.WAITING

    detect_count = 0
    clear_count = 0

    detect_started_at: float | None = None
    clear_started_at: float | None = None

    last_status_printed_at = 0.0

    print("[대기] 다음 물체를 기다리는 중")
    print("[안내] 종료하려면 Ctrl+C를 누르세요.")

    while True:
        loop_started_at = time.monotonic()

        yuv_array = picam2.capture_array(
            "lores"
        )

        current = preprocess_detection_frame(
            yuv_array,
            detection_width,
            detection_height,
        )

        (
            changed_ratio,
            mean_difference,
            brightness_shift,
        ) = calculate_change(
            background,
            current,
        )

        now = time.monotonic()

        is_detected = (
            changed_ratio >= DETECT_THRESHOLD
            and mean_difference >= DETECT_MEAN_DIFFERENCE_THRESHOLD
        )

        is_clear = (
            changed_ratio <= CLEAR_THRESHOLD
        )

        if state == State.WAITING:
            if is_detected:
                state = State.DETECTING
                detect_count = 1
                detect_started_at = now

                print(
                    "[감지] 물체 진입 후보 "
                    f"| 변화율 "
                    f"{changed_ratio * 100.0:.2f}%"
                )

            else:
                detect_count = 0
                detect_started_at = None

                if is_clear:
                    background = update_background(
                        background,
                        current,
                    )

        elif state == State.DETECTING:
            if is_detected:
                detect_count += 1

                object_present_sec = (
                    now - detect_started_at
                    if detect_started_at is not None
                    else 0.0
                )

                if (
                    detect_count
                    >= DETECT_CONSECUTIVE_FRAMES
                    and object_present_sec
                    >= MIN_OBJECT_PRESENT_SEC
                ):
                    print(
                        "[감지] 물체 진입 확인 "
                        f"| 변화율 "
                        f"{changed_ratio * 100.0:.2f}% "
                        f"| 유지 시간 "
                        f"{object_present_sec:.2f}초"
                    )

                    state = State.RECOGNIZING

                    recognition_result = recognize_object(
                        picam2,
                        interpreter,
                        input_detail,
                        output_detail,
                        labels,
                    )

                    state = State.CONFIRMED

                    print_recognition_result(
                        recognition_result
                    )

                    result_status = str(
                        recognition_result.get("status", "")
                    )
                    result_label = str(
                        recognition_result.get("label", "")
                    )

                    # 빈 화면의 초점·노출 변화가 물체 진입으로 잘못 감지된 경우
                    # LOCKED 상태로 들어가지 않고 현재 빈 화면을 다시 기준으로 만든다.
                    if (
                        result_status == "confirmed"
                        and result_label == "background"
                    ):
                        print(
                            "[복구] 빈 화면 오감지로 판단했습니다."
                        )
                        print(
                            "[복구] 현재 빈 화면으로 기준 배경을 다시 만듭니다."
                        )

                        recovery_frames: list[np.ndarray] = []

                        for _ in range(5):
                            recovery_yuv = picam2.capture_array(
                                "lores"
                            )

                            recovery_frame = preprocess_detection_frame(
                                recovery_yuv,
                                detection_width,
                                detection_height,
                            )

                            recovery_frames.append(
                                recovery_frame
                            )

                            time.sleep(0.10)

                        background = np.median(
                            np.stack(
                                recovery_frames,
                                axis=0,
                            ),
                            axis=0,
                        ).astype(np.float32)

                        state = State.WAITING

                        detect_count = 0
                        clear_count = 0
                        detect_started_at = None
                        clear_started_at = None

                        print(
                            "[대기] 다음 물체를 기다리는 중"
                        )

                        continue

                    state = State.LOCKED

                    detect_count = 0
                    clear_count = 0
                    detect_started_at = None
                    clear_started_at = None

                    print(
                        "[잠금] 같은 물체를 다시 인식하지 않습니다."
                    )
                    print(
                        "[잠금] 물체를 제거해 주세요."
                    )

            elif is_clear:
                print(
                    "[감지] 순간 변화로 판단하여 "
                    "후보를 취소합니다. "
                    f"| 변화율 "
                    f"{changed_ratio * 100.0:.2f}%"
                )

                state = State.WAITING
                detect_count = 0
                detect_started_at = None

                print(
                    "[대기] 다음 물체를 기다리는 중"
                )

        elif state == State.LOCKED:
            if is_clear:
                state = State.CLEARING
                clear_count = 1
                clear_started_at = now

                print(
                    "[초기화] 물체 제거 후보 "
                    f"| 변화율 "
                    f"{changed_ratio * 100.0:.2f}%"
                )

        elif state == State.CLEARING:
            if is_clear:
                clear_count += 1

                clear_elapsed_sec = (
                    now - clear_started_at
                    if clear_started_at is not None
                    else 0.0
                )

                if (
                    clear_count
                    >= CLEAR_CONSECUTIVE_FRAMES
                    and clear_elapsed_sec
                    >= MIN_CLEAR_SEC
                ):
                    print(
                        "[초기화] 물체 제거 확인 "
                        f"| 변화율 "
                        f"{changed_ratio * 100.0:.2f}% "
                        f"| 유지 시간 "
                        f"{clear_elapsed_sec:.2f}초"
                    )

                    background = update_background(
                        background,
                        current,
                        alpha=0.20,
                    )

                    state = State.WAITING

                    detect_count = 0
                    clear_count = 0
                    detect_started_at = None
                    clear_started_at = None

                    print(
                        "[대기] 다음 물체를 기다리는 중"
                    )

            elif is_detected:
                print(
                    "[초기화] 물체가 아직 남아 있어 "
                    "제거 확인을 취소합니다."
                )

                state = State.LOCKED
                clear_count = 0
                clear_started_at = None

        if (
            now - last_status_printed_at
            >= STATUS_PRINT_INTERVAL_SEC
        ):
            print(
                f"[상태] {state.name:<11} "
                f"| 변화율 "
                f"{changed_ratio * 100.0:6.2f}% "
                f"| 평균차이 "
                f"{mean_difference:6.2f} "
                f"| 밝기보정 "
                f"{brightness_shift:+6.2f}"
            )

            last_status_printed_at = now

        if state in (
            State.DETECTING,
            State.CLEARING,
        ):
            target_interval_sec = (
                ACTIVE_CHECK_INTERVAL_SEC
            )
        else:
            target_interval_sec = (
                IDLE_CHECK_INTERVAL_SEC
            )

        loop_elapsed_sec = (
            time.monotonic()
            - loop_started_at
        )

        sleep_time = max(
            0.0,
            target_interval_sec
            - loop_elapsed_sec,
        )

        time.sleep(sleep_time)


def main() -> int:
    """카메라 물체 감지와 TFLite 분류를 통합 실행한다."""
    print("=" * 76)
    print("스마트 분리수거함 카메라 AI 통합 프로그램")
    print("=" * 76)

    state = State.INITIALIZING
    print(f"[상태] {state.name}")

    validate_settings()
    check_required_files()

    labels = load_labels()

    (
        interpreter,
        input_detail,
        output_detail,
    ) = create_interpreter(
        labels
    )

    picam2: Picamera2 | None = None
    camera_started = False

    try:
        print("[초기화] 카메라 시작 중")

        picam2 = Picamera2()

        camera_config = picam2.create_preview_configuration(
            main={
                "size": MAIN_CAMERA_SIZE,
                "format": MAIN_CAMERA_FORMAT,
            },
            lores={
                "size": DETECTION_CAMERA_SIZE,
                "format": DETECTION_CAMERA_FORMAT,
            },
            buffer_count=4,
        )

        picam2.configure(
            camera_config
        )

        main_config = picam2.stream_configuration(
            "main"
        )

        detection_config = picam2.stream_configuration(
            "lores"
        )

        actual_main_size = tuple(
            int(value)
            for value in main_config["size"]
        )

        actual_main_format = str(
            main_config["format"]
        )

        actual_detection_size = tuple(
            int(value)
            for value in detection_config["size"]
        )

        actual_detection_format = str(
            detection_config["format"]
        )

        if actual_main_format != MAIN_CAMERA_FORMAT:
            raise ValueError(
                "분류용 카메라 형식이 예상과 다릅니다. "
                f"현재: {actual_main_format}"
            )

        if (
            actual_detection_format
            != DETECTION_CAMERA_FORMAT
        ):
            raise ValueError(
                "감지용 카메라 형식이 예상과 다릅니다. "
                f"현재: {actual_detection_format}"
            )

        print_settings(
            actual_main_size,
            actual_detection_size,
        )

        picam2.start()
        camera_started = True

        try:
            picam2.set_controls(
                {
                    "AfMode": (
                        controls.AfModeEnum.Continuous
                    ),
                }
            )

            print(
                "[초기화] 연속 자동 초점 활성화"
            )

        except Exception as exc:
            print(
                "[주의] 자동 초점 설정 실패: "
                f"{type(exc).__name__}: {exc}"
            )

        print(
            "[초기화] 카메라 노출과 "
            f"화이트밸런스 안정화 중 "
            f"({CAMERA_WARMUP_SEC:.1f}초)"
        )

        time.sleep(
            CAMERA_WARMUP_SEC
        )

        detection_width = int(
            actual_detection_size[0]
        )

        detection_height = int(
            actual_detection_size[1]
        )

        background = build_background(
            picam2,
            detection_width,
            detection_height,
        )

        run_state_machine(
            picam2,
            interpreter,
            input_detail,
            output_detail,
            labels,
            background,
            detection_width,
            detection_height,
        )

        return 0

    finally:
        if picam2 is not None:
            if camera_started:
                try:
                    picam2.stop()
                    print(
                        "[종료] 카메라 스트림 정지"
                    )
                except Exception as exc:
                    print(
                        "[주의] 카메라 정지 중 오류: "
                        f"{type(exc).__name__}: {exc}"
                    )

            try:
                picam2.close()
                print(
                    "[종료] 카메라 장치 해제"
                )
            except Exception as exc:
                print(
                    "[주의] 카메라 해제 중 오류: "
                    f"{type(exc).__name__}: {exc}"
                )


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )

    except KeyboardInterrupt:
        print(
            "\n[중단] 사용자가 Ctrl+C로 종료했습니다."
        )

        raise SystemExit(130)

    except Exception as exc:
        print(
            f"\n[오류] "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1)
