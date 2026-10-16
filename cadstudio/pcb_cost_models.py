"""Persisted, explicitly entered PCB costs; estimates are never vendor offers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

Money = Annotated[Decimal, Field(ge=0, le=1000000000000, decimal_places=6)]
Currency = Annotated[str, Field(pattern=r'^[A-Z]{3}$')]
Ref = Annotated[str, Field(min_length=1, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')]
ADDITIONAL_COSTS = ('pcb_fabrication','assembly_consumables','shipping','tax_import')


def _safe(value):
    if isinstance(value, Decimal):return str(value)
    if isinstance(value, date):return value.isoformat()
    if isinstance(value, dict):return {key:_safe(item) for key,item in value.items()}
    if isinstance(value, list):return [_safe(item) for item in value]
    return value


class CostModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,revalidate_instances='always')

    @model_serializer(mode='wrap')
    def json_safe(self,handler):return _safe(handler(self))

    @model_validator(mode='after')
    def source_and_date(self):
        source=getattr(self,'source_url','')
        if source:
            url=urlsplit(source)
            if url.scheme!='https' or not url.hostname or url.username or url.password or any(c.isspace() or ord(c)<32 for c in source):
                raise ValueError('Cost sources must be HTTPS URLs without credentials.')
        when=getattr(self,'as_of',None)
        if when is not None and not 1900<=when.year<=2100:raise ValueError('Cost date must be within 1900–2100.')
        return self


class CostPriceTier(CostModel):
    minimum_quantity: int = Field(ge=1,le=1000000,strict=True)
    unit_price: Annotated[Decimal,Field(ge=0,le=1000000000,decimal_places=6)]
    currency: Currency = 'KRW'
    status: Literal['reference','quoted'] = 'reference'
    as_of: date
    supplier: str = Field(min_length=1,max_length=120)
    source_url: str = Field(min_length=1,max_length=500)
    note: str = Field(default='',max_length=1000)

    @model_validator(mode='after')
    def provenance(self):
        if not self.supplier.strip():raise ValueError('Price tiers need an entered supplier and source.')
        return self


class CostRange(CostModel):
    minimum: Money
    maximum: Money
    currency: Currency = 'KRW'
    status: Literal['reference','quoted','user_estimate'] = 'user_estimate'
    as_of: date | None = None
    source_url: str = Field(default='',max_length=500)
    basis: str = Field(default='',max_length=1500)

    @model_validator(mode='after')
    def provenance(self):
        if self.minimum>self.maximum:raise ValueError('Cost range minimum exceeds maximum.')
        if not self.source_url and not self.basis.strip():raise ValueError('Cost ranges need a source or explicit estimate basis.')
        if self.status=='quoted' and (not self.as_of or not self.source_url):raise ValueError('Quoted ranges need a dated source.')
        return self


class CostAIRangeRow(CostModel):
    refs: list[Ref] = Field(min_length=1,max_length=64)
    mpn: str = Field(default='',max_length=120)
    required_quantity: int = Field(ge=1,le=100000000,strict=True)
    purchase_quantity: int = Field(ge=1,le=100000000,strict=True)
    minimum_unit_price: Money
    maximum_unit_price: Money
    currency: Currency
    as_of: date | None = None
    source_url: str = Field(default='',max_length=500)
    basis: str = Field(default='',max_length=1500)
    status: Literal['ai_estimate'] = 'ai_estimate'

    @model_validator(mode='after')
    def estimate_only(self):
        if len(set(self.refs))!=len(self.refs):raise ValueError('Duplicate estimate reference.')
        if self.minimum_unit_price>self.maximum_unit_price:raise ValueError('Estimate minimum exceeds maximum.')
        if self.purchase_quantity<self.required_quantity:raise ValueError('Purchase quantity cannot be below required quantity.')
        if not self.source_url and not self.basis.strip():raise ValueError('AI ranges need an explicit source or estimate basis.')
        return self


class CostTierBinding(CostModel):
    kind: Literal['ref'] = 'ref'
    ref: Ref
    purchase_identity_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class PCBCostInputs(CostModel):
    quantity_breaks: dict[Annotated[str,Field(min_length=1,max_length=120)],list[CostPriceTier]] = Field(default_factory=dict,max_length=128)
    quantity_break_bindings: dict[Annotated[str,Field(min_length=1,max_length=120)],CostTierBinding] = Field(default_factory=dict,max_length=128)
    additional_costs: dict[Literal['pcb_fabrication','assembly_consumables','shipping','tax_import'],CostRange] = Field(default_factory=dict,max_length=4)
    accepted_ai_estimates: list[CostAIRangeRow] = Field(default_factory=list,max_length=128)
    accepted_ai_bindings: dict[Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')],
        Annotated[dict[Ref,Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]],Field(min_length=1,max_length=64)]] = Field(default_factory=dict,max_length=128)

    @model_serializer(mode='wrap')
    def compatible_bindings(self,handler):
        data=_safe(handler(self))
        if not self.quantity_break_bindings:data.pop('quantity_break_bindings',None)
        if not self.accepted_ai_bindings:data.pop('accepted_ai_bindings',None)
        return data

    @model_validator(mode='after')
    def bounded_schedules(self):
        if sum(len(rows) for rows in self.quantity_breaks.values())>1024:raise ValueError('Too many saved price tiers.')
        for key,rows in self.quantity_breaks.items():
            if not key.strip() or not 1<=len(rows)<=128 or len({row.minimum_quantity for row in rows})!=len(rows):
                raise ValueError('Price schedules need a ref/MPN key and unique quantity thresholds.')
        seen=set()
        for row in self.accepted_ai_estimates:
            key=(tuple(sorted(row.refs)),row.mpn)
            if key in seen:raise ValueError('Duplicate accepted AI estimate BOM row.')
            seen.add(key)
        return self


class CostAIProposal(CostModel):
    schema_version: Literal[1]
    base_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    rows: list[CostAIRangeRow] = Field(default_factory=list,max_length=128)
    summary: str = Field(default='',max_length=2500)
    status: Literal['ai_estimate'] = 'ai_estimate'

    @model_validator(mode='before')
    @classmethod
    def exact_schema_version(cls,value):
        version=value.get('schema_version') if isinstance(value,dict) else getattr(value,'schema_version',None)
        if type(version) is not int or version!=1:raise ValueError('Cost proposal schema_version must be the explicit integer 1.')
        return value

    @model_validator(mode='after')
    def unique_rows(self):
        if not self.rows and not self.summary.strip():raise ValueError('An unknown-price response needs a summary of the missing pricing basis.')
        keys=[(tuple(sorted(row.refs)),row.mpn) for row in self.rows]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate proposed estimate BOM row.')
        return self
