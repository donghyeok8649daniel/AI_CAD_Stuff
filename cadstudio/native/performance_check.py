"""Bounded, synthetic-only source/frozen check. Never opens user projects."""
from pathlib import Path
import hashlib
import json
import os
import time
import traceback


def run(output):
    from cadstudio import __version__, __build_id__
    from cadstudio.models import Design, Part
    import cadstudio.kernel as kernel
    from cadstudio.preview_cache import MeshCache, _BoundedBuffer, _TooLarge
    from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QLineEdit, QComboBox
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QAction
    from shiboken6 import delete
    from .i18n import UILanguage
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    report=dict(version=__version__,build_id=__build_id__,success=False,scope='owned synthetic geometry and offscreen Qt only',
                user_window_inputs=0,user_project_reads=0,checks={})
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    try:
        app=QApplication.instance() or QApplication([])
        raw=Design(name='Performance fixture',parts=[Part(id='p'+str(i),name='부품 '+str(i),
            geometry=dict(kind='cylinder',diameter=20+i*.5,height=8+i*.25,bore_diameter=5),
            transform=dict(x=(i%6)*45,y=(i//6)*45)) for i in range(18)]).model_dump()
        kernel._preview_mesh_cache.clear();outputs=[];times=[]
        for i in range(3):
            start=time.perf_counter();result=kernel.preview(Design.model_validate(raw));times.append(time.perf_counter()-start)
            outputs.append(hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        check('three_identical_preview_outputs',len(set(outputs))==1)
        check('18_parts_15120_triangles',result['stats']['parts']==18 and result['stats']['triangles']==15120)
        check('no_interference_in_spaced_fixture',result['stats']['collisions']==[])
        check('two_mesh_hits',kernel._preview_mesh_cache.info()['hits']==2)
        check('whole_assembly_retention_two',kernel._build_cached.cache_info().maxsize==2)
        report['preview']=dict(seconds=times,output_sha256=outputs[0],cache=kernel._preview_mesh_cache.info())
        result['meshes'][0]['vertices'][0]=999
        fresh=kernel.preview(Design.model_validate(raw))
        check('caller_mutation_does_not_poison_cache',fresh['meshes'][0]['vertices'][0]!=999)
        import cadstudio.interference as interference
        original=interference.exact_collisions;calls=[]
        def counted(*args):calls.append(True);return original(*args)
        interference.exact_collisions=counted
        try:kernel.preview(Design.model_validate(raw))
        finally:interference.exact_collisions=original
        check('exact_interference_runs_on_mesh_hit',len(calls)==1)
        overlap=Design(parts=[Part(id='a',name='A',geometry=dict(kind='cylinder',diameter=20,height=10)),
                             Part(id='b',name='B',geometry=dict(kind='cylinder',diameter=20,height=10),transform=dict(x=5))])
        check('actual_solid_interference_detected',bool(kernel.preview(overlap)['stats']['collisions']))
        overlap.parts[1].transform.x=50
        check('moved_body_refreshes_interference',kernel.preview(overlap)['stats']['collisions']==[])
        cache=MeshCache(max_entries=2);cache.put('a',[1]);cache.put('b',[2]);cache.get('a');cache.put('c',[3])
        check('least_recent_mesh_evicted',cache.get('b') is None and cache.get('a')==[1])
        check('compressed_cache_total_bound',cache.bytes<=cache.max_bytes)
        check('raw_oversize_not_cached',not MeshCache(max_raw_bytes=20).put('x',['x'*1000]))
        with _BoundedBuffer(20) as buffer:
            try:buffer.write(b'x'*1000)
            except _TooLarge:check('raw_admission_stops_before_full_write',buffer.tell()==0)
            else:check('raw_admission_stops_before_full_write',False)
        back=QWidget();backlayout=QVBoxLayout(back)
        for i in range(1600):backlayout.addWidget(QLabel('새 설계'))
        front=QWidget();layout=QVBoxLayout(front);focus=QLabel('새 설계');layout.addWidget(focus)
        edit=QLineEdit('새 설계');edit.setPlaceholderText('새 설계');layout.addWidget(edit)
        combo=QComboBox();combo.addItem('새 설계','unchanged-id');layout.addWidget(combo)
        action=QAction('새 설계',front);front.addAction(action)
        service=UILanguage(app,output.with_suffix('.language.json'));service.set_language('en',persist=False)
        apply=service.apply;seen=[]
        def count(obj):seen.append(id(obj));return apply(obj)
        service.apply=count
        start=time.perf_counter()
        for i in range(20):
            focus.setText('새 설계' if i%2==0 else '회로도')
            QCoreApplication.sendEvent(front,QEvent(QEvent.Type.LayoutRequest));service.flush()
        report['language']=dict(seconds=time.perf_counter()-start,apply_calls=len(seen),background_labels=1600,foreground_updates=20)
        check('dynamic_label_translates',focus.text()=='Circuit')
        check('unrelated_background_not_scanned',id(back) not in seen)
        check('model_id_preserved',combo.itemData(0)=='unchanged-id')
        check('user_input_preserved',edit.text()=='새 설계')
        check('input_placeholder_translated',edit.placeholderText()=='New design')
        action.setText('회로도');service.flush();check('action_change_translates',action.text()=='Circuit')
        service.set_language('ko',persist=False);check('full_explicit_language_switch',focus.text()=='회로도' and combo.itemText(0)=='새 설계')
        app.removeEventFilter(service);service.refresh.stop();delete(service);delete(front);delete(back)
        report['success']=True
    except Exception:
        report['error']=traceback.format_exc()
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if report['success'] else 1
