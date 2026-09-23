"""Bounded TET4 finite elements for unmodified round/flat tensile specimens.

Coordinates mm, force N, stress MPa. Small strain isotropic linear elasticity.
End traction is integrated over triangles; the opposite grip is clamped.
"""
import math
import numpy as np
from pydantic import Field
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from .models import StrictModel


class TensileSettings(StrictModel):
    part_id: str
    young_gpa: float = Field(default=200,gt=.001,le=2000)
    poisson: float = Field(default=.3,ge=0,le=.45)
    yield_mpa: float = Field(default=250,gt=0,le=100000)
    force_n: float = Field(default=1000,ge=0,le=1e7)
    refinement: int = Field(default=1,ge=1,le=3)


def width_at(g,x):
    small=getattr(g,'gauge_diameter',getattr(g,'gauge_width',0))
    big=getattr(g,'grip_diameter',getattr(g,'grip_width',0))
    s=np.clip((np.abs(x)-g.gauge_length/2)/g.transition_length,0,1)
    return small+(big-small)*(3*s*s-2*s*s*s)


def specimen_mesh(g,refinement=1):
    if g.kind not in ('flat_specimen','round_specimen'):raise ValueError('원통형 / 평판형 인장 시편을 선택하세요.')
    if refinement not in (1,2,3):raise ValueError('메시 단계는 1~3입니다.')
    # Include every profile breakpoint so the neck and grip are not skipped.
    ends=[-g.length/2,-g.gauge_length/2-g.transition_length,-g.gauge_length/2,g.gauge_length/2,g.gauge_length/2+g.transition_length,g.length/2]
    xs=np.unique(np.concatenate([np.linspace(a,b,n*refinement+1) for a,b,n in zip(ends,ends[1:],[3,5,8,5,3])]))
    cross=[];triangles=[]
    if g.kind=='flat_specimen':
        ny,nz=4*refinement,2*refinement
        cross=[(y,z) for z in np.linspace(-g.thickness/2,g.thickness/2,nz+1) for y in np.linspace(-.5,.5,ny+1)]
        for j in range(nz):
            for i in range(ny):
                a=j*(ny+1)+i;b=a+1;c=a+ny+1;d=c+1
                triangles.extend([(a,b,d),(a,d,c)])
    else:
        sectors=16*refinement;rings=refinement+1;cross=[(0,0)]
        for ring in range(1,rings+1):
            for i in range(sectors):cross.append((.5*ring/rings*math.cos(2*math.pi*i/sectors),.5*ring/rings*math.sin(2*math.pi*i/sectors)))
        for i in range(sectors):triangles.append((0,1+i,1+(i+1)%sectors))
        for r in range(1,rings):
            for i in range(sectors):
                a=1+(r-1)*sectors+i;b=1+(r-1)*sectors+(i+1)%sectors;c=1+r*sectors+i;d=1+r*sectors+(i+1)%sectors
                triangles.extend([(a,b,d),(a,d,c)])
    n=len(cross);nodes=[]
    for x in xs:
        w=float(width_at(g,x))
        nodes.extend([(x,y*w,z*w if g.kind=='round_specimen' else z) for y,z in cross])
    tets=[]
    # Consistent diagonal on every shared prism side avoids hanging faces.
    for layer in range(len(xs)-1):
        for triangle in triangles:
            a,b,c=sorted(triangle);a0,b0,c0=[layer*n+k for k in (a,b,c)];a1,b1,c1=[(layer+1)*n+k for k in (a,b,c)]
            tets.extend([(a0,b0,c0,c1),(a0,b0,b1,c1),(a0,a1,b1,c1)])
    nodes=np.array(nodes,dtype=float);tets=np.array(tets,dtype=int)
    return nodes,tets,np.arange(n),np.array(triangles,dtype=int)+(len(xs)-1)*n


def elasticity_matrix(young,poisson):
    lam=young*poisson/((1+poisson)*(1-2*poisson));mu=young/(2*(1+poisson))
    d=np.zeros((6,6));d[:3,:3]=lam;d[np.arange(3),np.arange(3)]+=2*mu;d[3:,3:]=np.eye(3)*mu
    return d


