# 설치, 오프라인 실행 및 자동 시작

## 오프라인 실행

추론에 필요한 `.tflite` 모델과 안내용 `.wav` 파일을 Raspberry Pi에 저장하면 인터넷 없이 실행할 수 있습니다. 인터넷은 최초 패키지 설치와 저장소 복제에만 필요합니다.

## 직접 실행

```bash
cd /home/smini131/smart_bin
source .venv/bin/activate
GPIOZERO_PIN_FACTORY=lgpio python -u smart_bin_final.py
```

## systemd 등록

```bash
sudo cp systemd/smart-bin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable smart-bin.service
sudo systemctl start smart-bin.service
```

상태 확인:

```bash
sudo systemctl status smart-bin.service --no-pager
sudo journalctl -u smart-bin.service -n 100 --no-pager
```

실시간 로그:

```bash
sudo journalctl -u smart-bin.service -f
```

## 수정 또는 테스트 전

서비스와 수동 실행을 동시에 켜면 카메라, GPIO, I²C 장치가 충돌할 수 있습니다.

```bash
sudo systemctl stop smart-bin.service
```

수정 후:

```bash
python -m py_compile smart_bin_final.py
sudo systemctl restart smart-bin.service
```

## 부팅 후 자동 실행 시험

```bash
sudo reboot
```

재부팅 후 약 1분 뒤:

```bash
sudo systemctl is-enabled smart-bin.service
sudo systemctl is-active smart-bin.service
```

정상 결과는 각각 `enabled`, `active`입니다.
