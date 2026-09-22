"""Standalone Windows app: private loopback API + WebView2 window."""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',type=Path)
    parser.add_argument('--smoke-test',type=Path)
    args=parser.parse_args()
    bundle=Path(__file__).resolve().parent
    data=Path(os.getenv('CADSTUDIO_DATA_DIR',Path(os.getenv('LOCALAPPDATA',str(bundle))) / 'PromptCADStudio'))
    data.mkdir(parents=True,exist_ok=True)
    os.environ['CADSTUDIO_DATA_DIR']=str(data)
    log=(data/'desktop.log').open('a',encoding='utf-8',buffering=1)
    if sys.stdout is None:sys.stdout=log
    if sys.stderr is None:sys.stderr=log
    logging.basicConfig(stream=log,level=logging.WARNING)
    from launch import refresh_user_environment
    refresh_user_environment()
    if args.self_test:
        from cadstudio.catalog import preset
        from cadstudio.kernel import preview,export
        import tempfile
        report={}
        with tempfile.TemporaryDirectory() as folder:
            for kind in ['round_specimen','extrusion','robot_arm']:
                d=preset(kind);result=preview(d)
                path=Path(folder)/f'{kind}.step';export(d,path,'step')
                report[kind]={'valid':result['stats']['valid'],'parts':len(d.parts),'step_bytes':path.stat().st_size,'constraints':result['stats']['assembly_constraints']}
        from cadstudio.models import Extrusion,Design,Part
        from cadstudio.sketch_engine import sketch_preview,sketch_status
        g=Extrusion(sketch_mode='entities',entities=[dict(id='circle',kind='circle',center=dict(x=0,y=0),radius=10)],entity_constraints=[dict(id='origin',kind='fixed',a='circle',a_point='center',x=0,y=0),dict(id='diameter',kind='diameter',a='circle',value=20)])
        advanced=Design(name='Analytic sketch',parts=[Part(id='part',name='Circle',geometry=g)])
        report['analytic_sketch']={'valid':preview(advanced)['stats']['valid'],'regions':len(sketch_preview(g)['regions']),'dof':sketch_status(g)['dof']}
        args.self_test.write_text(json.dumps(report,indent=2),encoding='utf-8')
        return
    import uvicorn
    import webview
    from cadstudio import server as application
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:listener.bind(('127.0.0.1',18761))
    except OSError:listener.bind(('127.0.0.1',0))
    listener.listen(128)
    port=listener.getsockname()[1]
    running=uvicorn.Server(uvicorn.Config(application.app,host='127.0.0.1',port=port,log_level='warning',log_config=None))
    thread=threading.Thread(target=lambda:running.run(sockets=[listener]),daemon=True)
    thread.start()
    for _ in range(200):
        if running.started:break
        if not thread.is_alive():raise RuntimeError('CAD 서버를 시작하지 못했습니다.')
        time.sleep(.05)
    else:raise RuntimeError('CAD 서버 시작 시간이 초과되었습니다.')
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.settings['ALLOW_FILE_URLS']=False
    window=webview.create_window('Prompt CAD Studio',f'http://127.0.0.1:{port}',width=1440,height=900,min_size=(960,640),confirm_close=not bool(args.smoke_test))
    application.shutdown_callback=lambda:threading.Timer(.5,window.destroy).start()
    def loaded():
        logging.warning('Desktop WebView2 loaded on port %s',port)
        if args.smoke_test:
            args.smoke_test.write_text(json.dumps({'loaded':True,'port':port,'renderer':'edgechromium'}),encoding='utf-8')
            threading.Timer(6,window.destroy).start()
    window.events.loaded+=loaded
    try:
        webview.start(gui='edgechromium',private_mode=False,storage_path=str(data/'webview'),icon=str(bundle/'static/app.ico'))
    finally:
        running.should_exit=True;thread.join(timeout=5);listener.close()


if __name__=='__main__':
    try:main()
    except Exception:
        message=traceback.format_exc()
        data=Path(os.getenv('CADSTUDIO_DATA_DIR',str(Path(__file__).parent/'data')))
        data.mkdir(parents=True,exist_ok=True)
        (data/'startup-error.log').write_text(message,encoding='utf-8')
        if sys.platform=='win32' and not any(flag in sys.argv for flag in ['--self-test','--smoke-test']):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,'앱을 시작하지 못했습니다. WebView2 Runtime 설치와 startup-error.log를 확인하세요.\n'+str(data),'Prompt CAD Studio',0x10)
        raise
