"""Inert, source-linked product references for any CAD body.

These records describe user-selected products. They neither resize geometry nor
enable an electrical model. Links are stored without opening or downloading
them; the web reference reader has separate, stricter network validation.
"""
from __future__ import annotations

from datetime import date, datetime
from ipaddress import ip_address
import re
from typing import Literal, TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from .models import Design


def validate_product_link(value: str) -> str:
    """Validate a saved public HTTP(S) link without DNS or network access."""
    if not value:
        return value
    if len(value) > 1500 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise ValueError("제품 링크에 공백·제어 문자·역슬래시를 넣을 수 없습니다.")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("올바른 http 또는 https 제품 링크를 입력하세요.") from None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
        raise ValueError("제품 링크는 로그인 정보가 없는 http 또는 https 주소여야 합니다.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("제품 링크의 포트 번호가 올바르지 않습니다.")
    normalized = host.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith((".localhost", ".local", ".internal")):
        raise ValueError("공식·구매 제품 링크에 로컬 컴퓨터 주소를 사용할 수 없습니다.")
    try:
        address = ip_address(normalized)
    except ValueError:
        try:
            ascii_host = normalized.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("제품 링크의 도메인 이름이 올바르지 않습니다.") from None
        labels = ascii_host.split(".")
        if len(ascii_host) > 253 or len(labels) < 2 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            raise ValueError("제품 링크의 공개 도메인 이름이 올바르지 않습니다.")
    else:
        if not address.is_global:
            raise ValueError("공식·구매 제품 링크에 사설·로컬 IP 주소를 사용할 수 없습니다.")
    return value


def _checked_at(value: str) -> str:
    if not value:
        return value
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if "T" not in value or parsed.tzinfo is None:
                raise ValueError
    except ValueError:
        raise ValueError("자료 확인일은 YYYY-MM-DD 또는 시간대가 있는 ISO 날짜·시간을 입력하세요.") from None
    return value


class ProductSource(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    title: str = Field(default="", max_length=200)
    url: str = Field(max_length=1500)
    revision: str = Field(default="", max_length=160)
    checked_at: str = Field(default="", max_length=40)

    @field_validator("url")
    @classmethod
    def checked_url(cls, value):
        if not value:
            raise ValueError("자료 출처의 링크를 입력하세요.")
        return validate_product_link(value)

    @field_validator("checked_at")
    @classmethod
    def checked_date(cls, value):
        return _checked_at(value)


class ProductSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str = Field(min_length=1, max_length=160)
    value: str | float | None = None
    unit: str = Field(default="", max_length=80)
    condition: str = Field(default="", max_length=1000)
    source_url: str = Field(default="", max_length=1500)

    @field_validator("value", mode="before")
    @classmethod
    def bounded_value(cls, value):
        if isinstance(value, bool) or isinstance(value, (list, dict)):
            raise ValueError("제품 사양은 숫자·문자열 또는 미확인 값만 입력하세요.")
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("제품 사양 값은 1000자 이내로 입력하세요.")
        return value

    @field_validator("source_url")
    @classmethod
    def checked_url(cls, value):
        return validate_product_link(value)


class ProductMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(default="", max_length=200)
    manufacturer: str = Field(default="", max_length=160)
    model: str = Field(default="", max_length=160)
    spec_summary: str = Field(default="", max_length=16000)
    official_url: str = Field(default="", max_length=1500)
    datasheet_url: str = Field(default="", max_length=1500)
    purchase_url: str = Field(default="", max_length=1500)
    source_url: str = Field(default="", max_length=1500)
    catalog_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")
    catalog_namespace: Literal["", "electrical", "mechanical"] = ""
    source_checked_at: str = Field(default="", max_length=40)
    provenance: Literal["user", "catalog", "web_reference"] = "user"
    notes: str = Field(default="", max_length=8000)
    specs: list[ProductSpec] = Field(default_factory=list, max_length=64)
    sources: list[ProductSource] = Field(default_factory=list, max_length=16)

    @field_validator("official_url", "datasheet_url", "purchase_url", "source_url")
    @classmethod
    def checked_url(cls, value):
        return validate_product_link(value)

    @field_validator("source_checked_at")
    @classmethod
    def checked_date(cls, value):
        return _checked_at(value)

    @model_validator(mode="after")
    def catalog_reference(self):
        if bool(self.catalog_id) != bool(self.catalog_namespace):
            raise ValueError("제품 목록 ID와 전장/기계 목록 구분을 함께 지정하세요.")
        return self

    def is_empty(self) -> bool:
        return not any((self.name, self.manufacturer, self.model, self.spec_summary,
                        self.official_url, self.datasheet_url, self.purchase_url,
                        self.source_url, self.catalog_id, self.source_checked_at,
                        self.notes, self.specs, self.sources))


def product_from_catalog(namespace: str, catalog_id: str) -> ProductMetadata:
    """Map existing catalogue facts to references, without operating defaults."""
    if namespace == "electrical":
        from .electrical_catalog import get_catalog_entry
        entry = get_catalog_entry(catalog_id)
        if entry is None:
            raise ValueError("등록된 전장 제품을 찾지 못했습니다.")
        facts = []
        for field, label, unit in (
            ("nominal_voltage_v", "목록의 호칭 공급 전압", "V"),
            ("rated_current_a", "목록의 전류 사양", "A"),
            ("resistance_ohm", "저항", "ohm"),
            ("capacitance_f", "정전용량", "F"),
            ("inductance_h", "인덕턴스", "H"),
            ("winding_resistance_ohm", "권선 저항", "ohm"),
            ("rated_voltage_v", "목록의 정격/내전압", "V"),
        ):
            value = getattr(entry, field)
            if value is not None:
                facts.append(ProductSpec(label=label, value=value, unit=unit,
                    condition="제품 목록의 참고값입니다. 실제 동작 조건은 자료를 확인하세요.",
                    source_url=entry.source_url))
        # Summary retains the distinction between supply/stall ratings and
        # operating current. Those values do not become circuit inputs here.
        return ProductMetadata(name=entry.display_name, manufacturer=entry.manufacturer,
                               model=entry.model, spec_summary=entry.spec_summary,
                               source_url=entry.source_url, catalog_id=entry.catalog_id,
                               catalog_namespace="electrical", provenance="catalog",
                               specs=facts,
                               sources=[ProductSource(title=entry.display_name, url=entry.source_url)],
                               notes="제품 목록의 참고 자료입니다. 형상·배선·소비전류는 자동 설정하지 않습니다.")
    if namespace == "mechanical":
        from .mechanical_catalog import get_catalog_entry
        entry = get_catalog_entry(catalog_id)
        if entry is None:
            raise ValueError("등록된 기계 제품·규격 자료를 찾지 못했습니다.")
        facts = [ProductSpec(label=fact.label, value=fact.value, unit=fact.unit,
                             condition=" · ".join(filter(None, (fact.qualifier, fact.condition))),
                             source_url=entry.source_url) for fact in (*entry.ratings, *entry.dimensions)]
        if entry.wire_spec:
            wire = entry.wire_spec
            facts.extend([
                ProductSpec(label="전선 규격", value=wire.awg, unit="AWG", source_url=entry.source_url),
                ProductSpec(label="도체 구성", value=wire.stranding, source_url=entry.source_url),
                ProductSpec(label="명목 DC 저항", value=wire.dcr_ohm_per_1000ft,
                            unit="ohm/1000 ft", source_url=entry.source_url),
                ProductSpec(label="자유공기 참고 전류", value=wire.free_air_current_a,
                            unit="A", condition=wire.free_air_condition, source_url=entry.source_url),
            ])
            if wire.insulation_od_mm is not None:
                facts.append(ProductSpec(label="절연 외경", value=wire.insulation_od_mm,
                                         unit="mm", source_url=entry.source_url))
        return ProductMetadata(name=entry.display_name, manufacturer=entry.manufacturer,
                               model=entry.model, spec_summary=entry.summary,
                               source_url=entry.source_url, catalog_id=entry.catalog_id,
                               catalog_namespace="mechanical", provenance="catalog",
                               specs=facts, sources=[ProductSource(title=source.title, url=source.url,
                                   revision=source.revision, checked_at=source.retrieved_on) for source in entry.sources],
                               source_checked_at=entry.sources[0].retrieved_on,
                               notes="\n".join(entry.notes))
    raise ValueError("제품 목록 구분은 electrical 또는 mechanical이어야 합니다.")


def product_from_reference(record: dict) -> ProductMetadata:
    """Prepare an unverified page excerpt for explicit user confirmation."""
    if not isinstance(record, dict):
        raise ValueError("제품 자료 형식이 올바르지 않습니다.")
    url = record.get("url", "")
    if not url:
        raise ValueError("제품 자료의 출처 링크가 없습니다.")
    # Candidate dimensions are deliberately not assigned to geometry or
    # structured specs: a page may describe shipping/other-SKU dimensions.
    return ProductMetadata(name=record.get("title", ""), source_url=url,
                           spec_summary=record.get("excerpt", ""),
                           source_checked_at=record.get("retrieved_at", ""),
                           provenance="web_reference", notes=record.get("note", ""),
                           sources=[ProductSource(title=record.get("title", ""), url=url,
                                                  checked_at=record.get("retrieved_at", ""))])


def product_for_part(raw: Design | dict, part_id: str) -> ProductMetadata | None:
    """Return independent metadata or the existing electrical registration view."""
    from .models import Design
    design = raw if isinstance(raw, Design) else Design.model_validate(raw)
    part = next((part for part in design.parts if part.id == part_id), None)
    if part is None:
        raise ValueError("제품 자료를 표시할 CAD 부품을 찾지 못했습니다.")
    if part.product is not None:
        return part.product.model_copy(deep=True)
    matches=[component for component in (design.electrical.components if design.electrical else ())
             if component.part_id==part_id]
    if len(matches)>1:
        return ProductMetadata(name=part.name,notes='Multiple circuit registrations refer to this body; no single catalog product inferred.')
    registered=matches[0] if matches else None
    if registered and registered.catalog_id:
        from .electrical_catalog import get_catalog_entry
        if get_catalog_entry(registered.catalog_id):
            return product_from_catalog("electrical", registered.catalog_id)
    if registered and registered.source_url:
        try:return ProductMetadata(name=registered.name, source_url=registered.source_url)
        except ValueError:
            # Legacy circuit source strings were not guaranteed public URLs.
            # Keep their saved data intact without turning them into links.
            return ProductMetadata(name=registered.name)
    if registered:return ProductMetadata(name=registered.name)
    return None


def set_part_product(raw: Design | dict, part_id: str,
                     product: ProductMetadata | dict | None) -> Design:
    """Change only the selected body's reference metadata transactionally."""
    from .models import Design
    design = raw if isinstance(raw, Design) else Design.model_validate(raw)
    data = design.model_dump()
    part = next((part for part in data["parts"] if part["id"] == part_id), None)
    if part is None:
        raise ValueError("제품 자료를 지정할 CAD 부품을 먼저 선택하세요.")
    checked = product if isinstance(product, ProductMetadata) else ProductMetadata.model_validate(product) if product is not None else None
    if checked is None or checked.is_empty():
        part.pop("product", None)
    else:
        from .electrical_registration import registration_for_part
        registered = registration_for_part(design, part_id)
        if (registered and registered.catalog_id and checked.catalog_id
                and (checked.catalog_namespace != "electrical" or checked.catalog_id != registered.catalog_id)):
            raise ValueError("이미 등록된 전장 제품과 다른 목록 항목입니다. 전장 등록을 먼저 명시적으로 변경하세요.")
        part["product"] = checked.model_dump()
    return Design.model_validate(data)
