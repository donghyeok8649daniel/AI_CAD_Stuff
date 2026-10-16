"""Separate cancellable kernel queuing from bounded playback inspection.

This clock does not relax collision, pose, sample or local geometry gates.
Native geometry calls finish before the next cooperative checkpoint.
"""
from contextlib import contextmanager
from math import isfinite
import time


class MotionInspectionTimeout(ValueError):
    def __init__(self,message,report):
        super().__init__(message);self.report=report


class MotionInspectionBudget:
    def __init__(self,seconds,check,progress,wait_seconds=120.,clock=None,segmented=False):
        if type(seconds) not in (int,float) or not isfinite(seconds) or not .01<=seconds<=300:
            raise ValueError('검사 시간 범위를 확인하세요.')
        if type(wait_seconds) not in (int,float) or not isfinite(wait_seconds) or not .01<=wait_seconds<=120:
            raise ValueError('형상 엔진 대기 시간 범위를 확인하세요.')
        if type(segmented) is not bool:raise ValueError('분할 검사 설정을 확인하세요.')
        self.seconds=seconds;self.wait_seconds=wait_seconds;self.check=check;self.progress=progress;self.segmented=segmented
        self.clock=clock or time.monotonic;self.started=self.clock();self.active_started=None
        self.stage='kernel_wait';self.stage_started=self.started;self.phases={}
        self.wait_elapsed=0.;self.sample=0;self.samples=None;self.last_progress=None;self.done=False
        self.slice_started=None;self.slices=[];self.checkpoints=0

    def snapshot(self):
        now=self.clock();phases=dict(self.phases)
        if self.active_started is not None and not self.done:
            phases[self.stage]=phases.get(self.stage,0.)+now-self.stage_started
        return dict(stage=self.stage,queue_seconds=self.wait_elapsed if self.active_started is not None else now-self.started,
                    active_seconds=0. if self.active_started is None else now-self.active_started,
                    active_budget_seconds=self.seconds,queue_budget_seconds=self.wait_seconds,
                    budget_scope='completed_work_slices' if self.segmented else 'whole_inspection',
                    slice_active_seconds=0. if self.slice_started is None else now-self.slice_started,
                    completed_slices=len(self.slices),completed_slice_seconds=list(self.slices),checkpoints=self.checkpoints,
                    phase_seconds=phases,sample=self.sample,samples=self.samples,
                    cancellation_scope='cooperative_between_native_geometry_calls')

    def notify(self,force=False):
        now=self.clock()
        if force or self.last_progress is None or now-self.last_progress>=.5:
            self.last_progress=now;self.progress(self.snapshot())

    @contextmanager
    def locked(self,lock):
        self.notify(True)
        acquired=False
        try:
            while not acquired:
                self.check()
                remaining=self.wait_seconds-(self.clock()-self.started)
                if remaining<=0:
                    raise MotionInspectionTimeout('형상 엔진 대기 시간이 길어 검사를 시작하지 못했습니다. 다른 형상 작업이 끝난 뒤 다시 검사하세요. 원본은 유지됩니다.',self.snapshot())
                acquired=lock.acquire(timeout=min(.1,remaining))
                if not acquired:self.notify()
            self.wait_elapsed=self.clock()-self.started
            self.active_started=self.clock();self.stage='starting';self.stage_started=self.active_started
            self.slice_started=self.active_started
            self.check();self.notify(True)
            yield self
        finally:
            if acquired:lock.release()

    def phase(self,name,*,sample=None,samples=None):
        now=self.clock()
        if self.active_started is not None and not self.done:
            self.phases[self.stage]=self.phases.get(self.stage,0.)+now-self.stage_started
        self.stage=name;self.stage_started=now
        if sample is not None:self.sample=sample
        if samples is not None:self.samples=samples
        self.notify()

    def guard(self):
        self.check()
        origin=self.slice_started if self.segmented else self.active_started
        if origin is not None and self.clock()-origin>self.seconds:
            raise MotionInspectionTimeout('표본 구동 검사 시간 한도입니다. 검사 기록에서 지연 단계를 확인하세요. 구동 범위를 나누어 다시 검사할 수 있습니다. 원본은 유지됩니다.',self.snapshot())
        self.notify()

    def checkpoint(self):
        """Commit completed finite work, never grant clearance to a partial job.

        Only the opt-in UI workflow splits long finite inspections. Direct API
        calls retain the whole-inspection deadline. Each slice has the original
        time budget; one native operation can still overrun before this guard.
        """
        self.guard();self.checkpoints+=1
        now=self.clock()
        if self.segmented and self.slice_started is not None and now-self.slice_started>=min(2.,self.seconds/4):
            self.slices.append(now-self.slice_started);self.slice_started=now;self.notify(True)

    def finish(self):
        self.phase('complete');self.done=True;self.notify(True)
        return self.snapshot()
