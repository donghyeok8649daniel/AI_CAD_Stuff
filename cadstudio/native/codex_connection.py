"""Official Codex app-server, private stdio, ChatGPT sign-in only.

The CAD owns this child process and reuses Codex's official login store. It never reads
OAuth tokens, controls another Codex window, or falls back to an API key.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

from .local_ai import DraftControl
from .. import __version__

INSTALL_URL = 'https://learn.chatgpt.com/docs/codex/cli'
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')


def data_root():
    return Path(os.getenv('CADSTUDIO_DATA_DIR', str(Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'PromptCADStudio')))


def settings():
    try:
        value = json.loads((data_root() / 'codex-settings.json').read_text(encoding='utf-8'))
        return {key: str(value.get(key, '')) for key in ('executable', 'model')}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'executable': '', 'model': ''}


def save_settings(executable, model):
    root = data_root(); root.mkdir(parents=True, exist_ok=True)
    target = root / 'codex-settings.json'; temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(executable=executable, model=model)), encoding='utf-8')
    os.replace(temp, target)


def find_executable(explicit=''):
    """Resolve native binaries; never execute a shell or interpolate a command."""
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.is_file() and (os.name != 'nt' or candidate.suffix.lower() == '.exe'):
            return str(candidate.resolve())
        raise ValueError('Codex 실행 파일을 찾지 못했습니다. codex.exe 경로를 다시 선택하세요.')
    candidates = []
    found = shutil.which('codex')
    if found: candidates.append(Path(found))
    npm = Path(os.getenv('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'npm'
    roots = [npm, *(p.parent for p in candidates)]
    for root in roots:
        for arch in ('x64', 'arm64'):
            target = 'x86_64' if arch == 'x64' else 'aarch64'
            base = root / 'node_modules/@openai/codex'
            candidates.append(base / f'node_modules/@openai/codex-win32-{arch}/vendor/{target}-pc-windows-msvc/bin/codex.exe')
            candidates.append(base / f'vendor/{target}-pc-windows-msvc/codex/codex.exe')
    for candidate in candidates:
        if candidate.is_file() and (os.name != 'nt' or candidate.suffix.lower() == '.exe'):
            return str(candidate.resolve())
    raise ValueError('Codex CLI가 필요합니다. 연결 창의 설치 안내를 따라 설치하거나 codex.exe를 선택하세요.')


def login_url(value):
    url = urlsplit(value)
    if url.scheme != 'https' or url.hostname not in ('auth.openai.com', 'chatgpt.com') or url.username or url.password or url.port not in (None, 443):
        raise ValueError('Codex가 공식 로그인 주소를 반환하지 않았습니다. CLI를 업데이트하세요.')
    return value


def safe_error(error):
    """Classify without displaying server prose, headers, tokens or prompts."""
    text = json.dumps(error, ensure_ascii=True).lower()
    if any(word in text for word in ('usage_limit', 'usagelimit', 'rate_limit', 'ratelimit', 'quota', 'credits', 'limit reached')):
        return 'Codex 사용량 한도에 도달했습니다. Codex에서 남은 사용량과 초기화 시간을 확인하세요. API로 전환하지 않았습니다.'
    if any(word in text for word in ('unauthorized', 'authentication', 'token expired', '401', 'sign in', 'not logged')):
        return 'Codex 로그인이 필요하거나 만료되었습니다. Codex 연결에서 ChatGPT로 다시 로그인하세요.'
    if any(word in text for word in ('model', 'unsupported', 'not found', 'invalid params')):
        return 'Codex 모델 또는 연결 형식이 지원되지 않습니다. 모델 목록을 새로 찾고 Codex CLI를 업데이트하세요.'
    return 'Codex 연결 또는 설계 요청에 실패했습니다. 인터넷 연결과 Codex 로그인·사용량을 확인하세요. 현재 설계는 변경되지 않았습니다.'


class _ProcessJob:
    """Windows closes the owned process tree even if the CAD exits mid-request."""
    def __init__(self, pid):
        self.handle = None
        if os.name != 'nt': return
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('ProcessUserTimeLimit', ctypes.c_int64), ('JobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', Io), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = w.HANDLE; kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE; kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]; kernel.CloseHandle.argtypes = [w.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        info = Extended(); info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        try:
            if not job or not process or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(job, process):
                if job: kernel.CloseHandle(job)
                raise ValueError('Codex 종료 관리를 준비하지 못했습니다. CAD와 Codex를 같은 사용자 권한으로 실행하세요.')
            self.handle = job; self.kernel = kernel
        finally:
            if process: kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


class CodexSession:
    def __init__(self, executable='', *, profile=None):
        self.executable = find_executable(executable)
        self.profile = Path(profile) if profile else None
        self.cwd = (self.profile / 'cad-session') if self.profile else data_root() / 'codex-session'
        self.tool_overrides = {}
        self.process = None; self.reader = None; self.job = None
        self.pending = {}; self.events = asyncio.Queue(maxsize=4096); self.serial = 0
        self.active_thread = None; self.active_turn = None; self.login_id = None

    async def __aenter__(self):
        self.cwd.mkdir(parents=True, exist_ok=True)
        # Let Codex reuse its own official login. Never read/copy auth.json or
        # hand browser cookies/tokens to a third-party API client.
        env = {key: value for key, value in os.environ.items() if not key.startswith(('OPENAI_', 'CODEX_', 'CHATGPT_'))}
        if self.profile: env['CODEX_HOME'] = str(self.profile.resolve())
        elif os.getenv('CODEX_HOME'): env['CODEX_HOME'] = os.environ['CODEX_HOME']
        overrides = {'model_provider': 'openai',
                     'approval_policy': 'never', 'sandbox_mode': 'read-only', 'web_search': 'disabled',
                     'features.shell_tool': False, 'features.unified_exec': False, 'features.apps': False,
                     'features.remote_plugin': False, 'features.multi_agent': False, 'features.hooks': False,
                     'features.memories': False, 'features.goals': False, 'features.shell_snapshot': False,
                     'history.persistence': 'none', 'analytics.enabled': False, 'check_for_update_on_startup': False}
        args = [self.executable, 'app-server', '--listen', 'stdio://']
        for key, value in overrides.items(): args += ['-c', key + '=' + json.dumps(value)]
        try:
            self.process = await asyncio.create_subprocess_exec(*args, cwd=str(self.cwd), env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, limit=4_000_000,
                **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            self.job = _ProcessJob(self.process.pid)
            self.reader = asyncio.create_task(self._read())
            await self.rpc('initialize', {'clientInfo': {'name': 'prompt_cad_studio', 'title': 'Prompt CAD Studio', 'version': __version__}})
            await self.send({'method': 'initialized', 'params': {}})
            # Disable inherited integrations for this CAD thread only, without
            # changing the user's config. config/read is handled locally by
            # Codex; configuration is never logged or persisted by the CAD.
            config = (await self.rpc('config/read', {'includeLayers': False})).get('config', {})
            def clean(value):
                if isinstance(value, dict): return {key: clean(item) for key, item in value.items() if item is not None}
                if isinstance(value, list): return [clean(item) for item in value]
                return value
            for section in ('mcp_servers', 'plugins', 'apps'):
                values = config.get(section) or {}
                if isinstance(values, dict):
                    self.tool_overrides[section] = {name: {**clean(value), 'enabled': False}
                        for name, value in values.items() if isinstance(value, dict)}
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def send(self, value):
        if self.process.returncode is not None: raise ValueError('Codex 연결이 종료되었습니다. 연결 창에서 다시 확인하세요.')
        self.process.stdin.write((json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8'))
        await self.process.stdin.drain()

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                packet = json.loads(line)
                if 'id' in packet and 'method' not in packet:
                    future = self.pending.pop(packet['id'], None)
                    if future and not future.done():
                        if 'error' in packet: future.set_exception(ValueError(safe_error(packet['error'])))
                        else: future.set_result(packet.get('result', {}))
                elif 'id' in packet:
                    # This integration only consumes declarative CAD plans.
                    # Never grant shell, file, MCP or credential requests.
                    await self.send({'id': packet['id'], 'error': {'code': -32601, 'message': 'CAD plan-only client; tool execution is unavailable'}})
                elif 'method' in packet:
                    if self.events.full(): raise ValueError('Codex 응답이 너무 많습니다. 설계를 나누어 요청하세요.')
                    self.events.put_nowait(packet)
        except asyncio.CancelledError:
            return
        except Exception:
            pass
        finally:
            error = ValueError('Codex 연결이 종료되었거나 응답 형식이 올바르지 않습니다. CLI를 업데이트하고 다시 연결하세요.')
            for future in self.pending.values():
                if not future.done(): future.set_exception(error)
            self.pending.clear()
            if not self.events.full(): self.events.put_nowait({'method': '_closed'})

    async def rpc(self, method, params, timeout=30):
        self.serial += 1; identifier = self.serial
        future = asyncio.get_running_loop().create_future(); self.pending[identifier] = future
        try:
            await self.send({'id': identifier, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(identifier, None)

    async def event(self):
        item = await self.events.get()
        if item['method'] == '_closed': raise ValueError('Codex 연결이 끊겼습니다. 현재 설계는 변경되지 않았습니다.')
        return item

    async def account(self):
        account = (await self.rpc('account/read', {'refreshToken': False})).get('account')
        if not account or account.get('type') != 'chatgpt':
            raise ValueError('Codex에 ChatGPT 로그인이 필요합니다. Codex 연결에서 기존 로그인 확인 또는 ChatGPT 로그인을 누르세요. API 키는 사용하지 않습니다.')
        return {'plan': account.get('planType', 'unknown')}

    async def models(self):
        result = []; cursor = None
        for _ in range(10):
            page = await self.rpc('model/list', {'limit': 100, 'includeHidden': False, 'cursor': cursor})
            for model in page.get('data', []):
                name = model.get('model', '')
                if IDENTIFIER.fullmatch(name):
                    result.append({'model': name, 'name': model.get('displayName', name), 'default': bool(model.get('isDefault')),
                                   'efforts': [v['reasoningEffort'] for v in model.get('supportedReasoningEfforts', []) if isinstance(v, dict) and 'reasoningEffort' in v]})
            cursor = page.get('nextCursor')
            if not cursor: break
        if not result: raise ValueError('사용 가능한 Codex 모델이 없습니다. 계정 접근 권한과 CLI 버전을 확인하세요.')
        return result

    async def rate_limits(self):
        from .codex_usage import normalize_usage
        return normalize_usage(await self.rpc('account/rateLimits/read', {}, timeout=10))

    async def login(self, progress):
        result = await self.rpc('account/login/start', {'type': 'chatgpt'})
        self.login_id = result.get('loginId')
        progress({'login_url': login_url(result['authUrl'])})
        while True:
            event = await self.event(); params = event.get('params', {})
            if event['method'] == 'account/login/completed' and params.get('loginId') == self.login_id:
                self.login_id = None
                if not params.get('success'): raise ValueError(safe_error(params.get('error')))
                return await self.account()

    async def content(self, model, messages, schema, effort, progress):
        # A fresh ephemeral thread prevents previous phase schemas/history from
        # changing the planner contract and avoids cluttering Codex task lists.
        await self.account()  # gate EVERY generation against API-key auth
        thread = await self.rpc('thread/start', {'model': model, 'modelProvider': 'openai',
            'ephemeral': True, 'cwd': str(self.cwd.resolve()), 'config': self.tool_overrides,
            'approvalPolicy': 'never', 'sandbox': 'read-only',
            'baseInstructions': 'You are a CAD plan generator. Return only the JSON object matching the output schema. Do not use tools, read files, execute code or access the network.',
            'developerInstructions': messages[0]['content']})
        self.active_thread = thread['thread']['id']
        cursor = None
        for _ in range(20):
            status = await self.rpc('mcpServerStatus/list', {'threadId': self.active_thread, 'cursor': cursor, 'limit': 100})
            if any(item.get('tools') for item in status.get('data', [])):
                raise ValueError('CAD 전용 Codex 세션에서 다른 도구를 분리하지 못했습니다. CLI를 업데이트하세요. 설계 요청은 전송하지 않았습니다.')
            cursor = status.get('nextCursor')
            if not cursor: break
        if cursor: raise ValueError('Codex 도구 상태가 너무 많습니다. 설계 요청을 시작하지 않았습니다.')
        text = '\n\n'.join(v['role'] + ':\n' + v['content'] for v in messages[1:])
        turn = await self.rpc('turn/start', {'threadId': self.active_thread,
            'input': [{'type': 'text', 'text': text}], 'model': model, 'effort': effort,
            'outputSchema': schema, 'serviceTier': 'default',
            'sandboxPolicy': {'type': 'readOnly'}})
        self.active_turn = turn['turn']['id']; final = ''; size = 0
        while True:
            event = await self.event(); params = event.get('params', {}); method = event['method']
            if params.get('threadId') != self.active_thread: continue
            if params.get('turnId', self.active_turn) != self.active_turn: continue
            if method == 'item/agentMessage/delta':
                size += len(params.get('delta', ''))
                if size > 2_000_000: raise ValueError('Codex 응답이 너무 큽니다. 설계를 나누어 요청하세요.')
            elif method == 'item/completed':
                item = params.get('item', {})
                if item.get('type') == 'agentMessage' and item.get('phase') in (None, 'final_answer'):
                    final = item.get('text', '')
            elif method == 'turn/completed':
                turn = params.get('turn', {})
                if turn.get('id') != self.active_turn: continue
                self.active_turn = None
                if turn.get('status') != 'completed': raise ValueError(safe_error(turn.get('error', {})))
                if not final: raise ValueError('Codex가 CAD 작업 계획을 반환하지 않았습니다. 요청을 다시 확인하세요.')
                return final
            elif method == 'error' and not params.get('willRetry', False):
                raise ValueError(safe_error(params))

    async def __aexit__(self, *args):
        if self.process:
            try:
                if self.active_turn:
                    await self.rpc('turn/interrupt', {'threadId': self.active_thread, 'turnId': self.active_turn}, timeout=1)
                if self.login_id:
                    await self.rpc('account/login/cancel', {'loginId': self.login_id}, timeout=1)
            except (Exception, asyncio.CancelledError): pass
            if self.job: self.job.close()
            if self.process.returncode is None:
                try: self.process.terminate()
                except ProcessLookupError: pass
            try: await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill(); await self.process.wait()
            if self.reader:
                self.reader.cancel(); await asyncio.gather(self.reader, return_exceptions=True)


def connect(executable='', *, login=False, control=None, progress=None, session_factory=CodexSession):
    control = control or DraftControl(); progress = progress or (lambda value: None)
    async def run():
        async with session_factory(executable) as session:
            account = await session.login(progress) if login else await session.account()
            models = await session.models()
            try:usage = await session.rate_limits()
            except (ValueError, asyncio.TimeoutError):usage = {'buckets':[]}
            return {'account': account, 'models': models, 'executable': session.executable, 'usage': usage}
    return asyncio.run(control.execute(run, 300 if login else 40, 'Codex 연결 시간이 초과되었습니다. 인터넷 연결을 확인하고 다시 시도하세요.'))
