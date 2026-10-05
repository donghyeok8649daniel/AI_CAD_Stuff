"""Small manufacturer-reference profiles; settings and calibration stay unknown."""
from .measurement_specs import AdcMeasurement, EnvironmentalMeasurement, LoadCellMeasurement

ADS131M04_SOURCE='https://www.ti.com/lit/ds/symlink/ads131m04.pdf'
ADS1232_SOURCE='https://www.ti.com/lit/ds/symlink/ads1232.pdf'
HX711_SOURCE='https://cdn.sparkfun.com/datasheets/Sensors/ForceFlex/hx711_english.pdf'
SHT31_SOURCE='https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf'
SHT45_SOURCE='https://sensirion.com/media/documents/33FD6951/6A7C10A0/HT_DS_Datasheet_SHT4x_V7.3.pdf'
CHECKED_AT='2026-10-06'
HBK_U10M_SOURCE='https://www.hbm.com/fileadmin/mediapool/hbmdoc/technical/B01444.pdf'


def catalog_measurement(catalog_id):
    """Fresh typed reference, with no selected PGA/rate or operating current."""
    common=dict(provenance='manufacturer_reference',source_checked_at=CHECKED_AT)
    if catalog_id=='hbk_u10m_25kn_passive':
        return LoadCellMeasurement(**common,source_url=HBK_U10M_SOURCE,rated_capacity_n=25000,
            sensitivity_nominal_mv_per_v=2,sensitivity_min_mv_per_v=2,sensitivity_max_mv_per_v=2.5,
            excitation_min_v=.5,excitation_max_v=12,bridge_resistance_min_ohm=345,bridge_type='full_bridge',
            load_direction='tension_compression',fatigue_rated=True,fatigue_load_n=25000,
            terminal_roles={'excitation_positive':'port:EXC_POS','excitation_negative':'port:EXC_NEG',
                'signal_positive':'port:SIG_POS','signal_negative':'port:SIG_NEG','sense_positive':'port:SENSE_POS','sense_negative':'port:SENSE_NEG'},
            notes='U10M passive 25 kN, standard 100% dynamic calibration. Nominal 2 mV/V, non-adjusted 2..2.5; serial sensitivity/calibration required. ±100% Fnom dynamic range is not apparatus lifetime; cycle count unknown. 9.2 kHz transducer natural frequency is not system bandwidth. 1-U10M/25kN includes adapter; no-adapter custom code, cable option/pin numbers, installation and proof remain unconfirmed. Reference excitation 5 V is not selected drive voltage.')
    if catalog_id=='ti_ads131m04':
        return AdcMeasurement(**common,source_url=ADS131M04_SOURCE,resolution_bits=24,max_sample_rate_sps=64000,
            simultaneous_channels=4,interface='spi',reference_voltage_v=1.2,reference_mode='internal',
            analog_supply_min_v=2.7,analog_supply_max_v=3.6,digital_supply_min_v=2.7,digital_supply_max_v=3.6,
            terminal_roles={'signal_positive':'port:AIN0P','signal_negative':'port:AIN0N',
                'analog_positive':'port:AVDD','analog_negative':'port:AGND','digital_positive':'port:DVDD','digital_negative':'port:DGND',
                'clock':'port:SCLK','data_out':'port:DOUT','data_in':'port:DIN','chip_select':'port:CS','data_ready':'port:DRDY'},
            notes='Bare IC, not a verified load-cell PCB. 64 kSPS depends on clock/OSR/power mode; actual rate/bandwidth remain unset. Gain ≥8 requires each input ≤AVDD−1.8 V. Bridge excitation, filtering and calibration require review.')
    if catalog_id=='ti_ads1232':
        return AdcMeasurement(**common,source_url=ADS1232_SOURCE,resolution_bits=24,max_sample_rate_sps=80,interface='clock_data',
            reference_mode='unknown',analog_supply_min_v=2.7,analog_supply_max_v=5.3,digital_supply_min_v=2.7,digital_supply_max_v=5.3,
            terminal_roles={'signal_positive':'port:AINP1','signal_negative':'port:AINN1',
                'analog_positive':'port:AVDD','analog_negative':'port:AGND','digital_positive':'port:DVDD','digital_negative':'port:DGND',
                'reference_positive':'port:REFP','reference_negative':'port:REFN','clock':'port:SCLK','data_out':'port:DRDY_DOUT'},
            notes='Bare IC. Selectable 10/80 SPS. Rev H filter bandwidth is 2.4/19 Hz; this is not system or force-control bandwidth. Gain, reference and selected data rate are not assumed.')
    if catalog_id=='avia_hx711':
        return AdcMeasurement(**common,source_url=HX711_SOURCE,resolution_bits=24,max_sample_rate_sps=80,interface='clock_data',
            analog_supply_min_v=2.6,analog_supply_max_v=5.5,digital_supply_min_v=2.6,digital_supply_max_v=5.5,
            terminal_roles={'signal_positive':'port:INA_POS','signal_negative':'port:INA_NEG',
                'analog_positive':'port:AVDD','analog_negative':'port:AGND','digital_positive':'port:DVDD','digital_negative':'port:AGND',
                'clock':'port:PD_SCK','data_out':'port:DOUT'},
            notes='AVIA manufacturer datasheet hosted by SparkFun. Bare SOP-16 IC, not an arbitrary breakout. Internal-clock output 10/80 SPS; no verified usable system bandwidth. No high-frequency force-control approval.')
    if catalog_id=='sensirion_sht31_dis_b':
        return EnvironmentalMeasurement(**common,source_url=SHT31_SOURCE,supply_min_v=2.15,supply_max_v=5.5,
            temperature_min_c=-40,temperature_max_c=125,humidity_min_rh=0,humidity_max_rh=100,interface='i2c',
            terminal_roles={'power_positive':'port:VDD','power_negative':'port:VSS','data':'port:SDA','clock':'port:SCL'},
            notes='SHT31-DIS-B chip reference; addresses 0x44/0x45 depend on ADDR. Heater/mode-dependent current stays unset. A breakout PCB may add pull-ups or a regulator; verify its actual model.')
    if catalog_id=='sensirion_sht45_ad1b':
        return EnvironmentalMeasurement(**common,source_url=SHT45_SOURCE,supply_min_v=1.08,supply_max_v=3.6,
            temperature_min_c=-40,temperature_max_c=125,humidity_min_rh=0,humidity_max_rh=100,interface='i2c',i2c_address=0x44,
            terminal_roles={'power_positive':'port:VDD','power_negative':'port:VSS','data':'port:SDA','clock':'port:SCL'},
            notes='Exact SHT45-AD1B chip reference. Operating current depends on measurement/heater mode and remains unset. No I²C firmware execution or humidity-compensation model.')
    return None
