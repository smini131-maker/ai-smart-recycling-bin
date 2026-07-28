# 하드웨어 구성 및 배선

## Raspberry Pi 5 ↔ PCA9685

| Raspberry Pi 물리 핀 | 신호 | PCA9685 |
|---:|---|---|
| 1 | 3.3V | VCC |
| 3 | GPIO2 / SDA | SDA |
| 5 | GPIO3 / SCL | SCL |
| 6 | GND | GND |

## 서보 외부 전원

- SMPS `+5V` → PCA9685 `V+`
- SMPS `GND` → PCA9685 `GND`
- Raspberry Pi GND와 SMPS GND는 반드시 공통 접지
- 서보모터 전원을 Raspberry Pi 5V 핀에서 공급하지 않음
- 220V AC 단자는 노출되지 않도록 절연 및 덮개 사용

## 서보 채널

| 분류 | PCA9685 채널 | 닫힘 각도 | 열림 각도 |
|---|---:|---:|---:|
| 캔 | 0 | 170° | 10° |
| 투명 페트병 | 4 | 10° | 170° |
| 플라스틱 | 11 | 10° | 170° |
| 종이 | 15 | 10° | 170° |

각도는 현재 시제품 기준이며 기구물 조립 상태에 따라 `hardware_config.json`에서 재교정해야 합니다.

## PIR 센서

| PIR | Raspberry Pi |
|---|---|
| VCC | 5V, 물리 핀 2 |
| OUT | GPIO17, 물리 핀 11 |
| GND | GND, 물리 핀 6 |

PIR 센서는 부팅 후 안정화 시간이 필요합니다. 현재 설정은 45초입니다.

## 카메라

Camera Module 3를 CSI 커넥터에 연결합니다. 케이블 방향을 확인하고 전원이 꺼진 상태에서 연결해야 합니다.

## 점검 명령

```bash
sudo i2cdetect -y 1
rpicam-hello --list-cameras
aplay -l
```

PCA9685 기본 주소는 `0x40`이며 `0x70`은 All Call 주소로 표시될 수 있습니다.
