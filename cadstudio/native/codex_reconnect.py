"""Retry only transient transport failures, retaining caller messages and CAD checkpoints."""
import asyncio
import random


class ConnectionInterrupted(ValueError):
    pass


def classified_error(error):
    from .codex_connection import safe_error
    # Only structured transport types or well-known network phrases are retryable.
    # Authentication/quota/bad-request status always overrides transport wrappers.
    import json
    text=json.dumps(error,ensure_ascii=True).lower()
    def statuses(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in ('httpstatuscode','status_code') and isinstance(item,int):yield item
                yield from statuses(item)
        elif isinstance(value,list):
            for item in value:yield from statuses(item)
    codes=list(statuses(error))
    permanent=any(c in (400,401,403,404,409,422,429) for c in codes) or any(s in text for s in ('usagelimit','usage_limit','rate_limit','ratelimit','quota','credits','limit reached','unauthorized','authentication','token expired','401','sign in','not logged','contextwindowexceeded','badrequest','invalid params','unsupported'))
    transient=any(s in text for s in ('httpconnectionfailed','responsestreamconnectionfailed','responsestreamdisconnected','responsetoomanyfailedattempts','internalservererror','connection reset','connection refused','network is unreachable','dns error','error sending request','stream disconnected','connection closed','timed out','temporarily unavailable')) or any(c>=500 or c in (408,425) for c in codes)
    if transient and not permanent:return ConnectionInterrupted('Codex 통신이 일시적으로 끊겼습니다. 연결 복구를 기다립니다.')
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
    async def invoke(self,method,*args):
        attempt=0
        while True:
            self.control.check()
            try:
                if self.session is None:
                    session=self.factory(self.executable)
                    # Enter failures clean up via the concrete session implementation.
                    await session.__aenter__();self.session=session
                if self.control.network_paused:
                    # Probe local authentication/catalog first; content still retries safely
                    # if upstream network remains unavailable. No CAD state is applied here.
                    await self.session.account()
                self.control.network_wait(False)
                result=await getattr(self.session,method)(*args)
                if attempt:self.progress('Codex 연결 복구 · 중단된 작업 단계를 이어갑니다.')
                self.control.network_wait(False)
                return result
            except (ConnectionInterrupted,ConnectionError,asyncio.TimeoutError):
                self.control.check();self.control.network_wait(True)
                await self.close();attempt+=1
                delay=min(30,5*2**min(attempt-1,3))+random.uniform(0,.5)
                self.progress(f'Codex 연결 대기 · {delay:.0f}초 후 재시도 · 취소 가능 ({attempt})')
                await self.sleep(delay)
    async def account(self):return await self.invoke('account')
    async def models(self):return await self.invoke('models')
    async def content(self,*args):return await self.invoke('content',*args)
