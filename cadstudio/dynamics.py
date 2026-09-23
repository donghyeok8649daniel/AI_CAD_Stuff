"""SI-unit planar two-revolute-link dynamics, CAD inertia and inverse kinematics.

Rigid links; viscous joint damping; ideal joints. No impact, controller,
elasticity or joint-stop model. See docs/ENGINEERING.md for derivation sources.
"""
from dataclasses import dataclass
import math
import numpy as np
from scipy.integrate import solve_ivp
from pydantic import Field
from .models import StrictModel


class RobotSettings(StrictModel):
    shoulder: str = ''
    density: float = Field(default=2700,gt=0,le=30000)  # kg/m³, all moving CAD bodies
    payload: float = Field(default=.1,ge=0,le=1000)
    gravity: bool = False  # False: horizontal XY; True: vertical plane, gravity -Y
    damping: float = Field(default=.002,ge=0,le=100)
    duration: float = Field(default=2,ge=.02,le=20)
    mode: str = Field(default='inverse',pattern='^(inverse|forward)$')
    target: list[float] = Field(default_factory=lambda:[60,-90],min_length=2,max_length=2)
    torque: list[float] = Field(default_factory=lambda:[0,0],min_length=2,max_length=2)
    velocity: list[float] = Field(default_factory=lambda:[0,0],min_length=2,max_length=2)


@dataclass
class PlanarRobot:
    lengths: np.ndarray
    masses: np.ndarray
    centers: np.ndarray  # COM XY from each proximal pivot, m
    inertias: np.ndarray  # centroidal Izz, kg m²
    payload: float = 0
    gravity: float = 0
    damping: float = 0

    def terms(self,q,v):
        l1,l2=self.lengths;m1,m2=self.masses;(x1,y1),(x2,y2)=self.centers;i1,i2=self.inertias;mp=self.payload
        a,b=q;v1,v2=v;cb,sb=math.cos(b),math.sin(b)
        beta=m2*l1*(x2*cb-y2*sb)+mp*l1*l2*cb
        delta=-m2*l1*(x2*sb+y2*cb)-mp*l1*l2*sb
        j2=i2+m2*(x2*x2+y2*y2)+mp*l2*l2
        matrix=np.array([[i1+m1*(x1*x1+y1*y1)+(m2+mp)*l1*l1+j2+2*beta,j2+beta],[j2+beta,j2]])
        coriolis=np.array([delta*(2*v1*v2+v2*v2),-delta*v1*v1])
        end=(m2*x2+mp*l2)*math.cos(a+b)-m2*y2*math.sin(a+b)
        gravity=self.gravity*np.array([m1*(x1*math.cos(a)-y1*math.sin(a))+(m2+mp)*l1*math.cos(a)+end,end])
        return matrix,coriolis,gravity

    def inverse(self,q,v,acceleration):
        matrix,c,g=self.terms(q,v)
        return matrix@acceleration+c+g+self.damping*np.asarray(v)

    def acceleration(self,q,v,torque):
        matrix,c,g=self.terms(q,v)
        return np.linalg.solve(matrix,np.asarray(torque)-c-g-self.damping*np.asarray(v))

    def tip(self,q):
        return np.array([self.lengths[0]*math.cos(q[0])+self.lengths[1]*math.cos(sum(q)),self.lengths[0]*math.sin(q[0])+self.lengths[1]*math.sin(sum(q))])

    def ik(self,target,elbow=1):
        x,y=np.asarray(target);a,b=self.lengths;c=(x*x+y*y-a*a-b*b)/(2*a*b)
        if abs(c)>1+1e-10:raise ValueError('목표점이 로봇의 도달 범위 밖입니다.')
        q2=elbow*math.acos(np.clip(c,-1,1));q1=math.atan2(y,x)-math.atan2(b*math.sin(q2),a+b*math.cos(q2))
        return np.array([q1,q2])

    def energy(self,q,v):
        m,_,_=self.terms(q,v);a,b=q;l1,l2=self.lengths;m1,m2=self.masses;(x1,y1),(x2,y2)=self.centers
        potential=self.gravity*(m1*(x1*math.sin(a)+y1*math.cos(a))+(m2+self.payload)*l1*math.sin(a)+m2*(x2*math.sin(a+b)+y2*math.cos(a+b))+self.payload*l2*math.sin(a+b))
        return float(.5*np.asarray(v)@m@v+potential)


def chains(design):
    parts={p.id:p for p in design.parts};out=[]
    for a in design.mates:
        if a.kind!='revolute' or parts[a.child].geometry.kind!='link':continue
        for b in design.mates:
            if b.kind=='revolute' and b.parent==a.child and parts[b.child].geometry.kind=='link':out.append((a,b))
    return out


