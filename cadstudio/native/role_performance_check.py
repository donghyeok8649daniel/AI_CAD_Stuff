"""Bounded verification of role preferences and selection/read optimization."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json,os,traceback


def run(output):
    from cadstudio import __version__,__build_id__
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    report=dict(version=__version__,build_id=__build_id__,success=False,
        scope='owned synthetic model/history, offscreen Qt and CPU VTK actors only',
        user_projects=0,geometry_runs=0,GPU_frames=0,normal_windows=0,checks={})
    def check(name,value):
        report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
    def rejects(fn):
        try:fn()
        except (ValueError,TypeError):return True
        return False
    try:
        from PySide6.QtWidgets import QApplication,QTreeWidget,QTreeWidgetItem,QAbstractItemView,QWidget
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QAction,QColor
        from vtkmodules.vtkRenderingCore import vtkActor
        from shiboken6 import delete
        from ..role_colors import normalize_colors,load_colors,load_settings,save_colors,request_colors
        from ..part_roles import COLORS,new_part_style,assign_role
        from ..catalog import part_default,preset
        from ..models import Design,Project,DraftRequest
        from ..associativity import resolve_profiles
        from .document import Journal,Document
        from .role_color_settings import RoleColorSettings
        from .role_view import RoleViewUI,confirmed_display_roles,NEUTRAL_COLOR
        from .part_ui import PartSelectionUI
        from .viewport import CADViewport
        from .cad_tools import CADAction,_apply
        app=QApplication.instance() or QApplication([])
        palette=normalize_colors(dict(electrical='#C2A13F',structure='#D9E2F1',transmission='#339988'))
        path=output.parent/(output.stem+'-settings')/'role-colors.json'
        check('missing_settings_default',load_settings(path)==(COLORS,False))
        save_colors(path,request_colors(palette),view_enabled=True)
        check('restart_palette_and_mode',load_settings(path)==(palette,True))
        original=path.read_bytes();dialog=RoleColorSettings(None,palette,view_enabled=True)
        dialog.restore_defaults();dialog.reject()
        check('cancel_reset_preserves_file',path.read_bytes()==original)
        check('dialog_reset_has_legacy_defaults',dialog.selected_colors()==request_colors(COLORS))
        save_colors(path,dialog.selected_colors(),view_enabled=False)
        check('save_reset_and_restart',load_settings(path)==(COLORS,False));delete(dialog)
        check('bad_palette_rejected',all(rejects(lambda x=x:normalize_colors(x)) for x in
            [[],{'structure':'red'},{'electrical':'#00000000'},{'missing':'#123456'}]))
        path.write_text('{"schema":"cadstudio-role-colors-1"}',encoding='utf-8')
        check('malformed_settings_rejected',rejects(lambda:load_colors(path)))
        check('new_part_custom_default',part_default('plate',palette=palette).color==palette['structure'])
        check('new_gear_custom_default',new_part_style('spur_gear',palette=palette)['color']==palette['transmission'])
        check('explicit_new_color_wins',new_part_style('plate','structure','#123456',palette=palette)['color']=='#123456')
        part=part_default('plate').model_dump();part['color']='#123456'
        assign_role(part,'structure',use_color=False,palette=palette)
        check('role_assign_preserves_custom_color',part['color']=='#123456')
        assign_role(part,'electrical',palette=palette)
        check('explicit_role_color_apply',part['color']==palette['electrical'])
        check('old_request_serialization_unchanged','role_colors' not in DraftRequest(prompt='plate').model_dump())
        req=DraftRequest(prompt='plate',role_colors=request_colors(palette))
        check('request_snapshots_palette',req.role_colors==request_colors(palette))
        raw=Design(name='Created parts').model_dump()
        action=CADAction(tool='create',target='p',args=dict(name='Plate',role='structure',geometry={'kind':'plate','width':20,'length':30,'thickness':2}))
        _apply(raw,action,palette=req.role_colors)
        check('AI_create_uses_request_palette',raw['parts'][0]['color']==palette['structure'])
        check('AI_create_keeps_dimensions',raw['parts'][0]['geometry']['width']==20 and raw['parts'][0]['geometry']['length']==30)
        model_raw=preset('cylinder').model_dump();before=deepcopy(model_raw)
        checked=Design.model_validate(model_raw);checked.parts[0].geometry.height+=1
        check('normalization_owns_input',model_raw==before)
        linked=resolve_profiles(model_raw);linked['parts'][0]['geometry']['height']+=7
        check('standalone_profile_resolution_owns_input',model_raw==before)
        import cadstudio.parameters as parameters
        import cadstudio.associativity as associativity
        counts=[0,0];p_copy=parameters.deepcopy;a_copy=associativity.deepcopy
        def pc(value):counts[0]+=1;return p_copy(value)
        def ac(value):counts[1]+=1;return a_copy(value)
        parameters.deepcopy=pc;associativity.deepcopy=ac
        try:Design.model_validate(model_raw)
        finally:parameters.deepcopy=p_copy;associativity.deepcopy=a_copy
        check('one_owned_normalization_copy',counts==[1,0])
        base=preset('cylinder').model_dump();after=deepcopy(base);after['parts'][0]['geometry']['height']+=2
        journal=Journal(base);journal.append(base,after,'height');saved=dict(version=2,design=after,history=journal.data)
        typed=Project.model_validate(saved)
        check('history_roundtrip_identical',Project.model_validate_json(typed.model_dump_json()).model_dump()==typed.model_dump())
        untouched_typed=typed.model_dump();doc=Document();doc.load(typed)
        doc.journal.data['entries'][0]['label']='edited';doc.design['parts'][0]['color']='#123456'
        check('document_load_independent_of_typed_project',typed.model_dump()==untouched_typed)
        other=Journal(data=journal.data);other.data['entries'][0]['label']='different'
        check('standalone_journal_still_owns_input',other.data!=journal.data)
        bad=deepcopy(saved);bad['history']['entries'][1]['changes'][0]['before']=987
        check('history_wrong_before_rejected',rejects(lambda:Project.model_validate(bad)))
        bad=deepcopy(saved);bad['history']['entries'][1]['changes'][0]['path']=['__proto__','bad']
        check('history_unsafe_path_rejected',rejects(lambda:Project.model_validate(bad)))
        bad=deepcopy(saved);bad['design']['parts'][0]['geometry']['height']+=1
        check('history_cursor_mismatch_rejected',rejects(lambda:Project.model_validate(bad)))
        # Real Qt rows, including non-part feature selection and a blocked tree.
        tree=QTreeWidget();tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        index={}
        for i in range(250):
            item=QTreeWidgetItem(tree,['Part '+str(i)]);item.setData(0,Qt.ItemDataRole.UserRole,('part',str(i)));index[str(i)]=item
            feature=QTreeWidgetItem(item,['feature']);feature.setData(0,Qt.ItemDataRole.UserRole,('feature',str(i),'f'))
        selection=SimpleNamespace(tree=tree,_part_tree_items=index,selected_parts=['0','249'])
        feature.setSelected(True);tree.blockSignals(True);PartSelectionUI.sync_tree_selection(selection)
        check('indexed_selection_exact_and_signal_state',tree.signalsBlocked() and set(x.data(0,Qt.ItemDataRole.UserRole)[1] for x in tree.selectedItems())=={'0','249'})
        tree.blockSignals(False);selection.selected_parts=['3'];PartSelectionUI.sync_tree_selection(selection)
        check('indexed_selection_delta_and_feature_clear',tree.selectedItems()==[index['3']])
        selection._part_tree_items=None;selection.selected_parts=['6'];PartSelectionUI.sync_tree_selection(selection)
        check('unindexed_selection_fallback',tree.selectedItems()==[index['6']])
        tree.clear();selection._part_tree_items={};selection.selected_parts=[];PartSelectionUI.sync_tree_selection(selection)
        check('cleared_tree_index_safe',not tree.selectedItems());delete(tree)
        actors={str(i):(vtkActor(),vtkActor()) for i in range(250)}
        renders=[];view=SimpleNamespace(actors=actors,hidden=set(),show_edges=True,render=lambda:renders.append(1))
        CADViewport.select_many(view,['3','249']);snapshot={i:(a.GetMTime(),e.GetMTime(),a.GetProperty().GetMTime(),e.GetProperty().GetMTime()) for i,(a,e) in actors.items()}
        CADViewport.select_many(view,['3','249'])
        check('repeat_selection_no_actor_mutation',{i:(a.GetMTime(),e.GetMTime(),a.GetProperty().GetMTime(),e.GetProperty().GetMTime()) for i,(a,e) in actors.items()}==snapshot)
        check('repeat_selection_still_renders',len(renders)==2)
        view.hidden={'249'};view.show_edges=False;CADViewport.select_many(view,['249'],False)
        check('hidden_edge_and_selection_flags',not actors['249'][1].GetVisibility() and not actors['3'][1].GetVisibility())
        actors['3']=(vtkActor(),vtkActor());CADViewport.select_many(view,['3'],False)
        check('replaced_actor_restyled',actors['3'][0].GetProperty().GetAmbient()==.4 and actors['3'][1].GetVisibility())
        data=dict(parts=[dict(id='e',role='electrical',color='#123456'),dict(id='s',role='structure',color='#ABCDEF'),dict(id='t',role='transmission',color='#654321'),dict(id='u',role='unspecified',color=COLORS['structure']),dict(id='c',role='structure',color='#654321'),dict(id='r',role='unspecified',color='#765432')],electrical={'components':[{'part_id':'c'},{'part_id':'r'}]})
        check('confirmed_roles_conflicts_and_no_color_guess',confirmed_display_roles(data)=={'e':'electrical','s':'structure','t':'transmission','u':'unspecified','c':'unspecified','r':'electrical'})
        roles_view=SimpleNamespace(actors={p['id']:(vtkActor(),vtkActor()) for p in data['parts']},meshes={p['id']:{'color':p['color']} for p in data['parts']},render=lambda:None)
        host=SimpleNamespace(role_view=None,role_colors_enabled=True,role_colors=palette,document=SimpleNamespace(design=data),viewport=roles_view)
        untouched=deepcopy(data);RoleViewUI.refresh_role_view(host)
        rgb=lambda color:QColor(color).getRgbF()[:3]
        check('current_role_view_palette_and_unknown',roles_view.actors['s'][0].GetProperty().GetColor()==rgb(palette['structure']) and roles_view.actors['u'][0].GetProperty().GetColor()==rgb(NEUTRAL_COLOR) and roles_view.actors['c'][0].GetProperty().GetColor()==rgb(NEUTRAL_COLOR))
        check('role_view_model_and_mesh_unchanged',data==untouched and all(roles_view.meshes[p['id']]['color']==p['color'] for p in data['parts']))
        RoleViewUI._restore_role_colors(host);host.role_colors_enabled=False;RoleViewUI.refresh_role_view(host)
        check('role_view_off_restores_all_custom_colors',all(roles_view.actors[p['id']][0].GetProperty().GetColor()==rgb(p['color']) for p in data['parts']))
        # Invoke the real open_project callback with an owned synthetic result.
        # No file parsing, kernel, window construction or worker is executed.
        from .window import MainWindow
        callbacks=[];events=[]
        opened_document=SimpleNamespace(design=None,dirty=False)
        def load_document(project,path):
            opened_document.design=project.design.model_dump();events.append('document')
        opened_document.load=load_document
        opened_view=SimpleNamespace(actors={},meshes={},hidden=set(),joints=SimpleNamespace(set_design=lambda d:None),render=lambda:events.append('render'))
        def load_view(result,fit):
            opened_view.actors={p.id:(vtkActor(),vtkActor()) for p in result.parts}
            opened_view.meshes={p.id:dict(color=p.color) for p in result.parts}
            for p in result.parts:opened_view.actors[p.id][0].GetProperty().SetColor(rgb(p.color))
            events.append('actors')
        opened_view.load=load_view
        opened_host=SimpleNamespace(busy=False,sketching=False,check_save=lambda:True,cancel_ai=lambda:None,
            run=lambda work,done,title:callbacks.append(done),set_references=lambda r:None,
            reset_role_view=lambda **kw:None,document=opened_document,viewport=opened_view,
            operation_serial=0,accept_draft=SimpleNamespace(setEnabled=lambda x:None),
            prompt=SimpleNamespace(setPlainText=lambda x:None),actions={'isolate':SimpleNamespace(setChecked=lambda x:None)},
            rebuild_tree=lambda:events.append('tree'),select_parts=lambda ids:None,rebuild_timeline=lambda:None,
            title=lambda:None,message=lambda x:None,role_view=None,role_colors_enabled=True,role_colors=palette)
        opened_host.refresh_role_view=lambda:RoleViewUI.refresh_role_view(opened_host)
        opened=Project(design=preset('plate'));opened.design.parts[0].color='#123456'
        payload_before=opened.model_dump()
        MainWindow.open_project(opened_host,output.parent/'owned-callback.pcad')
        callbacks.pop()((opened,opened.design))
        identifier=opened.design.parts[0].id
        check('open_callback_reapplies_persisted_role_after_new_actors',opened_view.actors[identifier][0].GetProperty().GetColor()==rgb(palette['structure']) and events.index('actors')<events.index('render')<events.index('tree'))
        check('open_callback_preserves_custom_project_payload',opened.model_dump()==payload_before and opened_document.design['parts'][0]['color']=='#123456' and opened_view.meshes[identifier]['color']=='#123456')
        opened_host.role_colors_enabled=False;events.clear()
        MainWindow.open_project(opened_host,output.parent/'owned-second-callback.pcad')
        callbacks.pop()((opened,opened.design))
        check('open_callback_disabled_keeps_stored_colors',opened_view.actors[identifier][0].GetProperty().GetColor()==rgb('#123456'))
        report['checks_count']=len(report['checks']);report['success']=True
    except Exception:
        report['error']=traceback.format_exc()
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 2
