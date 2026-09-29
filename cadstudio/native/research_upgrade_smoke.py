"""Offline native/frozen integration checks for the research/AI update."""
from copy import deepcopy
import json
from zipfile import ZipFile
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def run_checks(app,w,path,check,wait,original_generator):
    from . import codex_ai,codex_connection
    from .codex_usage import normalize_usage
    from .part_role_dialog import PartRoleDialog
    from .research_dialog import ResearchDialog
    from ..catalog import preset
    from ..models import Design,Part
    from ..kernel import build,preview
    from ..assembly_motion import set_joint_motion
    from ..joint_alignment import options,align
    from ..research_package import export_package
    import numpy as np
    from ..threads import cylinder_records
    old_generator=codex_ai.generate;old_connect=codex_connection.connect
    calls=[]
    class Session:
        def __init__(self):self.n=0
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def account(self):return dict(plan='test')
        async def models(self):return [dict(model='fixture',efforts=['medium'])]
        async def content(self,model,messages,schema,effort,progress):
            calls.append(messages);self.n+=1
            if self.n==1:return json.dumps(dict(intent='assembly',tools=['create'],shapes=['plate'],new_parts=['frame','sample'],connections=[]))
            actions=[dict(tool='create',target='frame',args=dict(name='Frame',role='structure',geometry=dict(kind='plate',length=30,width=20,thickness=10))),dict(tool='create',target='sample',args=dict(name='Specimen',role='specimen',geometry=dict(kind='plate',length=60,width=4,thickness=2),transform=dict(z=6)))]
            if self.n>=9:actions.append(dict(tool='pocket',target='frame',args=dict(face='+Z',profile=dict(rectangle=dict(width=31,height=4.4)),depth=4.2)))
            return json.dumps(dict(summary='Clearance repaired',actions=actions))
    try:
        codex_ai.generate=lambda request,model,**kw:original_generator(request,model,session_factory=lambda _:Session(),**kw)
        w.document.dirty=False;w.new_document();w.prompt.setPlainText('간섭 없이 시편 클램프 설계');w.ai_timeout.setCurrentIndex(w.ai_timeout.findData(None))
        w.generate_button.click();wait(lambda:w.ai_task is None)
        check(w.last_draft is not None,'Unlimited generation returns a validated draft')
        check(w.last_draft['response']['attempts']==8,'Native unlimited revision passes the previous six-attempt ceiling')
        check(w.last_draft['response']['validation']['status']=='ready','Eight-attempt result truly passes interference review')
        check(not w.last_draft['preview']['stats']['collisions'],'Actual clearance pocket removes overlap')
        check(w.document.design is None,'Long repair does not mutate the original')
        check(max(map(len,calls))<=4,'Unlimited repair keeps bounded message context')
        w.apply_draft();wait(lambda:not w.busy)
        check(w.document.design['parts'][0]['color']=='#F2F2F2','New structure is white')
        check(w.document.design['parts'][1]['color']=='#AEB6BF','New specimen is gray')
        before=deepcopy(w.document.design);w.select_parts(['frame','sample'])
        def role_modal():
            modal=QApplication.activeModalWidget()
            assert isinstance(modal,PartRoleDialog)
            modal.role.setCurrentIndex(modal.role.findData('electrical'));modal.accept()
        QTimer.singleShot(200,role_modal);w.role_selection();wait(lambda:not w.busy)
        check(all(p['role']=='electrical' and p['color']=='#FFD400' for p in w.document.design['parts']),'Native multi-selection role dialog applies yellow')
        w.undo();wait(lambda:not w.busy);check(w.document.design==before,'Role change undoes exactly')
        codex_connection.connect=lambda *a,**kw:dict(account=dict(plan='test'),models=[dict(model='fixture',name='Fixture',efforts=['medium'])],usage=normalize_usage(dict(rateLimits=dict(primary=dict(usedPercent=87,windowDurationMins=10080,resetsAt=1791046745)))))
        w.codex_check_button.click();wait(lambda:w.codex_probe_task is None)
        check('13% 남음' in w.codex_usage.text(),'Native usage widget displays weekly remainder')
        check('초기화' in w.codex_usage.text(),'Native usage widget displays reset time')
        check('✓' in w.codex_status.text(),'Usage refresh preserves verified connection indicator')
        w.ai_dock.show();w.ai_dock.raise_();app.processEvents();w.ai_scroll.ensureWidgetVisible(w.codex_usage);app.processEvents()
        check(w.codex_usage.isVisible(),'Usage is reachable in the native AI panel')
        w.ai_scroll.grab().save(str(path.with_name('research-usage.png')))
        raw=Design(parts=[Part(id='guide',name='Guide',geometry=dict(kind='cylinder',diameter=30,height=20,bore_diameter=12.4),fixed=True,transform=dict(rx=70,ry=20)),Part(id='shaft',name='Shaft',geometry=dict(kind='cylinder',diameter=12,height=20))],mates=[dict(id='linear',kind='slider',parent='guide',child='shaft',limits={'z':[-10,10]})]).model_dump()
        a,b=options(raw,'linear');d,_=align(raw,'linear',next(v['index'] for v in a if v['internal']),b[0]['index'],gap=0,angle=25)
        check(bool(d.joint_frames),'Slider binds to real cylindrical faces')
        for distance in (-10,0,10):
            pose=d.model_dump();set_joint_motion(pose,'linear',dict(z=distance));solid=build(Design.model_validate(pose))
            check(solid[0].intersect(solid[1]).Volume()<1e-7,f'Slider clear at {distance} mm')
            ca=next(c for c in cylinder_records(solid[0]) if c.internal);cb=cylinder_records(solid[1])[0]
            check(np.linalg.norm(np.cross(np.array(cb.frame.origin)-ca.frame.origin,ca.frame.normal))<1e-7,f'Slider concentric at {distance} mm')
        sample=preset('round_specimen');dialog=ResearchDialog(w,sample.model_dump());dialog.show();app.processEvents()
        check(all(not f.text() for f in dialog.fields.values()),'Unknown test ratings stay blank')
        dialog.accept();archive=export_package(sample,'part-1',dialog.protocol,path.with_name('research-example.zip'));dialog.deleteLater()
        with ZipFile(archive) as z:
            data=json.loads(z.read('protocol.json'))
            check(data['protocol']['max_force_N'] is None,'Export preserves unspecified maximum load')
            check(data['model_time_mapping'] is None and not data['solver_integration'],'No invented physical/model time mapping or solver result')
            check(len(z.read('measurements-template.csv').splitlines())==1,'CSV contains headers only, no fabricated measurements')
            check(z.read('specimen.step').startswith(b'ISO-10303-21'),'Export includes actual STEP specimen geometry')
        english=app.cad_language;english.set_language('en',persist=False)
        check('13% remaining' in w.codex_usage.text(),'Usage widget switches to English')
        english.set_language('ko',persist=False)
    finally:
        codex_ai.generate=old_generator;codex_connection.connect=old_connect
