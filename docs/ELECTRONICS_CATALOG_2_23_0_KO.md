# 전장 제품 DB 확장 · v2.23.0

공식 제조사 자료를 2026-10-08에 확인한 125개 항목을 추가했다. 전체 카탈로그는 235개이며, 검색한 항목의 정확한 모델명과 공식 자료 링크를 CAD 부품 등록에 보존한다. 자료가 있다고 실제 펌웨어나 부품 동작을 모두 모사하는 것은 아니다.

| 구분 | 전체 항목 수 | 의미 |
| --- | ---: | --- |
| 전체 카탈로그 | 235 | 기존 항목과 신규 제품·참고 자료 |
| CAD 부품에 등록 가능 | 164 | 정확한 제품 식별 또는 확인된 단자 자료 |
| 보드 핀 자료 | 11 | 기존에 확인한 정확한 헤더/보드 지도 |
| 제품 단자 자료 | 49 | 모터·액추에이터·센서·드라이버 등의 확인된 단자 |
| 수동 단자 등록 | 104 | 확인되지 않은 핀 위치를 추정하지 않는 제품 등록 |
| 참고 전용 | 71 | 패키지·보드·옵션·동작 모델을 아직 특정하지 않은 자료 |

## 이번에 추가한 제품

| 범위 | 신규 수 | 대표 제품 |
| --- | ---: | --- |
| MCU 보드 | 41 | Nucleo 24종, Arduino 9종, ESP32 개발 보드 4종, Pico W/2 W, Teensy 4.0/4.1 |
| MPU 보드 | 3 | BeagleBone Black, BeaglePlay, BeagleY-AI |
| MPU 모듈 참고 자료 | 2 | Raspberry Pi Compute Module 4/5; carrier·메모리·무선 옵션을 특정해야 함 |
| 모터·스테퍼 드라이버 | 8 | DRV8251/8876/8711/8301/8313, TMC2209/2130/5160 |
| 센서·ADC·전원·통신 IC 참고 자료 | 19 | INA226/3221, ADS1115/1256, TMP117, LM1117, TPS5430, BQ24074/76920, SN65HVD230, MAX3232, PCA9306, ADXL355, MAX31865, LTC3780, BMI270/088, BMP390, BME680 |
| 스마트 액추에이터 | 9 | XL330-M077-T, XC330-T181/T288-T, XM430-W210-T/R, XH430-W350-T/R, XM540-W270-T/R |
| 정확한 퓨즈 주문 코드 | 29 | Littelfuse 218, 451 Nano², 287 ATOF |
| 수동 소자 | 14 | Panasonic 저항 6종·전해 콘덴서 2종, Bourns SRR1260 인덕터 6종 |

Nucleo 추가 모델: G031K8, G431RB, G491RE, G071RB, G070RB, F042K6, F031K6, F030R8, F091RC, F302R8, F303RE, F303ZE, F412ZG, F439ZI, F767ZI, H723ZG, H563ZI, H503RB, L073RZ, L031K6, L412KB, U575ZI-Q, WB55RG, WL55JC. 제품명은 모두 `NUCLEO-`로 시작한다. 보드에 탑재된 MCU 식별은 자료에 기록하지만 리비전별 전원 점퍼와 미확인 헤더를 자동으로 연결하지 않는다.

Arduino는 UNO R4 Minima, MKR Zero, Nano RP2040 Connect, Portenta H7, Zero, Leonardo, Nano 33 IoT, MKR WiFi 1010, Due를 추가했다. Nano RP2040 Connect의 공식 End of Life 상태도 표시한다.

## 회로 등록과 계산의 범위

- 신규 제품을 기존 CAD 부품에 붙여도 형상·위치·고정 상태·사용자 색상·그룹·다른 회로 연결은 유지한다. 소비전류가 검증되지 않은 제품은 계산 제외 상태에서 시작한다.
- Nucleo/Arduino/Espressif/Pico/Teensy/BeagleBoard 신규 보드는 제품 등록이 가능하지만 이번 확장만으로 새로운 헤더 핀 지도나 임의 코드 실행을 지원한다고 표시하지 않는다.
- TI/ADI/Bosch IC 자료와 Compute Module 옵션 자료는 참고 전용이다. 완성된 모듈·패키지·핀 지도가 확인되기 전에는 회로 부품으로 자동 승격하지 않는다.
- 액추에이터의 stall 전류와 권장 공급기 전류를 고정 소비전류로 사용하지 않는다. DYNAMIXEL T형은 half-duplex TTL, R형은 RS-485 단자를 보존한다. XL330 DATA는 3.3 V TTL/5 V 호환이고 XC330 DATA는 5 V TTL 자료다. 내부 엔코더가 있다고 A/B 핀을 만들어내지 않는다. XM540의 별도 External Port·Dual Joint 커넥터는 이번 통신 단자 모식도에서 제외한다.
- 퓨즈는 비극성 A/B 양 끝을 가진 닫힌 접점과 문서의 명목 냉간 저항으로 등록한다. 정격 전류 초과를 경고하지만 자동으로 끊어진 것처럼 계산하지 않는다. 실제 시간-전류 곡선·차단 용량·I²t·온도 보정의 동작 검증은 별도다.
- 218 시리즈의 250 V **AC**를 DC 차단 정격으로 사용하지 않는다. 451의 125 V AC/DC, 287의 32 V DC는 확인된 DC 전압 정격에 기록한다. 451의 0.5/0.75/1 A 냉간 저항은 현재 공식 자료의 0.3046/0.1444/0.0780 Ω를 사용한다.
- 저항은 0.125 W 정격을 I²R 손실과 비교한다. 커패시터의 내압을 전압원으로 사용하지 않는다. Bourns 인덕터 RDC는 문서의 **최대** 값이며 실제 온도에서 측정한 값이나 포화 전류가 아니다. 임의의 방열 저항·모터 효율을 자동 설정하지 않는다.

