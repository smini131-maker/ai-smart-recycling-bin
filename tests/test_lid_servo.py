import time
from adafruit_servokit import ServoKit

CHANNEL = 0

# 처음 시험할 임시 각도
CLOSED_ANGLE = 90
OPEN_ANGLE = 130

kit = ServoKit(channels=16, address=0x40, frequency=50)
servo = kit.servo[CHANNEL]
servo.set_pulse_width_range(600, 2400)


def move_slowly(start_angle, end_angle, delay=0.03):
    step = 1 if end_angle > start_angle else -1

    for angle in range(start_angle, end_angle + step, step):
        servo.angle = angle
        time.sleep(delay)


try:
    print("닫힘 위치로 이동")
    servo.angle = CLOSED_ANGLE
    time.sleep(2)

    print("3초 후 뚜껑을 엽니다.")
    time.sleep(3)

    move_slowly(CLOSED_ANGLE, OPEN_ANGLE)
    print("뚜껑 열림")
    time.sleep(3)

    move_slowly(OPEN_ANGLE, CLOSED_ANGLE)
    print("뚜껑 닫힘")
    time.sleep(2)

finally:
    servo.angle = None

print("뚜껑 1개 테스트 완료")
