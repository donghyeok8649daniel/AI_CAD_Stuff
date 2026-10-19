"""Shared checked opening pipeline for the native worker and CLI acceptance."""
import time
from .native.document import read_project
from .verified_preview_cache import VerifiedPreviewCache
from .kernel import KERNEL_LOCK,preview
from . import preview_quality


def load_project_preview(path,cache_folder,*,progress=lambda text:None,audit=None):
    report={} if audit is None else audit
    progress('프로젝트 파일 · 전체 작업 기록 검증 중…')
    fingerprints=[];tick=time.perf_counter()
    project=read_project(path,fingerprint=fingerprints.append)
    report.update(file_sha256=fingerprints[0],parse_seconds=time.perf_counter()-tick,cache_hit=False)
    cache=VerifiedPreviewCache(cache_folder)
    binding=cache.binding(fingerprints[0],project.design,preview_quality.mode())
    tick=time.perf_counter();cached=cache.get(binding);report['cache_read_seconds']=time.perf_counter()-tick
    if cached is not None:
        resolved,result=cached;project=project.model_copy(update={'design':resolved})
        report['cache_hit']=True
        progress('동일 파일 · 이전 전체 계산 결과 확인 완료')
        return project,result
    tick=time.perf_counter()
    with KERNEL_LOCK:result=preview(project.design,progress=progress)
    report['compute_seconds']=time.perf_counter()-tick
    progress('다음 열기를 위한 검증된 계산 결과 보관 중…')
    tick=time.perf_counter();report['cache_stored']=cache.put(binding,project.design,result)
    report['cache_write_seconds']=time.perf_counter()-tick
    if cache.error:report['cache_error']=cache.error
    return project,result


def remember_saved_preview(path,design,result,cache_folder):
    """A completed save must make its exact new file reusable, too.

    This optional step never changes the success of the already completed
    checked save. Geometry must still attest to the actual saved Design.
    """
    if result is None:return False
    try:
        from hashlib import file_digest
        from .models import Design
        resolved=Design.model_validate(design)
        with open(path,'rb') as stream:sha=file_digest(stream,'sha256').hexdigest()
        cache=VerifiedPreviewCache(cache_folder)
        binding=cache.binding(sha,resolved,preview_quality.mode())
        return cache.put(binding,resolved,result)
    except (OSError,ValueError,KeyError,TypeError,MemoryError):return False
