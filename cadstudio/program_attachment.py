"""Portable, bounded source attachments; uploaded code is data, never executed."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SOURCE_BYTES = 256 * 1024
ProgramLanguage = Literal['arduino', 'raspberry_python', 'stm32_hal']


class ProgramAttachment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=160)
    language: ProgramLanguage
    source: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    board_component_id: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')

    @model_validator(mode='after')
    def validate_source(self):
        raw = self.source.encode('utf-8')
        if len(raw) > MAX_SOURCE_BYTES or '\x00' in self.source:
            raise ValueError('프로그램은 NUL 없는 UTF-8 텍스트 256 KiB 이내로 첨부하세요.')
        if sha256(raw).hexdigest() != self.sha256:
            raise ValueError('첨부 프로그램의 SHA-256과 내용이 일치하지 않습니다.')
        if Path(self.name).name != self.name or any(ord(c) < 32 for c in self.name):
            raise ValueError('프로그램 이름에는 파일명만 저장하세요.')
        return self


def attach_source(name: str, source: str, *, board_component_id: str = '') -> ProgramAttachment:
    """Detect supported source family without importing or executing the file."""
    suffix = Path(name).suffix.lower()
    if suffix == '.py':
        language = 'raspberry_python'
    elif suffix == '.ino':
        language = 'arduino'
    elif suffix in ('.c', '.cpp', '.h') and 'HAL_GPIO_' in source:
        language = 'stm32_hal'
    elif suffix in ('.c', '.cpp') and ('digitalWrite' in source or 'analogWrite' in source):
        language = 'arduino'
    else:
        raise ValueError('지원 소스: Arduino .ino, Raspberry Pi GPIO .py, STM32 HAL GPIO .c/.cpp. ELF/HEX/운영체제는 실행하지 않습니다.')
    return ProgramAttachment(name=Path(name).name, language=language, source=source,
        sha256=sha256(source.encode('utf-8')).hexdigest(), board_component_id=board_component_id)


def read_program(path: str | Path, *, board_component_id: str = '') -> ProgramAttachment:
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('첨부 프로그램은 최대 256 KiB입니다.')
    try:
        source = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('프로그램을 UTF-8 소스 파일로 저장하세요. 바이너리는 실행하지 않습니다.') from exc
    return attach_source(path.name, source, board_component_id=board_component_id)