def solve_tetrahedra(nodes,tets,fixed,traction_faces,young,poisson,force):
    nodes=np.asarray(nodes);tets=np.asarray(tets);count=len(nodes)*3
    if count>45000:raise ValueError('메시가 너무 큽니다. 메시 단계를 낮추세요.')
    if not (young>0 and 0<=poisson<.49 and force>=0):raise ValueError('재료 / 하중 범위를 확인하세요.')
    coords=nodes[tets];a=np.concatenate([np.ones((*coords.shape[:2],1)),coords],axis=2);vol=np.abs(np.linalg.det(a))/6
    if np.min(vol)<1e-12:raise ValueError('퇴화된 유한요소가 있습니다. 치수나 메시를 바꾸세요.')
    grad=np.linalg.inv(a)[:,1:,:];b=np.zeros((len(tets),6,12))
    for k in range(4):
        x,y,z=grad[:,:,k].T;j=3*k
        b[:,0,j]=x;b[:,1,j+1]=y;b[:,2,j+2]=z
        b[:,3,j]=y;b[:,3,j+1]=x;b[:,4,j+1]=z;b[:,4,j+2]=y;b[:,5,j]=z;b[:,5,j+2]=x
    d=elasticity_matrix(young,poisson);ke=np.einsum('eai,ab,ebj,e->eij',b,d,b,vol,optimize=True)
    dofs=(3*tets[:,:,None]+np.arange(3)).reshape(-1,12)
    rows=np.broadcast_to(dofs[:,:,None],ke.shape).ravel();cols=np.broadcast_to(dofs[:,None,:],ke.shape).ravel()
    stiffness=coo_matrix((ke.ravel(),(rows,cols)),shape=(count,count)).tocsr()
    xyz=nodes[traction_faces];areas=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)/2
    load=np.zeros(count)
    for corner in range(3):np.add.at(load,3*traction_faces[:,corner],areas*force/areas.sum()/3)
    restrained=(3*np.array(fixed)[:,None]+np.arange(3)).ravel();free=np.setdiff1d(np.arange(count),restrained);u=np.zeros(count)
    if force:u[free]=spsolve(stiffness[free,:][:,free],load[free])
    if not np.isfinite(u).all():raise ValueError('유한요소 해석에 실패했습니다. 고정 조건과 치수를 확인하세요.')
    stress=np.einsum('ab,ebi,ei->ea',d,b,u[dofs],optimize=True);sx,sy,sz,txy,tyz,txz=stress.T
    vm=np.sqrt(.5*((sx-sy)**2+(sy-sz)**2+(sz-sx)**2)+3*(txy*txy+tyz*tyz+txz*txz))
    reaction=stiffness@u-load;imbalance=float(np.linalg.norm(reaction[free]))
    if imbalance>max(1e-6,force*1e-6):raise ValueError('평형 오차가 너무 큽니다. 메시 / 치수를 확인하세요.')
    displacement=u.reshape(-1,3)
    return dict(nodes=nodes,tets=tets,displacement=displacement,stress=stress,von_mises=vm,volumes=vol,reaction=reaction.reshape(-1,3)[fixed].sum(axis=0),force_n=force,energy_nmm=float(.5*u@load),max_displacement_mm=float(np.linalg.norm(displacement,axis=1).max()),max_stress_mpa=float(vm.max()),loaded_area_mm2=float(areas.sum()),equilibrium_error_n=imbalance)


def analyze(design,settings):
    p=next((p for p in design.parts if p.id==settings.part_id),None)
    if p is None:raise ValueError('해석할 시편이 삭제되었습니다.')
    if p.features:raise ValueError('시편 해석은 추가 절삭 / 필렛 없는 기본 시편 형상을 사용합니다.')
    g=p.geometry;nodes,tets,fixed,faces=specimen_mesh(g,settings.refinement)
    result=solve_tetrahedra(nodes,tets,fixed,faces,settings.young_gpa*1000,settings.poisson,settings.force_n)
    area=math.pi*g.gauge_diameter**2/4 if g.kind=='round_specimen' else g.gauge_width*g.thickness
    centers=nodes[tets].mean(axis=1);gauge=np.abs(centers[:,0])<g.gauge_length*.4
    result.update(nominal_stress_mpa=settings.force_n/area,gauge_axial_stress_mpa=float(np.average(result['stress'][gauge,0],weights=result['volumes'][gauge])),yield_exceeded=result['max_stress_mpa']>settings.yield_mpa,safety_factor=settings.yield_mpa/result['max_stress_mpa'] if result['max_stress_mpa']>0 else None,part_name=p.name)
    return result


def specimen_rule(g,rule='custom',mark_length=25):
    if g.kind not in ('round_specimen','flat_specimen'):raise ValueError('인장 시편에서만 표점 길이를 지정할 수 있습니다.')
    if rule not in ('custom','E8-4D','E8M-5D'):raise ValueError('지원하지 않는 표점 규칙입니다.')
    if rule!='custom' and g.kind!='round_specimen':raise ValueError('4D / 5D 규칙은 원통형 시편용입니다.')
    length=mark_length if rule=='custom' else g.gauge_diameter*(4 if rule=='E8-4D' else 5)
    if not math.isfinite(length) or length<=0:raise ValueError('표점 길이는 0보다 커야 합니다.')
    return dict(rule=rule,mark_length=length,parallel_length=g.gauge_length,fits=length<=g.gauge_length,source='https://store.astm.org/e0008_e0008m-25.html' if rule!='custom' else '',certified=False,note='표점 길이만 검사합니다. 전이부 형상·치수 공차·시험 절차의 전체 규격 적합성은 별도 확인이 필요합니다.')
