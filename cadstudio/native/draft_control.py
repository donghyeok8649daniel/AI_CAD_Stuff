"""Provider cancellation and deadlines, independent of CAD/kernel imports."""
import asyncio
from copy import deepcopy
import threading


class DraftCancelled(Exception):
    pass


class DraftControl:
    """Cancel blocked network reads and retain only complete CAD checkpoints."""
    def __init__(self):
        self.cancelled=threading.Event();self.lock=threading.Lock();self.loop=None;self.task=None;self.retained=None;self.timer=None;self.network_paused=False;self.remaining=None
    def keep_draft(self,response,verified):
        checkpoint=dict(response=deepcopy(response),preview=verified)
        with self.lock:
            if not self.cancelled.is_set():self.retained=checkpoint
    def checkpoint(self):
        with self.lock:return self.retained
    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.loop and not self.loop.is_closed():self.loop.call_soon_threadsafe(self.task.cancel)
    def check(self):
        if self.cancelled.is_set():raise DraftCancelled('설계 초안 생성을 취소했습니다.')
    def network_wait(self,waiting):
        """Offline waiting pauses the worker's active deadline."""
        if waiting==self.network_paused:return
        self.network_paused=waiting
        if not self.timer:return
        loop=asyncio.get_running_loop()
        if waiting:
            when=self.timer.when();self.remaining=None if when is None else max(.001,when-loop.time());self.timer.reschedule(None)
        elif self.remaining is not None:self.timer.reschedule(loop.time()+self.remaining);self.remaining=None
    async def execute(self,fn,deadline,timeout_message=None):
        self.check()
        with self.lock:self.loop=asyncio.get_running_loop();self.task=asyncio.current_task()
        try:
            self.check()
            async with asyncio.timeout(deadline) as timer:
                self.timer=timer
                return await fn()
        except asyncio.CancelledError:raise DraftCancelled('설계 초안 생성을 취소했습니다.') from None
        except asyncio.TimeoutError:raise ValueError(timeout_message or '로컬 AI가 제한 시간 안에 완료하지 못했습니다. 부품 하나와 치수부터 요청하거나 더 작은 모델을 선택하세요.') from None
        finally:
            with self.lock:self.loop=None;self.task=None;self.timer=None;self.network_paused=False;self.remaining=None