## 공식 자료

각 항목의 원문 링크는 `cadstudio/electrical_catalog_data.py`에 함께 저장한다. 웹 페이지나 데이터시트 파일 전체를 패키지에 복제하지 않고 제품 식별·확인한 수치·짧은 설명만 오프라인으로 제공한다.

- [ST Nucleo 공식 제품 목록](https://www.st.com/en/evaluation-tools/stm32-nucleo-boards/products.html)
- [Arduino UNO R4 Minima 공식 보드 문서](https://docs.arduino.cc/hardware/uno-r4-minima/), [Nano RP2040 Connect 문서](https://docs.arduino.cc/hardware/nano-rp2040-connect/)
- [Espressif ESP32-S3-DevKitC-1 문서](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/index.html)
- [Raspberry Pi Pico 공식 제품 자료](https://www.raspberrypi.com/products/raspberry-pi-pico/), [Teensy 4.1 자료](https://www.pjrc.com/store/teensy41.html), [BeagleBone Black](https://www.beagleboard.org/boards/beaglebone-black)
- [TI 제품 자료 예: DRV8251](https://www.ti.com/product/DRV8251), [ADS1256](https://www.ti.com/product/ADS1256)
- [ADI TMC2130](https://www.analog.com/en/products/tmc2130.html), [TMC5160](https://www.analog.com/en/products/tmc5160.html), [ADXL355](https://www.analog.com/en/products/adxl355.html)
- [Bosch BMI270](https://www.bosch-sensortec.com/en/products/motion-sensors/imus/bmi270), [BME680](https://www.bosch-sensortec.com/en/products/environmental-sensors/gas-sensors/bme680)
- [ROBOTIS XL330-M077](https://emanual.robotis.com/docs/en/dxl/x/xl330-m077/), [XC330-T288](https://emanual.robotis.com/docs/en/dxl/x/xc330-t288/), [XM540-W270](https://emanual.robotis.com/docs/en/dxl/x/xm540-w270/)
- [Littelfuse 218 데이터시트](https://www.littelfuse.com/assetdocs/littelfuse_fuse_218_datasheet.pdf?assetguid=a96d72b7-5296-4815-88b4-98b2f6738874), [451/453 데이터시트](https://www.littelfuse.com/~/media/electronics/datasheets/fuses/littelfuse_fuse_451_453_datasheet.pdf.pdf), [287 ATOF 데이터시트](https://www.littelfuse.com/assetdocs/littelfuse-datasheet-287-atof?assetguid=43dcdce8-8ca2-426f-8998-7e566f048d40)
- [Panasonic ERJ6ENF2200V](https://industrial.panasonic.com/ww/products/pt/general-purpose-chip-resistors/models/ERJ6ENF2200V), [EEUFR1E101B](https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFR1E101B), [Bourns SRR1260 데이터시트](https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf)

## 검증

`tests/test_electronics_catalog2230.py`는 신규 등록 가능 제품 96종의 CAD 부품 등록·파일 재개방·기존 회로 유지, 참고 자료 29종의 잘못된 승격 차단, 퓨즈 29종의 AC/DC·냉간 저항·정격 경고, DYNAMIXEL 9종의 TTL/RS-485 실제 단자와 저장된 연결을 확인한다. 과전류·과전압 상태에서도 퓨즈를 자동으로 개방하지 않는다는 제한을 검사한다. 기존 카탈로그·모터·단자 자료 검사 221개와 등록·AI 기록·전장 안전 회귀 검사 98개를 합쳐 319개 검사를 통과했다. 이는 제품 DB·저장·DC 정격 검사이며 실제 펌웨어 에뮬레이션이나 제조 정격 인증 결과는 아니다.
