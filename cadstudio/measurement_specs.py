"""Typed, user-reviewable measurement references; no hardware or firmware I/O."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class MeasurementModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ForceCalibration(MeasurementModel):
    status: Literal['uncalibrated','user_calibrated','certificate_reference'] = 'uncalibrated'
    zero_offset_counts: float | None = None
    scale_n_per_count: float | None = None
    calibrated_at: date | None = None
    certificate_reference: str = Field(default='', max_length=300)
    notes: str = Field(default='', max_length=1200)
    point_count: int = Field(default=0, ge=0, le=10000)
    rms_residual_n: float | None = Field(default=None, ge=0)

    @field_serializer('calibrated_at')
    def serialize_calibrated_at(self, value):
        # Document history accepts JSON scalars even in Python-mode dumps.
        return value.isoformat() if value is not None else None

    @model_validator(mode='after')
    def valid_scale(self):
        if self.scale_n_per_count == 0:
            raise ValueError('Force calibration scale must be non-zero in N/count.')
        if self.status!='uncalibrated' and (self.zero_offset_counts is None or self.scale_n_per_count is None):
            raise ValueError('A declared calibration requires its zero offset and N/count scale.')
        if self.status=='certificate_reference' and not self.certificate_reference:
            raise ValueError('Enter the certificate reference; the application does not certify it.')
        return self


class MeasurementReference(MeasurementModel):
    source_url: str = Field(default='', max_length=500)
    source_checked_at: date | None = None
    provenance: Literal['user_entered','manufacturer_reference'] = 'user_entered'
    notes: str = Field(default='', max_length=1600)
    # Names are functional roles, values are saved schematic terminal keys.
    # A manual terminal map is an explicit declaration, not an official pinout.
    terminal_roles: dict[str,str] = Field(default_factory=dict, max_length=24)

    @field_serializer('source_checked_at')
    def serialize_source_checked_at(self, value):
        return value.isoformat() if value is not None else None

    @model_validator(mode='after')
    def safe_reference(self):
        if self.source_url:
            url=urlsplit(self.source_url)
            if url.scheme!='https' or not url.hostname or url.username or url.password or any(c.isspace() or ord(c)<32 for c in self.source_url):
                raise ValueError('Measurement source must be a safe HTTPS URL.')
        for role,terminal in self.terminal_roles.items():
            if not role or len(role)>40 or not role.isascii() or not all(c.isalnum() or c=='_' for c in role):
                raise ValueError('Use ASCII role keys for measurement terminals.')
            prefix,separator,key=terminal.partition(':')
            if terminal not in ('a','b') and (not separator or prefix not in ('port','pin','supply') or not key or len(key)>40 or not key.isascii() or not all(c.isalnum() or c in '_-' for c in key)):
                raise ValueError('Use an actual a/b, port, GPIO or supply terminal key.')
        return self


class LoadCellMeasurement(MeasurementReference):
    role: Literal['load_cell'] = 'load_cell'
    rated_capacity_n: float | None = Field(default=None, gt=0, le=1e9)
    sensitivity_mv_per_v: float | None = Field(default=None, gt=0, le=1000)
    sensitivity_nominal_mv_per_v: float | None = Field(default=None, gt=0, le=1000)
    sensitivity_min_mv_per_v: float | None = Field(default=None, gt=0, le=1000)
    sensitivity_max_mv_per_v: float | None = Field(default=None, gt=0, le=1000)
    excitation_voltage_v: float | None = Field(default=None, gt=0, le=1000)
    excitation_min_v: float | None = Field(default=None, gt=0, le=1000)
    excitation_max_v: float | None = Field(default=None, gt=0, le=1000)
    bridge_resistance_ohm: float | None = Field(default=None, gt=0, le=1e9)
    bridge_resistance_min_ohm: float | None = Field(default=None, gt=0, le=1e9)
    bridge_type: Literal['unknown','full_bridge'] = 'unknown'
    output_common_mode_v: float | None = None
    dynamic_bandwidth_hz: float | None = Field(default=None, gt=0, le=1e7)
    load_direction: Literal['unknown','tension','compression','tension_compression'] = 'unknown'
    # Cycle qualification is a separate manufacturer specification, never
    # inferred from ultimate capacity, safe overload or one static test.
    fatigue_rated: bool | None = None
    fatigue_cycles: int | None = Field(default=None, gt=0)
    fatigue_load_n: float | None = Field(default=None, gt=0, le=1e9)
    calibration: ForceCalibration = Field(default_factory=ForceCalibration)

    @model_validator(mode='after')
    def ordered_excitation(self):
        if self.excitation_min_v is not None and self.excitation_max_v is not None and self.excitation_min_v>self.excitation_max_v:
            raise ValueError('Load-cell excitation minimum exceeds maximum.')
        if self.sensitivity_min_mv_per_v is not None and self.sensitivity_max_mv_per_v is not None and self.sensitivity_min_mv_per_v>self.sensitivity_max_mv_per_v:
            raise ValueError('Load-cell sensitivity minimum exceeds maximum.')
        return self


class AdcMeasurement(MeasurementReference):
    role: Literal['adc'] = 'adc'
    resolution_bits: int | None = Field(default=None, ge=1, le=32)
    gain: float | None = Field(default=None, ge=1, le=10000)
    sample_rate_sps: float | None = Field(default=None, gt=0, le=1e7)
    max_sample_rate_sps: float | None = Field(default=None, gt=0, le=1e7)
    usable_bandwidth_hz: float | None = Field(default=None, gt=0, le=1e7)
    bandwidth_basis: Literal['unknown','datasheet_filter','measured_system'] = 'unknown'
    filter_mode: str = Field(default='', max_length=80)
    settling_time_ms: float | None = Field(default=None, ge=0, le=1e9)
    reference_voltage_v: float | None = Field(default=None, gt=0, le=1000)
    input_full_scale_mv: float | None = Field(default=None, gt=0, le=1e6)
    analog_supply_voltage_v: float | None = Field(default=None, gt=0, le=1000)
    digital_supply_voltage_v: float | None = Field(default=None, gt=0, le=1000)
    analog_supply_min_v: float | None = Field(default=None, gt=0, le=1000)
    analog_supply_max_v: float | None = Field(default=None, gt=0, le=1000)
    digital_supply_min_v: float | None = Field(default=None, gt=0, le=1000)
    digital_supply_max_v: float | None = Field(default=None, gt=0, le=1000)
    input_common_mode_min_v: float | None = None
    input_common_mode_max_v: float | None = None
    reference_mode: Literal['unknown','internal','external_ratiometric','external_fixed'] = 'unknown'
    interface: Literal['unknown','spi','i2c','clock_data'] = 'unknown'
    simultaneous_channels: int | None = Field(default=None, ge=1, le=64)
    clock_frequency_hz: float | None = Field(default=None, gt=0, le=1e9)
    oversampling_ratio: int | None = Field(default=None, ge=1, le=1000000)
    power_mode: Literal['unknown','high_resolution','low_power','very_low_power'] = 'unknown'
    turbo_mode: bool | None = None
    excitation_sense_divider_ratio: float | None = Field(default=None,gt=0,le=1)
    excitation_sense_gain: float | None = Field(default=None,ge=1,le=128)

    @model_validator(mode='after')
    def ordered_ranges(self):
        for minimum,maximum in (('analog_supply_min_v','analog_supply_max_v'),('digital_supply_min_v','digital_supply_max_v'),('input_common_mode_min_v','input_common_mode_max_v')):
            if getattr(self,minimum) is not None and getattr(self,maximum) is not None and getattr(self,minimum)>getattr(self,maximum):raise ValueError('ADC range minimum exceeds maximum: '+minimum)
        return self


class EnvironmentalMeasurement(MeasurementReference):
    role: Literal['humidity_temperature'] = 'humidity_temperature'
    supply_min_v: float | None = Field(default=None, gt=0, le=1000)
    supply_max_v: float | None = Field(default=None, gt=0, le=1000)
    temperature_min_c: float | None = Field(default=None, ge=-273.15, le=1000)
    temperature_max_c: float | None = Field(default=None, ge=-273.15, le=1000)
    humidity_min_rh: float | None = Field(default=None, ge=0, le=100)
    humidity_max_rh: float | None = Field(default=None, ge=0, le=100)
    interface: Literal['i2c','spi','analog','unknown'] = 'unknown'
    i2c_address: int | None = Field(default=None, ge=8, le=119)
    response_time_s: float | None = Field(default=None, gt=0, le=1e7)

    @model_validator(mode='after')
    def ordered_ranges(self):
        for minimum,maximum in (('supply_min_v','supply_max_v'),('temperature_min_c','temperature_max_c'),('humidity_min_rh','humidity_max_rh')):
            if getattr(self,minimum) is not None and getattr(self,maximum) is not None and getattr(self,minimum)>getattr(self,maximum):raise ValueError('Sensor range minimum exceeds maximum: '+minimum)
        return self


MeasurementSpec = Annotated[LoadCellMeasurement | AdcMeasurement | EnvironmentalMeasurement, Field(discriminator='role')]


class ForceChainSpec(MeasurementModel):
    source_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    load_cell_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    adc_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    controller_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    external_clock_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')
    external_clock_terminal: str = Field(default='',max_length=48)
    environment_ids: list[str] = Field(default_factory=list, max_length=16)
    target_frequency_hz: float | None = Field(default=None, gt=0, le=1e6)
    target_peak_force_n: float | None = Field(default=None, gt=0, le=1e9)
    samples_per_cycle_required: float = Field(default=20, ge=2, le=10000)
    purpose: Literal['acquisition_only','force_feedback'] = 'acquisition_only'
    # Explicit host pin choices. Example: {'clock':'pin:PA5',
    # 'data_out':'pin:PA6'} means the ADC output enters host PA6.
    controller_terminals: dict[str,str] = Field(default_factory=dict, max_length=12)

    @model_validator(mode='after')
    def valid_pin_choices(self):
        MeasurementReference(terminal_roles=self.controller_terminals)
        if self.external_clock_terminal:MeasurementReference(terminal_roles={'external_clock':self.external_clock_terminal})
        if len(set(self.environment_ids))!=len(self.environment_ids) or any(not key or len(key)>40 or not key.isascii() or not all(c.isalnum() or c in '_-' for c in key) for key in self.environment_ids):
            raise ValueError('Environmental component IDs must be unique ASCII identifiers.')
        return self

