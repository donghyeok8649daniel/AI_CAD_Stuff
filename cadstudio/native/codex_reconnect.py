"""Retry only transient transport failures, retaining caller messages and CAD checkpoints."""
import asyncio
import random


class ConnectionInterrupted(ValueError):
    pass


def classified_error(error):
    from .codex_errors import safe_error, error_details
    if error_details(error)['category'] == 'network':return ConnectionInterrupted(safe_error(error))
    return ValueError(safe_error(error))


class RecoveringSession:
    def __init__(self,factory,executable,control,progress,*,sleep=asyncio.sleep):
        self.factory=factory;self.executable=executable;self.control=control;self.progress=progress;self.sleep=sleep;self.session=None
    async def __aenter__(self):return self
    async def close(self):
        session,self.session=self.session,None
        if session:await session.__aexit__(None,None,None)
    async def __aexit__(self,*args):
        try:await self.close()
        finally:self.control.network_wait(False)
    async def invoke(self,method,*args,**kwargs):
        attempt=0
        while True:
            self.control.check()
            try:
                if self.session is None:
                    session=self.factory(self.executable)
                    # Enter failures clean up via the concrete session implementation.
                    await session.__aenter__();self.session=session
                    if hasattr(session, 'network_wait'): session.network_wait=self.control.network_wait
                if self.control.network_paused:
                    # Probe local authentication/catalog first; content still retries safely
                    # if upstream network remains unavailable. No CAD state is applied here.
                    await self.session.account()
                self.control.network_wait(False)
                result=await getattr(self.session,method)(*args,**kwargs)
                if attempt:self.progress('Codex 연결 복구 · 중단된 작업 단계를 이어갑니다.')
                self.control.network_wait(False)
                return result
            except (ConnectionInterrupted,ConnectionError,asyncio.TimeoutError):
                self.control.check();self.control.network_wait(True)
                # Upstream service failures need not restart a healthy local
                # app-server. EOF/send failures recreate only our owned process.
                if not getattr(self.session, 'alive', False): await self.close()
                attempt+=1
                delay=min(30,5*2**min(attempt-1,3))+random.uniform(0,.5)
                self.progress(f'Codex 연결 대기 · {delay:.0f}초 후 재시도 · 취소 가능 ({attempt})')
                await self.sleep(delay)
    async def account(self):return await self.invoke('account')
    async def models(self):return await self.invoke('models')
    async def content(self,*args,**kwargs):return await self.invoke('content',*args,**kwargs)
