
import time
from pathlib import Path

import cv2
from libcamera import controls
from picamera2 import Picamera2


OUTPUT_PATH = Path(
    "/home/smini131/smart_bin/tests/python_camera_test.jpg"
)


def main() -> None:
    camera = Picamera2()

    config = camera.create_preview_configuration(
        main={
            "size": (640, 480),
            "format": "RGB888",
        }
    )

    camera.configure(config)

    camera.set_controls(
        {
            "AfMode": controls.AfModeEnum.Continuous,
        }
    )

    try:
        camera.start()

        # 카메라 밝기와 자동초점이 안정될 시간을 줍니다.
        time.sleep(3)

        frame = camera.capture_array()

        if frame is None:
            raise RuntimeError("카메라 프레임을 가져오지 못했습니다.")

        success = cv2.imwrite(
            str(OUTPUT_PATH),
            frame,
        )

        if not success:
            raise RuntimeError("사진 파일 저장에 실패했습니다.")

        print(f"사진 저장 완료: {OUTPUT_PATH}")

    finally:
        camera.stop()
        camera.close()


if __name__ == "__main__":
    main()
