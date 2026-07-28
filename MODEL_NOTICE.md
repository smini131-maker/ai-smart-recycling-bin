# Model and Dataset Notice

## 포함된 모델

| 파일 | 역할 | 테스트 지표 |
|---|---|---|
| `model/garbage_classifier.tflite` | 6종 기본 분류 | accuracy 약 86.18% |
| `model/pet_plastic_classifier.tflite` | 투명 PET/플라스틱 전문 분류 | TFLite accuracy 약 96.44% |

모델 입력은 RGB `float32` 배열이며 크기는 `224 × 224`입니다. MobileNetV2 전처리가 모델 그래프 내부에 포함되어 있습니다.

## 데이터 출처 표기

저장소의 메타데이터에는 다음 학습 데이터 출처가 기록되어 있습니다.

- AI Hub 71385 indoor sorter
- AI Hub 495 PP

원본 학습 데이터는 저장소에 포함하지 않습니다. 원본 데이터의 재배포 및 이용은 해당 제공기관의 이용약관과 라이선스를 따라야 합니다.

## 자산 라이선스 범위

`LICENSE`의 MIT 조건은 이 프로젝트에서 작성한 소스코드에 적용됩니다. 모델 파일과 음성 파일은 대회 작품 재현 및 검증을 위해 포함되며, 모델 학습에 사용된 원본 데이터의 권리는 각 제공기관에 있습니다.
