from copy import deepcopy
import json
import numpy as np
import pytest
from cadstudio.models import Design,Transform
from cadstudio.firmware_drive import VirtualDriveSpec,geometry_fingerprint,validate_drive,validate_trace
from cadstudio.firmware_motion import checked_motion,pose_at,actor_matrices,world_matrix
from test_firmware_emulation import workspace,image


def fixture(tmp_path):
    work=workspace();raw=work.model_dump(mode='json')
    raw['components'].append(dict(id='driver',name='Declared virtual driver',kind='load',a='PWR',b='GND',part_registration=True,part_id='driver_body',analysis_enabled=False))
    raw['components'].append(dict(id='motor',name='Declared virtual motor',kind='motor',a='PWR',b='GND',part_registration=True,part_id='shaft',analysis_enabled=False))
    parts=[dict(id=pid,name=pid,fixed=pid=='base',geometry=dict(kind='cylinder',diameter=4,height=10))
           for pid in ('base','shaft','stage','board_body','driver_body')]
    design=Design.model_validate(dict(name='Motion fixture',parts=parts,electrical=raw,
        mates=[dict(id='turn',kind='revolute',parent='base',child='shaft'),dict(id='slide',kind='slider',parent='base',child='stage',z=10,limits={'z':[5,15]})],
        motion_links=[dict(id='lead',driver='turn',driver_axis='rz',driven='slide',driven_axis='z',ratio=5/360,offset=10)]))
    item=image(tmp_path,design.electrical)
    item.virtual_drive=VirtualDriveSpec(profile='cad_synthetic_velocity_servo_v1',virtual_only=True,geometry_sha256=geometry_fingerprint(design),clearance_receipt_sha256='1'*64,
        clearance_basis='discrete_exact_solid_poses_not_continuous_sweep',motor_part_id='shaft',driver_component_id='driver',mate_id='turn',screw_lead_mm_per_rev=5.,declared_gear_ratio=18.77777777777778,
        feedback_basis='synthetic_counter_injection_not_physical_linear_encoder_scale',input_basis='virtual_fault_bits_PC0_stop_PC1_upper_PC2_lower_PC3_guard_not_physical_polarity',
        synthetic_counts_per_screw_rev=4096,velocity_time_constant_s=.02,max_displacement_mm=1.,duration_s=.1,sample_step_s=.005,stop_time_s=.035)
    trace=[dict(time_s=(i+1)*.005,position_mm=i*.01,speed_mm_s=1.,command_mm_s=1.,screw_angle_deg=i*.72,motor_angle_deg=i*.72*18.77777777777778,
        input_mask=0,firmware_input_mask=0,firmware_feedback_um=i*10,firmware_target_um=500,virtual_enable=1,firmware_sequence=i+1) for i in range(20)]
    result=dict(status='executed',image_sha256=item.sha256,scenario='motor_drive',virtual_motion_trace=trace,errors=[])
    return design,item,result


def test_geometry_identity_and_units_are_bound(tmp_path):
    design,item,result=fixture(tmp_path);before=deepcopy(design.model_dump(mode='json'))
    base,spec,trace=checked_motion(design,item,result)
    pose=pose_at(base,spec,trace[10]);stage=next(m for m in pose.mates if m.id=='slide')
    assert abs(stage.z-10.1)<1e-10 and design.model_dump(mode='json')==before
    altered=design.model_copy(deep=True);altered.parts[0].geometry.diameter=6
    with pytest.raises(ValueError,match='stale'):validate_drive(altered,item)
    row=deepcopy(trace[1]);row['screw_angle_deg']*=np.pi/180
    with pytest.raises(ValueError,match='units'):pose_at(design,spec,row)


def test_wrong_execution_partial_trace_and_safety_failure_rejected(tmp_path):
    design,item,result=fixture(tmp_path)
    wrong=deepcopy(result);wrong['image_sha256']='0'*64
    with pytest.raises(ValueError,match='exact ELF'):checked_motion(design,item,wrong)
    wrong=deepcopy(result);wrong['virtual_motion_trace'].pop()
    with pytest.raises(ValueError,match='incomplete'):checked_motion(design,item,wrong)
    wrong=deepcopy(result);wrong['virtual_motion_trace'][0]['firmware_input_mask']=1
    with pytest.raises(ValueError,match='CPU'):checked_motion(design,item,wrong)
    errors=validate_trace({'virtual_trace':result['virtual_motion_trace']},item.virtual_drive,'motor_stop')[1]
    assert 'Requested safety input was never injected.' in errors


def test_known_rotation_translation_and_actor_delta(tmp_path):
    matrix=world_matrix(Transform(x=1,y=2,z=3,rz=90))
    assert np.allclose(matrix@np.array([1,0,0,1]),[1,3,3,1])
    design,item,result=fixture(tmp_path);pose=pose_at(design,item.virtual_drive,result['virtual_motion_trace'][10])
    deltas=actor_matrices(design,pose)
    assert abs(deltas['stage'][2,3]-.1)<1e-9
    assert np.allclose(deltas['base'],np.eye(4))


def test_offscreen_replay_uses_own_actors_and_shuts_down(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication,QWidget
    from vtkmodules.vtkRenderingCore import vtkActor
    from cadstudio.preview_metadata import geometry_key
    import cadstudio.native.firmware_motion_dialog as module
    app=QApplication.instance() or QApplication([])
    design,item,result=fixture(tmp_path);before=design.model_dump(mode='json')
    class View(QWidget):
        def __init__(self,parent):
            super().__init__(parent);self.actors={p.id:(vtkActor(),vtkActor()) for p in design.parts};self.closed=False
        def load(self,value):self.loaded=value
        def render(self):pass
        def shutdown(self):self.closed=True
    monkeypatch.setattr(module,'CADViewport',View)
    meshes={'_geometry_key':geometry_key(design),'meshes':[]}
    dialog=module.FirmwareMotionDialog(design,item,result,meshes,language='en')
    dialog.slider.setValue(10)
    assert abs(dialog.viewport.actors['stage'][0].GetUserMatrix().GetElement(2,3)-.1)<1e-9
    dialog.toggle();assert dialog.timer.isActive()
    dialog.reject();assert not dialog.timer.isActive() and dialog.viewport.closed
    assert design.model_dump(mode='json')==before
    dialog.deleteLater();app.processEvents()
