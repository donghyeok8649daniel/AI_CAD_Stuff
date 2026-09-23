import numpy as np
import pytest
from cadstudio.catalog import preset
from cadstudio.dynamics import PlanarRobot,RobotSettings,cad_robot,simulate
from cadstudio.tensile import TensileSettings,analyze,specimen_rule,solve_tetrahedra


def robot():
    return PlanarRobot(np.array([1.,.7]),np.array([2.,1.]),np.array([[.5,0],[.35,0]]),np.array([2/12,.7**2/12]),.5,9.80665)


def test_static_gravity_and_positive_mass_matrix():
    r=robot();m,c,g=r.terms([0,0],[0,0]);expected=9.80665*np.array([2*.5+1*(1+.35)+.5*1.7,1*.35+.5*.7])
    assert g==pytest.approx(expected);assert c==pytest.approx([0,0])
    for q in np.linspace(-np.pi,np.pi,20):assert np.min(np.linalg.eigvalsh(r.terms([.3,q],[1,2])[0]))>0
    assert r.acceleration([0,0],[0,0],expected)==pytest.approx([0,0],abs=1e-10)


def test_forward_energy_and_ik():
    r=robot();s=RobotSettings(mode='forward',duration=1,velocity=[20,-10],damping=0)
    result=simulate(r,[.2,-.6],s);assert np.ptp(result['energy'])<1e-6
    target=[.8,.3]
    for elbow in (-1,1):assert r.tip(r.ik(target,elbow))==pytest.approx(target)
    with pytest.raises(ValueError,match='도달'):r.ik([3,0])


def test_cad_mass_includes_attached_pin_and_density_scaling():
    d=preset('robot_arm');a,pair,included=cad_robot(d,RobotSettings(payload=0));b,_,_=cad_robot(d,RobotSettings(payload=0,density=5400))
    assert 'pin-2' in included and 'pin-1' not in included
    assert b.masses==pytest.approx(a.masses*2);assert b.inertias==pytest.approx(a.inertias*2)
    result=simulate(a,np.radians([25,-55]),RobotSettings(target=[60,-90]));assert result['angles'][-1]==pytest.approx([60,-90]);assert result['velocity'][-1]==pytest.approx([0,0],abs=1e-10)


def test_fem_uniform_bar_patch_and_reactions():
    # Six tetrahedra on each cube, uniform uniaxial stress at nu=0 is exact.
    nodes=np.array([(x,y,z) for x in [0,5,10] for y in [0,2] for z in [0,2]],float)
    cells=[]
    for i in range(2):
        base=i*4
        for t in [(0,1,3,7),(0,3,2,7),(0,2,6,7),(0,6,4,7),(0,4,5,7),(0,5,1,7)]:cells.append([base+k for k in t])
    faces=np.array([[8,9,11],[8,11,10]])
    r=solve_tetrahedra(nodes,np.array(cells),[0,1,2,3],faces,200000,0,400)
    assert r['stress'][:,0]==pytest.approx(np.full(len(cells),100),rel=1e-8)
    assert r['displacement'][-1,0]==pytest.approx(400*10/(4*200000),rel=1e-8)
    assert r['reaction']==pytest.approx([-400,0,0],abs=1e-7)


@pytest.mark.parametrize('kind',['flat_specimen','round_specimen'])
def test_specimen_fem_force_balance_and_nominal_gauge(kind):
    d=preset(kind);settings=TensileSettings(part_id=d.parts[0].id);r=analyze(d,settings)
    assert r['reaction']==pytest.approx([-1000,0,0],abs=1e-6)
    assert r['max_displacement_mm']>0
    assert r['gauge_axial_stress_mpa']==pytest.approx(r['nominal_stress_mpa'],rel=.05)
    assert r['energy_nmm']>0
    zero=analyze(d,settings.model_copy(update={'force_n':0}));assert zero['max_stress_mpa']==zero['max_displacement_mm']==0


def test_mark_length_is_distinct_from_parallel_length():
    g=preset('round_specimen').parts[0].geometry
    r=specimen_rule(g,'E8M-5D');assert r['mark_length']==g.gauge_diameter*5 and r['parallel_length']==g.gauge_length
    assert r['certified'] is False
    with pytest.raises(ValueError):specimen_rule(preset('flat_specimen').parts[0].geometry,'E8M-5D')
