"""Frozen native UI and real CAD kernel; deterministic Codex protocol substitute."""
import asyncio
import json
import math
import time
import traceback

from PySide6.QtCore import QTimer
from . import codex_ai, codex_connection
from .codex_setup import CodexSetupDialog
from ..models import Design
from ..kernel import build


def run(app, window, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'checks': [], 'real_model_calls': 0}
    original = codex_ai.generate; original_connect = codex_connection.connect
    def check(value, name):
        if not value: raise AssertionError(name)
        report['checks'].append(name)
    def wait(predicate):
        end = time.monotonic() + 20
        while not predicate() and time.monotonic() < end:
            app.processEvents(); time.sleep(.01)
        check(predicate(), 'native worker completed')
    class Session:
        count = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def account(self): return {'plan': 'pro'}
        async def models(self): return [{'model': 'gpt-6-astra', 'efforts': ['medium']}]
        async def content(self, *args):
            self.count += 1
            if self.count == 1:
                return json.dumps(dict(intent='part', tools=['create', 'hole'], shapes=['cylinder'], new_parts=['hub'], connections=[]))
            return json.dumps(dict(summary='구멍 있는 허브', construction=['직경 40, 높이 10, 관통 구멍 8'],
                base=dict(tool='create', target='hub', args=dict(name='허브', geometry=dict(kind='cylinder', diameter=40, height=10))),
                actions=[dict(tool='hole', target='hub', args=dict(face='+Z', diameter=8, through_all=True))]))
    try:
        check(window.document.design is None, 'blank start')
        window.ai_dock.show(); window.ai_dock.raise_()
        window.provider.setCurrentIndex(window.provider.findData('codex')); app.processEvents()
        check(window.codex_setup_button.isVisible(), 'ChatGPT connection discoverable')
        check(not window.key.isVisible() and not window.openai_setup_button.isVisible(), 'no API key field in subscription mode')
        window.codex_config = dict(executable='', model='gpt-6-astra'); window.provider_changed()
        codex_ai.generate = lambda request, model, **kw: original(request, model, session_factory=lambda _: Session(), **kw)
        window.prompt.setPlainText('직경 40 mm 높이 10 mm 허브에 직경 8 mm 관통 구멍')
        window.generate_button.click(); wait(lambda: window.ai_task is None)
        check(window.last_draft is not None, 'subscription draft ready')
        check(window.document.design is None, 'preview does not replace current design')
        check(window.accept_draft.isEnabled(), 'explicit apply enabled')
        QTimer.singleShot(100,lambda:app.activeModalWidget().accept() if app.activeModalWidget() else None)
        window.accept_draft.click(); wait(lambda: not window.busy and window.document.design is not None)
        solid = build(Design.model_validate(window.document.design))[0]
        check(abs(solid.Volume() - math.pi * (20**2 - 4**2) * 10) < 1e-5, 'real through hole volume')
        check(len(window.document.design['parts']) == 1, 'single connected body')
        check(window.document.design['parts'][0]['features'][0]['operation'] == 'cut', 'editable hole feature preserved')
        window.resize(1000, 680); window.ai_dock.raise_(); app.processEvents(); window.grab().save(str(path.with_name('codex270-mode.png')))
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
        from vtkmodules.vtkIOImage import vtkPNGWriter
        window.viewport.window.Render(); capture = vtkWindowToImageFilter(); capture.SetInput(window.viewport.window)
        capture.ReadFrontBufferOff(); capture.Update(); writer = vtkPNGWriter(); writer.SetFileName(str(path.with_name('codex270-viewport.png')))
        writer.SetInputConnection(capture.GetOutputPort()); writer.Write()
        check(window.generate_button.visibleRegion().contains(window.generate_button.rect()), 'generate reachable at compact size')
        check(window.accept_draft.visibleRegion().contains(window.accept_draft.rect()), 'apply reachable at compact size')
        # Closing setup never needs a GUI-thread join, even while login is pending.
        async def stalled(*args): await asyncio.sleep(60)
        def pending(executable='', **kw):
            return asyncio.run(kw['control'].execute(lambda: stalled(), None))
        codex_connection.connect = pending
        dialog = CodexSetupDialog(window); dialog.show(); dialog.login_button.click(); app.processEvents()
        start = time.monotonic(); dialog.reject()
        check(time.monotonic() - start < .5 and dialog.task is None, 'closing login is immediate and cancellable')
        dialog.deleteLater()
        codex_connection.connect = lambda *args, **kw: dict(account={'plan':'pro'}, executable='example.exe',
            models=[dict(model='gpt-6-astra', name='GPT-6 Astra', default=True, efforts=['medium'])])
        dialog = CodexSetupDialog(window); dialog.resize(460, 520); dialog.show(); dialog.check_button.click()
        wait(lambda: dialog.task is None)
        check(dialog.use_button.isEnabled() and 'pro' in dialog.status.toPlainText(), 'account and model result in native setup')
        check(dialog.status.visibleRegion().contains(dialog.status.rect()), 'connection result visible at compact size')
        dialog.grab().save(str(path.with_name('codex270-setup.png'))); dialog.reject(); dialog.deleteLater()
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc(); report['passed'] = False
    finally:
        codex_ai.generate = original; codex_connection.connect = original_connect
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.cancel_ai(); window.document.dirty = False
        QTimer.singleShot(200, lambda: app.exit(0 if report['passed'] else 1))
