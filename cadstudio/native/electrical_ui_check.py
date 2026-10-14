"""Small CPU VTK/offscreen Qt checks; no actual CAD open, power or code run."""
from pathlib import Path
from types import SimpleNamespace,MethodType
import json,math

def run(output):
    from PySide6.QtWidgets import QApplication
    from vtkmodules.vtkFiltersSources import vtkCubeSource
    from vtkmodules.vtkRenderingCore import vtkActor,vtkPolyDataMapper,vtkRenderer
    from .viewport import CADViewport
    from .workflows import joint_pose_note
    from .electrical_workbench import ElectricalWorkbenchDialog
    from ..models import Design,Part
    from ..electrical import ElectricalWorkspace
    from ..mcu_connections import connection_endpoints
    from .. import __version__,__build_id__
    app=QApplication.instance() or QApplication([])
    app.cad_language=SimpleNamespace(language='ko')
    report=dict(success=False,checks=[],version=__version__,build_id=__build_id__,
                native_windows_shown=0,gpu_render_calls=0,real_geometry_calls=0,
                hardware_output=0,firmware_execution=0)
    dialogs=[]
    def check(name,condition):
        assert condition,name;report['checks'].append(dict(name=name,passed=True))
    def cube(center,size=10):
        source=vtkCubeSource();source.SetCenter(*center);source.SetXLength(size);source.SetYLength(size);source.SetZLength(size)
        mapper=vtkPolyDataMapper();mapper.SetInputConnection(source.GetOutputPort())
        actor=vtkActor();actor.SetMapper(mapper);return actor
    near,far,sketch=cube((0,0,0)),cube((1000,0,0)),cube((2000,0,0),2)
    renderer=vtkRenderer()
    host=SimpleNamespace(actors={'near':(near,near),'far':(far,far)},hidden=set(),sketch_actors={},
                         result={'stats':{'min':[-5,-5,-5],'max':[1005,5,5],'bounds':[1010,10,10]}},renderer=renderer)
    host.visible_fit_bounds=MethodType(CADViewport.visible_fit_bounds,host)
    renders=[];host.render=lambda:renders.append(True)
    check('complete visible body bounds include both bodies',host.visible_fit_bounds()==[-5,1005,-5,5,-5,5])
    host.hidden={'far'};far.SetVisibility(False)
    check('isolated fit excludes whole assembly extent',host.visible_fit_bounds()==[-5,5,-5,5,-5,5])
    CADViewport.fit(host)
    check('actual VTK camera focuses isolated body',renderer.GetActiveCamera().GetFocalPoint()==(0.,0.,0.))
    check('fit makes one render request and finite clipping',len(renders)==1 and all(math.isfinite(v) for v in renderer.GetActiveCamera().GetClippingRange()))
    host.sketch_actors={sketch:'s'}
    check('isolated fit excludes distant construction sketch',host.visible_fit_bounds()==[-5,5,-5,5,-5,5])
    host.hidden=set();far.SetVisibility(True)
    check('complete view includes visible saved sketch',host.visible_fit_bounds()[1]==2001)
    far.SetVisibility(False)
    check('actor visibility also excludes body even without hidden set',host.visible_fit_bounds()==[-5,5,-5,5,-5,5])
    near.SetVisibility(False)
    check('all hidden bodies use finite default not whole extent',host.visible_fit_bounds()==[-25,25,-25,25,0,0])
    host.actors={}
    check('sketch-only fit includes saved sketch',host.visible_fit_bounds()==[1999,2001,-1,1,-1,1])
    host.sketch_actors={}
    check('empty fit has finite default',host.visible_fit_bounds()==[-25,25,-25,25,0,0])
    class Invalid:
        def GetVisibility(self):return True
        def GetBounds(self):return (float('nan'),1,0,1,0,1)
    invalid=Invalid();host.actors={'invalid':(invalid,invalid)}
    check('invalid actor bounds do not enter camera',host.visible_fit_bounds()==[-25,25,-25,25,0,0])
    source=[dict(a='a',b='b',volume=7.559)]*16
    note=joint_pose_note(source,{'existing':source},None,False)
    check('raw16 explicitly retained in pose note','16' in note and '체적 겹침' in note)
    check('unchanged values have separate Apply-disabled reason','관절값 변경 없음' in note)
    check('raw overlap never gets bare pose-valid claim','현재 자세가 유효' not in note)
    note=joint_pose_note(source,{'existing':source},None,True)
    check('changed values do not claim no-change','변경 없음' not in note)
    note=joint_pose_note([],{},None,True)
    check('clear current pose does not certify travel/load','전체 구동 범위' in note and '하중 정격' in note)
    check('new overlap reason matches blocker','적용이 차단' in joint_pose_note(source,{'blocked':source},None,True))
    check('sampled motion blocker has precedence','구동 중' in joint_pose_note(source,{},dict(blocked=source),True))
    app.cad_language.language='en'
    check('English raw/no-change qualification','16 overlap pairs' in joint_pose_note(source,{},None,False) and 'no new motion' in joint_pose_note(source,{},None,False))
    app.cad_language.language='ko'
    part=Part(id='board',name='Manual board',role='electrical',color='#FFD400',geometry=dict(kind='plate',length=10,width=8,thickness=3,hole_count=0))
    workspace=ElectricalWorkspace.model_validate(dict(nodes=['GND','A','B','PWR','GROUND_LABEL'],components=[dict(
        id='manual',name='Manual reference',kind='mcu',part_id='board',part_registration=True,a='A',b='B',
        analysis_enabled=False,signal_pins={'POWER1_P1':'PWR','POWER1_P6':'GROUND_LABEL'})]))
    design=Design(parts=[part],electrical=workspace)
    dialog=ElectricalWorkbenchDialog(None,design);dialogs.append(dialog)
    check('actual workbench manual notice explicitly shown',not dialog.manual_pin_notice.isHidden())
    check('manual warning identifies POWER/GND typing limit','POWER/GND' in dialog.manual_pin_notice.text() and '신호 참조 라벨' in dialog.manual_pin_notice.text())
    check('manual warning identifies unmodeled converter/ground paths','내부 변환기' in dialog.manual_pin_notice.text())
    check('manual warning does not turn disabled wires into continuity pass','전원 통과 검증이 아닙니다' in dialog.manual_pin_notice.text())
    check('actual manual power-named pins remain signal types',all(e.pin_kind=='signal' for e in connection_endpoints(workspace) if e.terminal.startswith('pin:')))
    check('opening workbench does not enable analysis or mutate design',dialog.draft==design and not dialog.draft.electrical.components[0].analysis_enabled)
    empty=ElectricalWorkbenchDialog(None,Design(parts=[part]));dialogs.append(empty)
    check('no manual pins means no irrelevant manual-pin notice',empty.manual_pin_notice.isHidden())
    report.update(success=True,checks_count=len(report['checks']),
                  limitations=['CPU VTK camera and offscreen widget checks only; actual project native acceptance separate.',
                               'Motion blocking policy unchanged; no motor motion, firmware or power operation.'])
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    for dialog in dialogs:dialog.close();dialog.deleteLater()
    app.processEvents()
    print(json.dumps(dict(success=True,checks=report['checks_count'],build_id=__build_id__)))
    return 0