def cad_robot(design,settings):
    from .kernel import local_shape
    from .constraints import transform_matrix,anchors
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    pair=next((c for c in chains(design) if not settings.shoulder or c[0].id==settings.shoulder),None)
    if pair is None:raise ValueError('양단 링크 2개를 회전 관절로 연결한 로봇이 필요합니다.')
    a,b=pair;parts={p.id:p for p in design.parts};links=[parts[a.child],parts[b.child]];base=parts[a.parent]
    if not base.fixed:raise ValueError('동역학의 베이스는 고정해야 합니다.')
    if design.loops:raise ValueError('동역학은 열린 2링크 체인을 지원합니다. 폐루프는 관절 구동에서 해석하세요.')
    if any(f.mate_id in (a.id,b.id) for f in design.joint_frames):raise ValueError('동역학은 구멍 중심 기준의 XY 회전 조인트를 사용하세요.')
    if any(abs(v)>1e-7 for v in (base.transform.rx,base.transform.ry,base.transform.rz,a.rx,a.ry,a.x,a.y,b.rx,b.ry,b.x,b.y)):
        raise ValueError('베이스 회전과 관절의 XY 오프셋을 0으로 두고 XY 평면 체인을 사용하세요.')
    if a.child_anchor!='hole_1_bottom' or b.child_anchor!='hole_1_bottom' or b.parent_anchor!='hole_2_top':
        raise ValueError('링크의 첫 구멍으로 연결하고 팔꿈치는 첫 링크의 두 번째 위쪽 구멍을 사용하세요.')
    lengths=np.array([p.geometry.hole_spacing/1000 for p in links]);masses=[];centers=[];inertias=[];included=[]
    for root,mate in zip(links,pair):
        group={root.id};changed=True
        while changed:
            before=len(group)
            for joint in design.mates:
                if joint.parent in group and joint.kind=='rigid':group.add(joint.child)
            changed=len(group)>before
        if any(j.parent in group and j.kind!='rigid' and j.id!=b.id for j in design.mates):raise ValueError('2링크 외의 움직이는 가지는 동역학에서 지원하지 않습니다.')
        rotation=transform_matrix(root.transform);rootpos=np.array([root.transform.x,root.transform.y,root.transform.z]);pivot=np.array(anchors(root.geometry)[mate.child_anchor]);records=[]
        for identifier in group:
            p=parts[identifier];shape=local_shape(design,p)
            if not shape.Solids():raise ValueError('동역학에는 체적을 갖는 솔리드가 필요합니다.')
            prop=GProp_GProps();BRepGProp.VolumeProperties_s(shape.wrapped,prop);volume=prop.Mass();mass=volume*settings.density*1e-9
            com=prop.CentreOfMass();local=np.array([com.X(),com.Y(),com.Z()]);rp=transform_matrix(p.transform);relative=rotation.T@rp
            center=(rotation.T@(rp@local+np.array([p.transform.x,p.transform.y,p.transform.z])-rootpos)-pivot)/1000
            tensor=prop.MatrixOfInertia();imat=np.array([[tensor.Value(i+1,j+1) for j in range(3)] for i in range(3)])*settings.density*1e-15
            records.append((mass,center,float((relative@imat@relative.T)[2,2])))
        total=sum(m for m,_,_ in records);center=sum(m*c for m,c,_ in records)/total
        inertia=sum(i+m*np.sum((c[:2]-center[:2])**2) for m,c,i in records)
        masses.append(total);centers.append(center[:2]);inertias.append(inertia);included.extend(sorted(group))
    robot=PlanarRobot(lengths,np.array(masses),np.array(centers),np.array(inertias),settings.payload,9.80665 if settings.gravity else 0,settings.damping)
    return robot,pair,included


def simulate(robot,start,settings,samples=201):
    start=np.asarray(start,dtype=float);t=np.linspace(0,settings.duration,samples)
    if settings.mode=='inverse':
        target=np.radians(settings.target);s=t/settings.duration;delta=target-start
        q=start+(10*s**3-15*s**4+6*s**5)[:,None]*delta
        v=(30*s**2-60*s**3+30*s**4)[:,None]*delta/settings.duration
        acceleration=(60*s-180*s**2+120*s**3)[:,None]*delta/settings.duration**2
        torque=np.array([robot.inverse(a,b,c) for a,b,c in zip(q,v,acceleration)])
    else:
        torque=np.tile(settings.torque,(samples,1));calls=0
        def rhs(time,state):
            nonlocal calls
            calls+=1
            if calls>30000 or not np.isfinite(state).all() or np.max(np.abs(state[2:]))>1000:raise ValueError('속도가 너무 높습니다. 토크를 낮추거나 시간을 줄이세요.')
            return np.r_[state[2:],robot.acceleration(state[:2],state[2:],settings.torque)]
        sol=solve_ivp(rhs,(0,settings.duration),np.r_[start,np.radians(settings.velocity)],t_eval=t,rtol=1e-8,atol=1e-10,max_step=settings.duration/200)
        if not sol.success:raise ValueError('시간 적분이 수렴하지 않았습니다: '+sol.message)
        q,v=sol.y[:2].T,sol.y[2:].T
        acceleration=np.array([robot.acceleration(a,b,settings.torque) for a,b in zip(q,v)])
    tip=np.array([robot.tip(a)*1000 for a in q]);energy=[robot.energy(a,b) for a,b in zip(q,v)]
    return dict(time=t.tolist(),angles=np.degrees(q).tolist(),velocity=np.degrees(v).tolist(),acceleration=np.degrees(acceleration).tolist(),torque=torque.tolist(),tip=tip.tolist(),energy=energy,peak_torque=np.max(np.abs(torque),axis=0).tolist(),masses=robot.masses.tolist(),inertias=robot.inertias.tolist(),reach_mm=[abs(np.diff(robot.lengths)[0])*1000,sum(robot.lengths)*1000])
