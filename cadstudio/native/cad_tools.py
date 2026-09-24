"""Transactional, bounded CAD tools for language-model plans; never execute code."""
from copy import deepcopy
import json
import math
from typing import Any, Literal, Annotated

from pydantic import Field, TypeAdapter
from ..models import (StrictModel, Design, Part, Geometry, Transform, Extrusion,
                      SketchFeature, SolidFeature, EdgeFeature, AssemblyMate, Material)
from ..planner import AIReply


class CADAction(StrictModel):
    tool: Literal['create','dimensions','transform','appearance','hole','pocket','pad',
                  'fillet','chamfer','shell','solid','thread','joint','parameter','edit_feature','edit_joint']
    target: str = Field(min_length=1,max_length=40,pattern=r'^[a-zA-Z0-9_-]+$')
    args: dict[str,Any] = Field(default_factory=dict,max_length=24)


class CADCheck(StrictModel):
    target: str = Field(min_length=1,max_length=40)
    size: list[Annotated[float,Field(ge=0)]] | None = Field(default=None,min_length=3,max_length=3)
    x: float | None = Field(default=None,ge=0)
    y: float | None = Field(default=None,ge=0)
    z: float | None = Field(default=None,ge=0)
    volume: float | None = Field(default=None,ge=0)
    solids: int | None = Field(default=None,ge=0,le=256)


class CADPlan(StrictModel):
    construction: list[Annotated[str,Field(min_length=1,max_length=80)]] = Field(default_factory=list,max_length=4)
    checks: list[CADCheck] = Field(default_factory=list,max_length=32)
    name: str = Field(default='AI 설계',min_length=1,max_length=100)
    summary: str = Field(min_length=1,max_length=160)
    assumptions: list[Annotated[str,Field(min_length=1,max_length=120)]] = Field(default_factory=list,max_length=4)
    actions: list[CADAction] = Field(min_length=1,max_length=32)


class ToolReply(AIReply):
    tool_actions: list[dict] = Field(default_factory=list)
    journal_base: dict | None = None
    journal_steps: list[dict] = Field(default_factory=list)
    measurements: list[dict] = Field(default_factory=list)


TOOL_LABELS={'create':'부품 생성','dimensions':'치수 변경','transform':'이동·회전','appearance':'색상·재질',
             'hole':'구멍','pocket':'포켓 절삭','pad':'돌출','fillet':'필렛','chamfer':'모따기',
             'shell':'셸','solid':'솔리드 작업','thread':'나사산','joint':'조립 구속','parameter':'변수','edit_feature':'기존 피처 편집','edit_joint':'관절 자세 편집'}


CATALOG = '''You design CAD models by composing tools, for ANY object the user describes. Return only one compact JSON plan. Never return a complete design file, Python, or a catalogue of unrelated parts. Choose only the operations needed by this request. All lengths are mm, all angles degrees. Respect explicit dimensions. If dimensions are missing choose practical dimensions and list these assumptions in Korean. Existing parts stay untouched unless the user asks to edit them. New IDs must be unique ASCII letters/digits/hyphens. The target is a part ID except joint/edit_joint (joint ID) and parameter (variable name). Each action has tool,target,args. Execute in listed order. At most 32 actions.
For a vague request, start with a minimal useful mechanical concept, normally one body and 1..6 actions. Do not invent decorative details, fillets, spokes or repeated features unless needed or requested. State the chosen dimensions and omitted functional details briefly; the user can refine them. Explicit requested features always take priority over this simplicity preference. construction contains at most 4 short technical fragments, each at most 80 characters. No paragraphs or repeated explanation. summary is at most 160 characters. assumptions contains only necessary choices, at most 4 short items of 120 characters each. The actual dimensions belong in actions, not extended narration.

TOOLS (only these args are accepted):
create: {name,geometry,color?,transform?}. geometry is one of the shapes below. This adds one new editable part; target is its new ID. transform={x,y,z,rx,ry,rz}, defaults zero. Base primitives are centered in XY with bottom at Z=0. Separate independent parts using transform; leave intended assembly positions aligned.
dimensions: {values:{dimension:value,...}}. Patch actual fields of an EXISTING part's base geometry, preserving all other fields. A new create ALREADY includes its dimensions; do not add a redundant dimensions action after create. Never invent fields such as diameter_top on a loft (its dimensions are inside sections). No kind change. Parameter-bound dimensions must be edited using parameter instead.
edit_feature: {feature_id,...changed_fields}. Edit an EXISTING feature, keeping its ID, support faces and downstream history. Use its actual editable fields and dimensions from current_design. depth edits sketch extrusion/cut depth; for a blind hole specify through_all=false AND depth. diameter edits a circular sketch profile; entity_id is mandatory when there is more than one circle, use one action per circle. This can SHRINK an existing hole by rebuilding its original cut; do not add a new hole on top. size is edge radius/chamfer distance or shell thickness; thread uses pitch,length,offset,clearance,handedness,reverse. Pattern uses count,count_y,spacing or angle as listed in editable. suppressed=true disables a feature reversibly, false restores it; dependent features must remain valid. name renames it. Do not change IDs, support references or operation types. A variable-driven field needs parameter instead; a linked profile needs its original sketch edited manually. Do not guess which feature when the request is ambiguous; selected_feature identifies the user's current feature selection.
transform: {x?,y?,z?,rx?,ry?,rz?}. Set absolute placement, unspecified coordinates preserved. Joint-driven parts accept only an already-satisfied placement; set joint offsets when creating the joint instead of moving its child afterward.
appearance: {color?:"#RRGGBB",name?,material?:{name,density,youngs_modulus,poisson}}.
hole: {face:"+Z",diameter,centers?:[[u,v],...],pattern?:PATTERN,depth?:number,through_all?:true,finish?:"plain"|"counterbore"|"countersink",head_diameter?,head_depth?,head_angle?}. Use centers OR pattern, never both. For symmetric repeated holes PREFER pattern; CAD computes exact positions. PATTERN is {kind:"rectangular",count_x:2,count_y:2,spacing_x:60,spacing_y:40,center:[0,0]} OR {kind:"circular",count:6,diameter:50,start_angle:0,center:[0,0]}. Rectangular pattern is CENTERED on center, spacing is between adjacent holes. Circular diameter is the bolt circle diameter. Default single center=[[0,0]], through_all=true. u,v are coordinates in the selected face frame about its CENTER. For +Z, u=X and v=Y. Other faces: u is projected X (or Y on ±X faces), v=normal cross u. Never specify face indices.
pocket or pad: {face,profile,depth,through_all?:false}. profile is a 2D profile as below in the face frame. pad adds material outward AND AUTOMATICALLY FUSES it to the body. pocket removes material inward: a circular pocket produces a BORE, never a smaller solid outside diameter. To reduce external diameter by cutting, remove an annulus, not its inner disk. Prefer a circular pad to build a smaller solid section on top.
fillet or chamfer: {size,edges?:"all"|"+Z"|"-Z"|"+X"|"-X"|"+Y"|"-Y"}. A face direction selects the edges bordering that face. Use small radii that fit the material; do these last.
shell: {thickness,open_faces?:["+Z"]}. Removes selected faces and hollows inward. Wall must be less than half the smallest dimension.
solid: Modify an EXISTING solid ONLY when mirror/pattern/split/draft or boolean is requested. Creating a solid body (e.g. loft solid=true) does NOT require this tool. {operation:"mirror"|"linear_pattern"|"circular_pattern"|"split"|"draft"|"boolean", ...}. mirror: origin=[0,0,0],direction=[1,0,0],keep_original=true. linear_pattern: count,spacing=[dx,dy,dz],count_y=1. circular_pattern: count,angle=360,origin=[0,0,0],direction=[0,0,1]. split: origin,direction,keep_side="positive"|"negative"|"all". draft: angle,faces=["+X"],origin,direction. boolean: tool_part_id,boolean_mode="union"|"cut"|"intersect" (tool part remains as an editable reference; do not create unused tools).
thread: {diameter,pitch,length,internal?:false,offset?:0,handedness?:"right"|"left",clearance?:0}. Selects the cylindrical face matching diameter (or internal pilot bore). Length 1..32 pitches, must fit the cylinder. Not cosmetic: creates actual thread geometry.
joint: {kind:"rigid"|"revolute"|"slider"|"cylindrical"|"ball"|"planar"|"pin_slot",parent,child,parent_anchor?:"origin",child_anchor?:"origin",x?,y?,z?,rx?,ry?,rz?,limits?:{rz:[minimum,maximum]}}. For revolute use rz limits in degrees (e.g. {rz:[-90,90]}), for slider use z limits in mm. Omit limits when no range was requested. Both anchors must be "origin"; use offsets for another location. target=new joint ID. Parent/child are existing part IDs. Offsets relative to parent. Makes parent fixed if it has no parent joint. Do not join a part to itself.
edit_joint: {x?,y?,z?,rx?,ry?,rz?}. target=EXISTING JOINT ID, never a part ID. Set absolute joint coordinates ONLY on its independent motion_axes, with mm or degrees as listed. For 'increase by' add to the current value first. Frame is the existing joint coordinate frame, not global XYZ. Existing limits, face frames, anchors, motion links and parent/child are preserved. Never transform a joint-driven child to move its joint. An axis marked driven_by must be moved using its driving joint instead; passive loop joints are solved automatically. Cannot alter connection kind or limits. selected_joint identifies the user's selected joint; when only selected_part is given find its parent joint by child ID. Do not claim a collision-free motion path; validation checks the final pose only.
parameter: {value:"expression"}. target=parameter name; update/add a dimension variable. Existing dimension bindings use the new value.

SHAPES for create.geometry (kind and dimensions only, no tool/target inside geometry):
cylinder: {kind:"cylinder",diameter,height,bore_diameter?:0}. Axial bore must be < diameter-0.2. bore_diameter already CUTS the center hole: never drill that same hole again. Disk, shaft, tube, wheel, spacer are combinations of this and other tools, not separate kinds.
plate: {kind:"plate",length,width,thickness,hole_count:0}. Use hole for precisely positioned holes. This is also a rectangular block.
extrusion: {kind:"extrusion",thickness,profile:PROFILE}. Example: {kind:"extrusion",thickness:6,profile:{points:[{x:0,y:0},{x:30,y:0},{x:30,y:10},{x:0,y:10}]}}. Arbitrary closed planar shape, not limited to named products. Optional taper (-60..60),symmetric,thin_wall.
revolve: PREFER {kind:"revolve",segments:[{length:15,diameter:24},{length:8,diameter:14}],bore_diameter?:0,angle:360}. Each segment has CONSTANT outside diameter over its length; CAD joins them into ONE solid about Z. Optional end_diameter makes that segment a taper. Total height is sum of lengths. This creates solid outside material, not a bore. Alternative stations form: {kind:"revolve",stations:[[z,OUTSIDE_DIAMETER],...],bore_diameter?:0,angle:360}. Stations ordered bottom to top; repeat z for an abrupt shoulder (e.g. [[0,24],[15,24],[15,14],[23,14]]); differing diameter at differing z makes a taper, NOT a step. Arbitrary axis/profile form: {kind:"revolve",profile:{sketch:PROFILE,frame?:FRAME},axis_start:[0,0,0],axis_direction:[0,1,0],angle:360}; profile must stay on ONE side of the axis.
sweep: {kind:"sweep",profile:{sketch:PROFILE},path:{points:[[x,y,z],...],smooth:true},solid:true,align_profile:true}. Circle radius must fit bends; use gentle curves.
loft: {kind:"loft",sections:[{sketch:PROFILE,frame:FRAME},...],solid:true,ruled:false}. A simple Z-section may be written {z:0,profile:{circle:{diameter:40}}} or {z:50,profile:{circle:{diameter:20}}}; CAD computes the frame and radius. 2..8 sections, ordered along path, matching profile topology. One create contains all sections, NOT separate parts. Set solid=false only for requested surfaces.
bracket: {kind:"bracket",length,width,height,thickness,hole_diameter,hole_inset}. Built-in L bracket with holes. thickness<min(length,height)/2; hole_diameter<width/2-0.2; hole_inset>hole_diameter/2+0.1; hole_inset+hole_diameter/2+thickness<min(length,height)-0.1. For other brackets use extrusion, pad, holes.
link: {kind:"link",length,width,thickness,hole_diameter,hole_spacing}. Rounded link with two holes. length>width; hole_spacing<=length-width and >hole_diameter+0.2; hole_diameter<width-0.2.
sheetmetal: {kind:"sheetmetal",length,width,flange_length,thickness,bend_radius,bend_angle,k_factor:0.5}. Single bend sheet.
round_specimen: {kind:"round_specimen",length,gauge_length,grip_diameter,gauge_diameter,transition_length}. gauge_diameter<grip_diameter; gauge_length+2*transition_length<length-0.02.
flat_specimen: {kind:"flat_specimen",length,gauge_length,grip_width,gauge_width,thickness,transition_length}. Same length rule; gauge_width<grip_width.
PROFILE: simplest circle {circle:{diameter:12,center:[0,0]}}; simplest rectangle {rectangle:{width:20,height:10,center:[0,0]}}. Center defaults[0,0]. Or {points:[{x,y},...]} (3..32 vertices, no repeated closing vertex, no self-intersections) or {sketch_mode:"entities",entities:[{id,kind:"circle",center:{x,y},radius}]}. Multiple circles can make holes. Analytic closed chains of line(start/end),arc(center/radius/start_angle/sweep),ellipse(center/radius_x/radius_y),spline(points,closed:true) also work. thickness defaults 8 in a profile and is overridden by pad/pocket depth. Never include "kind":"PROFILE".
FRAME: {origin:[x,y,z],normal:[0,0,1],x_direction:[1,0,0]} (orthogonal unit vectors).

General method: first write construction as a SHORT list of the actual dimensions and necessary operations (not hidden reasoning). Then write those actions. Target MUST exactly match the ID of a preceding create or an existing part. Reuse the SAME spelling. ONE connected part should normally be ONE create followed by pad/pocket/hole features on it. Add material with pad, remove material with pocket. Never cut away material just to join two parts. Use transform ONLY for actual placement changes. No unnecessary appearance or transform steps. A complex object may be a simplified mechanical concept; clearly state simplifications and unresolved functional details. Never call an approximation certified or fully engineered. Do not silently drop requested holes or features. Feature faces use +X/-X/+Y/-Y/+Z/-Z in PART LOCAL coordinates. An invalid step returns a precise error for you to fix; return a corrected whole plan preserving the original request, never unrelated parts.
Short generic construction examples (adapt ALL dimensions to the request):
- Add a circular boss to a body: create cylinder diameter=24,height=15 then pad on SAME target, face="+Z",depth=8,profile={sketch_mode:"entities",entities:[{id:"c",kind:"circle",center:{x:0,y:0},radius:7}]}. Total height=23. No pockets, joints or second part.
- Transition between circular sections: ONE create geometry={kind:"loft",sections:[{sketch:{sketch_mode:"entities",entities:[{id:"c",kind:"circle",center:{x:0,y:0},radius:15}]},frame:{origin:[0,0,0],normal:[0,0,1],x_direction:[1,0,0]}},{sketch:{sketch_mode:"entities",entities:[{id:"c",kind:"circle",center:{x:0,y:0},radius:9}]},frame:{origin:[0,0,35],normal:[0,0,1],x_direction:[1,0,0]}}],solid:true}. Do not create separate cylinder parts or a joint for loft sections.
'''


def context(design):
    if not design:return None
    from .cad_feature_edits import summary
    from ..assembly_motion import motion_controls
    raw=dict(mates=[m.model_dump() for m in design.mates],loops=[m.model_dump() for m in design.loops],motion_links=[m.model_dump() for m in design.motion_links])
    # Never include imported binary assets, display meshes, history or the full schema.
    return dict(name=design.name,parameters=design.parameters,
                parts=[dict(id=p.id,name=p.name,geometry=p.geometry.model_dump(exclude_none=True),
                            kind=p.geometry.kind,transform=p.transform.model_dump(),
                            features=[summary(f) for f in p.features],
                            source_part_id=p.source_part_id) for p in design.parts],
                mates=[dict(**m.model_dump(exclude_defaults=True),motion_axes=motion_controls(raw,m.id)) for m in design.mates],
                dimension_bindings=[b.model_dump() for b in design.dimension_bindings])


def messages(request):
    return [dict(role='system',content=CATALOG),dict(role='user',content=json.dumps(
        dict(prompt=request.prompt,selected_part=request.selected_part,selected_feature=request.selected_feature,selected_joint=request.selected_joint,current_design=context(request.current)),
        ensure_ascii=False,separators=(',',':')))]


def _keys(args,allowed,required=()):
    extra=set(args)-set(allowed);missing=set(required)-set(args)
    if extra:raise ValueError('허용되지 않는 인자: '+', '.join(sorted(extra)))
    if missing:raise ValueError('필수 인자 누락: '+', '.join(sorted(missing)))


def _part(raw,identifier):
    part=next((p for p in raw['parts'] if p['id']==identifier),None)
    if part is None:raise ValueError(f'부품 {identifier} 없음. 사용 가능: '+', '.join(p['id'] for p in raw['parts']))
    return part


def _shape(raw,identifier):
    from ..kernel import local_shape
    design=Design.model_validate(raw)
    return local_shape(design,next(p for p in design.parts if p.id==identifier))


def _face(shape,selector):
    from ..kernel import face_frame
    axes={'+X':(1,0,0),'-X':(-1,0,0),'+Y':(0,1,0),'-Y':(0,-1,0),'+Z':(0,0,1),'-Z':(0,0,-1)}
    if selector not in axes:raise ValueError('면 방향은 +X, -X, +Y, -Y, +Z, -Z 중 하나여야 합니다.')
    direction=axes[selector];found=[]
    for index,face in enumerate(shape.Faces()):
        if face.geomType()!='PLANE':continue
        if sum(a*b for a,b in zip(face.normalAt().toTuple(),direction))>.999:
            found.append((sum(a*b for a,b in zip(face.Center().toTuple(),direction)),face.Area(),index,face))
    if not found:raise ValueError(f'{selector} 방향 평면이 없습니다. 다른 방향 또는 다른 작업을 선택하세요.')
    # Outermost face, largest area when coplanar. No LLM-generated topology IDs.
    _,_,index,face=max(found,key=lambda x:(round(x[0],5),x[1]))
    return index,face,face_frame(face)


def _feature_id(part):
    used={f['id'] for f in part['features']};number=1
    while f'ai-feature-{number}' in used:number+=1
    return f'ai-feature-{number}'


def _profile(value):
    """Accept a named profile wrapper and normalize exact, equivalent syntax only."""
    if not isinstance(value,dict):raise ValueError('profile은 points 또는 entities를 가진 객체여야 합니다.')
    data=deepcopy(value)
    for primitive in ('circle','rectangle'):
        if primitive not in data:continue
        spec=data.pop(primitive)
        if not isinstance(spec,dict):raise ValueError(primitive+' profile must be an object.')
        if any(k in data for k in ('circle','rectangle','points','entities','profile')):raise ValueError('Use only one profile representation.')
        _keys(spec,('diameter','center') if primitive=='circle' else ('width','height','center'),('diameter',) if primitive=='circle' else ('width','height'))
        center=spec.get('center',[0,0])
        if not isinstance(center,list) or len(center)!=2:raise ValueError('Profile center must be [x,y].')
        x,y=center
        if primitive=='circle':
            if not isinstance(spec['diameter'],(int,float)) or not math.isfinite(spec['diameter']) or spec['diameter']<=0:raise ValueError('Circle diameter must be positive and finite.')
            data.update(sketch_mode='entities',entities=[dict(id='circle',kind='circle',center=dict(x=x,y=y),radius=spec['diameter']/2)])
        else:
            w,h=spec['width'],spec['height']
            if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (w,h)):raise ValueError('Rectangle width and height must be positive and finite.')
            data['points']=[dict(x=x+dx*w/2,y=y+dy*h/2) for dx,dy in ((-1,-1),(1,-1),(1,1),(-1,1))]
    if 'profile' in data:
        inner=_profile(data.pop('profile'))
        if inner.get('kind')=='extrusion':inner.pop('kind')
        if set(inner)&set(data)-{'kind'}:raise ValueError('단면 필드를 profile 안과 밖에 중복해서 지정하지 마세요.')
        data={**inner,**data}
    if data.get('kind') in ('profile','PROFILE'):data.pop('kind')
    if data.get('points'):
        data['points']=[dict(x=p[0],y=p[1]) if isinstance(p,list) and len(p)==2 else p for p in data['points']]
        if len(data['points'])>3 and data['points'][0]==data['points'][-1]:data['points'].pop()
    if not data.get('points') and not data.get('entities'):raise ValueError('닫힌 단면의 points 또는 entities를 명시하세요. 기본 예제 단면으로 대체하지 않습니다.')
    if data.get('entities'):data.setdefault('sketch_mode','entities')
    return data


def _geometry(value):
    if not isinstance(value,dict):raise ValueError('geometry는 형상 객체여야 합니다.')
    data=deepcopy(value);kind=data.get('kind')
    def section(value):
        if not isinstance(value,dict):raise ValueError('단면은 sketch와 frame을 가진 객체여야 합니다.')
        value=deepcopy(value)
        if 'z' in value:
            _keys(value,('z','profile'),('z','profile'))
            return dict(sketch=_profile(value['profile']),frame=dict(origin=[0,0,value['z']],normal=[0,0,1],x_direction=[1,0,0]))
        if 'sketch' in value:value['sketch']=_profile(value['sketch']);return value
        frame=value.pop('frame',None);result=dict(sketch=_profile(value))
        if frame is not None:result['frame']=frame
        return result
    if kind=='revolve' and 'segments' in data:
        _keys(data,('kind','segments','bore_diameter','angle'),('segments',))
        segments=data.pop('segments')
        if not isinstance(segments,list) or not 1<=len(segments)<=14:raise ValueError('Revolve needs 1..14 segments of length and outside diameter.')
        z=0;stations=[]
        for segment in segments:
            if not isinstance(segment,dict):raise ValueError('Each segment must contain length and diameter.')
            _keys(segment,('length','diameter','end_diameter'),('length','diameter'))
            length=segment['length'];diameter=segment['diameter'];end=segment.get('end_diameter',diameter)
            if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (length,diameter,end)):raise ValueError('Segment lengths and diameters must be finite and positive.')
            if not stations or stations[-1]!=[z,diameter]:stations.append([z,diameter])
            z+=length;stations.append([z,end])
        data['stations']=stations
    if kind=='revolve' and 'stations' in data:
        _keys(data,('kind','stations','bore_diameter','angle'),('stations',))
        stations=data['stations'];bore=data.get('bore_diameter',0)
        if not isinstance(stations,list) or not 2<=len(stations)<=28:raise ValueError('Revolve needs 2..28 [z,outside_diameter] stations.')
        if not isinstance(bore,(int,float)) or not math.isfinite(bore) or bore<0:raise ValueError('Bore diameter must be finite and nonnegative.')
        for s in stations:
            if not isinstance(s,list) or len(s)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in s):raise ValueError('Each station is finite [z,outside_diameter].')
            if s[1]<=bore:raise ValueError('Every outside diameter must exceed the bore diameter.')
        if stations[-1][0]<=stations[0][0] or any(b[0]<a[0] for a,b in zip(stations,stations[1:])):raise ValueError('Stations must progress from bottom to top along Z.')
        points=[dict(x=bore/2,y=stations[0][0])]+[dict(x=d/2,y=z) for z,d in stations]+[dict(x=bore/2,y=stations[-1][0])]
        data=dict(kind='revolve',profile=dict(sketch=dict(points=points),frame=dict(origin=[0,0,0],normal=[0,-1,0],x_direction=[1,0,0])),axis_start=[0,0,0],axis_direction=[0,0,1],angle=data.get('angle',360))
    if kind=='extrusion':data=_profile(data)
    elif kind in ('sweep','revolve'):
        if 'profile' not in data:raise ValueError('회전·스윕 단면 profile을 명시하세요.')
        data['profile']=section(data['profile'])
    elif kind=='loft':
        if 'sections' not in data:raise ValueError('로프트 sections에 두 개 이상의 단면을 명시하세요.')
        data['sections']=[section(s) for s in data['sections']]
    return data


def hole_centers(args):
    """Expand dimensioned patterns; the model need not perform coordinate math."""
    if 'pattern' not in args:return args.get('centers',[[0,0]])
    if 'centers' in args:raise ValueError('centers와 pattern 중 하나만 지정하세요.')
    pattern=args['pattern']
    if not isinstance(pattern,dict):raise ValueError('pattern은 종류와 간격을 가진 객체여야 합니다.')
    kind=pattern.get('kind');center=pattern.get('center',[0,0])
    def finite(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if not isinstance(center,list) or len(center)!=2 or not all(finite(v) for v in center):raise ValueError('패턴 중심은 유한한 [u,v] 좌표여야 합니다.')
    def count(key):
        n=pattern.get(key)
        if not isinstance(n,int) or isinstance(n,bool) or not 1<=n<=32:raise ValueError(key+' 개수는 1~32의 정수여야 합니다.')
        return n
    if kind=='rectangular':
        _keys(pattern,('kind','center','count_x','count_y','spacing_x','spacing_y'),('count_x','count_y','spacing_x','spacing_y'))
        nx,ny=count('count_x'),count('count_y');dx,dy=pattern['spacing_x'],pattern['spacing_y']
        if nx*ny>32:raise ValueError('구멍 패턴은 최대 32개입니다.')
        if not all(finite(v) and v>=0 for v in (dx,dy)) or (nx>1 and dx<=0) or (ny>1 and dy<=0):raise ValueError('반복되는 방향의 간격은 양수여야 합니다.')
        return [[center[0]+(x-(nx-1)/2)*dx,center[1]+(y-(ny-1)/2)*dy] for y in range(ny) for x in range(nx)]
    if kind=='circular':
        _keys(pattern,('kind','center','count','diameter','start_angle'),('count','diameter'))
        n=count('count');diameter=pattern['diameter'];angle=pattern.get('start_angle',0)
        if not finite(diameter) or diameter<=0 or not finite(angle):raise ValueError('볼트 원 지름은 양수, 시작 각도는 유한한 수여야 합니다.')
        return [[center[0]+diameter/2*math.cos(math.radians(angle)+i*2*math.pi/n),center[1]+diameter/2*math.sin(math.radians(angle)+i*2*math.pi/n)] for i in range(n)]
    raise ValueError('pattern.kind는 rectangular 또는 circular이어야 합니다.')


def _apply(raw,action):
    tool=action.tool;args=deepcopy(action.args);target=action.target
    if tool=='edit_joint':
        from ..assembly_motion import set_joint_motion
        set_joint_motion(raw,target,args);return
    if tool=='create':
        _keys(args,('name','geometry','color','transform'),('name','geometry'))
        if any(p['id']==target for p in raw['parts']):raise ValueError('새 부품 ID가 이미 존재합니다. 수정은 dimensions를 사용하세요.')
        args['geometry']=_geometry(args['geometry'])
        # A rectangular block does not accidentally inherit the plate preset's holes.
        if args['geometry'].get('kind')=='plate':args['geometry'].setdefault('hole_count',0)
        raw['parts'].append(Part(id=target,**args).model_dump());return
    if tool=='parameter':
        _keys(args,('value',),('value',))
        if not isinstance(args['value'],str):raise ValueError('변수 값은 치수 식 문자열이어야 합니다.')
        raw.setdefault('parameters',{})[target]=args['value'];return
    if tool=='joint':
        _keys(args,set(AssemblyMate.model_fields)-{'id'},('kind','parent','child'))
        if any(m['id']==target for m in raw['mates']):raise ValueError('조인트 ID가 이미 존재합니다.')
        raw['mates'].append(AssemblyMate(id=target,**args).model_dump())
        parent=_part(raw,args['parent'])
        if not any(m['child']==parent['id'] for m in raw['mates']):parent['fixed']=True
        return
    part=_part(raw,target)
    if tool=='dimensions':
        _keys(args,('values',),('values',));values=args['values']
        if not isinstance(values,dict) or not values:raise ValueError('values에 변경할 치수를 넣으세요.')
        if part.get('source_part_id') or part.get('profile_sketch_id'):raise ValueError('연결된 부품은 원본 부품 또는 스케치에서 치수를 수정해야 합니다.')
        forbidden=set(values)-set(part['geometry'])|({'kind'}&set(values))
        if forbidden:raise ValueError('수정할 수 없는 치수: '+', '.join(sorted(forbidden))+'. Available geometry fields: '+', '.join(sorted(set(part['geometry'])-{'kind'}))+'. Do not invent fields. Omit redundant dimensions already included in create.')
        from .cad_feature_edits import check_replacement_bindings
        check_replacement_bindings(raw,part['geometry'],values)
        part['geometry']=TypeAdapter(Geometry).validate_python({**part['geometry'],**values}).model_dump();return
    if tool=='transform':
        _keys(args,Transform.model_fields)
        desired=Transform.model_validate({**part['transform'],**args}).model_dump()
        driving=next((m for m in raw['mates'] if m['child']==target),None)
        if driving:
            if all(math.isclose(value,part['transform'][key],rel_tol=0,abs_tol=1e-9) for key,value in desired.items()):
                return dict(outcome='already_satisfied',detail='조립 구속이 이미 요청한 위치를 유지합니다. 구속과 부품 위치를 보존했습니다.')
            raise ValueError('관절이 위치를 구속한 부품입니다. '+
                f'Joint {driving["id"]} drives {target}; current placement is {part["transform"]}. '+
                'Remove this transform action. For a new joint, set its offsets in the joint action instead. Do not break an existing joint to reposition its child.')
        part['transform']=desired;return
    if tool=='appearance':
        _keys(args,('name','color','material'))
        part.update(args);Part.model_validate(part);return
    if part.get('source_part_id'):raise ValueError('연결 복제의 피처는 원본 부품에서 수정하세요.')
    if tool=='edit_feature':
        from .cad_feature_edits import apply
        return apply(raw,part,args)
    shape=_shape(raw,target);identifier=_feature_id(part)
    support=part['features'][-1]['id'] if part['features'] else 'base'
    common=dict(id=identifier,support_feature=support)
    from ..topology import face_reference
    if tool in ('hole','pocket','pad'):
        allowed=('face','diameter','centers','pattern','depth','through_all','finish','head_diameter','head_depth','head_angle') if tool=='hole' else ('face','profile','depth','through_all')
        _keys(args,allowed,('face','diameter') if tool=='hole' else ('face','profile','depth'))
        index,face,frame=_face(shape,args['face'])
        if tool=='hole':
            centers=hole_centers(args)
            if not isinstance(centers,list) or not 1<=len(centers)<=32:raise ValueError('구멍 중심은 1~32개여야 합니다.')
            if not all(isinstance(p,list) and len(p)==2 for p in centers):raise ValueError('구멍 중심은 [u,v] 좌표 목록입니다.')
            if not isinstance(args['diameter'],(int,float)) or not .01<=args['diameter']<=2000:raise ValueError('구멍 지름은 0.01~2000 mm입니다.')
            if any(math.dist(a,b)<=args['diameter']+1e-6 for i,a in enumerate(centers) for b in centers[i+1:]):raise ValueError('구멍 중심이 중복되거나 구멍끼리 겹칩니다. 슬롯은 pocket을 사용하세요.')
            profile=dict(sketch_mode='entities',profiles=list(range(len(centers))),entities=[dict(id=f'hole-{i}',kind='circle',center=dict(x=p[0],y=p[1]),radius=args['diameter']/2) for i,p in enumerate(centers)])
        else:profile=_profile(args['profile'])
        profile['thickness']=args.get('depth',10)
        sketch=Extrusion.model_validate(profile)
        if tool=='hole':
            import cadquery as cq
            from ..kernel import exact_bounds
            from ..threads import cylinder_records
            bounds=exact_bounds(shape)
            depth=max(-(cq.Vector(x,y,z)-frame.origin).dot(frame.zDir) for x in (bounds.xmin,bounds.xmax) for y in (bounds.ymin,bounds.ymax) for z in (bounds.zmin,bounds.zmax)) if args.get('through_all',True) else sketch.thickness
            retained=[];existing=[]
            for center in centers:
                position=frame.toWorldCoords(tuple(center));cutter=cq.Solid.makeCylinder(args['diameter']/2,depth+.0001,position,-frame.zDir)
                if shape.intersect(cutter).Volume()<1e-7:
                    matched=False
                    for ref in cylinder_records(shape):
                        if not ref.internal or abs(ref.diameter-args['diameter'])>1e-5:continue
                        axis=cq.Vector(*ref.frame.normal);delta=cq.Vector(*ref.frame.origin)-position
                        if abs(abs(axis.dot(frame.zDir))-1)>1e-5 or (delta-frame.zDir.multiply(delta.dot(frame.zDir))).Length>1e-5:continue
                        a=delta.dot(-frame.zDir);b=a+ref.length*axis.dot(-frame.zDir)
                        if min(a,b)<1e-5 and max(a,b)>=depth-1e-5:matched=True;break
                    if not matched:
                        corners=[frame.toLocalCoords(cq.Vector(x,y,z)) for x in (bounds.xmin,bounds.xmax) for y in (bounds.ymin,bounds.ymax) for z in (bounds.zmin,bounds.zmax)]
                        limits=f'u=[{min(p.x for p in corners):g},{max(p.x for p in corners):g}], v=[{min(p.y for p in corners):g},{max(p.y for p in corners):g}]'
                        raise ValueError(f'구멍 중심 {center}가 재료에 닿지 않아 부피 변화가 없습니다. 이미 있는 구멍보다 작은 지름의 절삭도 불가능합니다. '
                                         f'Hole center {center} cuts no material. Face coordinates are CENTERED, not measured from a corner; enclosing bounds: {limits}. '
                                         'First check existing base bores and previous cuts. If the requested opening already exists, REMOVE this redundant hole action; do not move it elsewhere or add a pattern. '
                                         'Only when the ORIGINAL request explicitly asks for symmetric multiple holes, use a rectangular/circular pattern with exactly its requested count and spacings. Do not invent extra openings.')
                    if args.get('finish','plain')=='plain':existing.append(center);continue
                retained.append(center)
            if not retained:return dict(outcome='already_satisfied',detail='같은 위치·지름·깊이의 구멍이 이미 있습니다. 실제 원통 면으로 확인했습니다.')
            sketch=Extrusion(sketch_mode='entities',thickness=sketch.thickness,profiles=list(range(len(retained))),entities=[dict(id=f'hole-{i}',kind='circle',center=dict(x=p[0],y=p[1]),radius=args['diameter']/2) for i,p in enumerate(retained)])
        feature=SketchFeature(**common,name={'hole':'AI 구멍','pocket':'AI 포켓','pad':'AI 돌출'}[tool],
            face=index,support_face_count=len(shape.Faces()),reference=face_reference(shape,index),
            normal=list(frame.zDir.toTuple()),origin=list(frame.origin.toTuple()),x_direction=list(frame.xDir.toTuple()),
            operation='add' if tool=='pad' else 'cut',sketch=sketch,
            through_all=args.get('through_all',tool=='hole'),hole_finish=args.get('finish','plain'),
            **{k:args[k] for k in ('head_diameter','head_depth','head_angle') if k in args})
    elif tool in ('fillet','chamfer'):
        _keys(args,('size','edges'),('size',))
        from ..advanced_geometry import edge_records
        selected=shape.Edges() if args.get('edges','all')=='all' else _face(shape,args['edges'])[1].Edges()
        indices={i for i,e in enumerate(shape.Edges()) if any(e.isSame(s) for s in selected)}
        refs=[{k:v for k,v in e.items() if k!='points'} for e in edge_records(shape) if e['index'] in indices]
        feature=EdgeFeature(**common,kind=tool,name='AI '+tool,size=args['size'],edges=refs,support_edge_count=len(shape.Edges()))
    elif tool in ('shell','solid'):
        if tool=='shell':
            _keys(args,('thickness','open_faces'),('thickness',))
            if not isinstance(args['thickness'],(int,float)) or args['thickness']<=0:raise ValueError('벽 두께는 양수여야 합니다.')
            fields=dict(operation='shell',size=args['thickness'],faces=[face_reference(shape,_face(shape,f)[0]) for f in args.get('open_faces',['+Z'])])
        else:
            _keys(args,set(SolidFeature.model_fields)-{'id','kind','name','support_feature','suppressed'},('operation',))
            fields=args
            if fields['operation']=='shell':raise ValueError('속 비우기는 shell 도구를 사용하세요.')
            if 'faces' in fields:fields['faces']=[face_reference(shape,_face(shape,f)[0]) for f in fields['faces']]
        feature=SolidFeature(**common,name='AI '+fields['operation'],**fields)
    elif tool=='thread':
        from ..threads import cylinder_records
        from ..models import ThreadFeature
        _keys(args,('diameter','pitch','length','internal','offset','handedness','clearance'),('diameter','pitch','length'))
        internal=args.pop('internal',False);diameter=args['diameter'];pitch=args['pitch']
        candidates=[r for r in cylinder_records(shape) if r.internal==internal and
                    (diameter-1.082532*pitch-.15<=r.diameter<diameter-.05 if internal else abs(r.diameter-diameter)<1e-4)]
        if len(candidates)!=1:raise ValueError('나사를 만들 원통 면을 하나로 정할 수 없습니다. 지름 또는 부품 구성을 확인하세요.')
        feature=ThreadFeature(**common,name='AI 나사산',cylinder=candidates[0],**args)
    else:raise ValueError('지원하지 않는 CAD 도구입니다.')
    part['features'].append(feature.model_dump())


def execute_plan(content,request,*,check=lambda:None,progress=lambda text:None,single_part=False):
    """Apply to a copy; an error never leaks a partial draft into the document."""
    from ..kernel import build
    from .document import differences
    payload=json.loads(content)
    if not isinstance(payload,dict):raise ValueError('Return a CAD plan object.')
    single_part=single_part or 'base' in payload
    if single_part:
        base=payload.pop('base',None);features=payload.get('actions',[])
        if not isinstance(base,dict) or base.get('tool')!='create':raise ValueError('Single-part output requires ONE base create object, followed by feature actions. Do not create separate walls or sections.')
        if not isinstance(features,list) or any(not isinstance(a,dict) or a.get('tool') in ('create','joint','edit_joint') or (a.get('target')!=base.get('target') and a.get('tool')!='parameter') for a in features):
            raise ValueError('Single-part actions must modify the SAME base target; no separate creates or joints. Use shell/pocket to remove material, pad to fuse material.')
        payload['actions']=[base]+features
    plan=CADPlan.model_validate(payload)
    raw=deepcopy(request.current.model_dump()) if request.current else Design(name=plan.name,mode=request.mode).model_dump()
    before=deepcopy(raw);steps=[];journal_steps=[]
    for number,action in enumerate(plan.actions,1):
        check();progress(f'CAD 작업 {number}/{len(plan.actions)} · {TOOL_LABELS[action.tool]} · {action.target}')
        try:
            step_before=deepcopy(raw);outcome=_apply(raw,action) or {}
            design=Design.model_validate(raw)
            # Validate exact shapes, not just schema; no meshing between steps.
            shapes=build(design)
            if any(not s.isValid() or not s.Faces() for s in shapes):raise ValueError('유효하지 않은 CAD 형상입니다.')
            if single_part:
                shape=shapes[next(i for i,p in enumerate(design.parts) if p.id==base['target'])]
                if len(shape.Solids())>1:raise ValueError('Single connected part required. The operation created disconnected solids; fuse touching additions or correct the feature placement.')
            raw=design.model_dump()
        except (ValueError,TypeError,KeyError,IndexError,AttributeError,RuntimeError) as exc:
            from .local_ai import validation_feedback
            raise ValueError(f'작업 {number}/{len(plan.actions)} [{action.tool} → {action.target}] 실패: '+validation_feedback(exc)) from None
        check();step=dict(step=number,**action.model_dump(),validated=True,**outcome);steps.append(step)
        journal_steps.append(dict(action=step,changes=differences(step_before,raw)))
    if raw==before and not any(s.get('outcome')=='already_satisfied' for s in steps):raise ValueError('요청된 작업이 설계를 변경하지 않았습니다. 치수 또는 대상을 확인하세요.')
    from ..kernel import exact_bounds
    measurements=[]
    for expected in plan.checks:
        check();_part(raw,expected.target);shape=_shape(raw,expected.target);box=exact_bounds(shape)
        actual=dict(x=box.xlen,y=box.ylen,z=box.zlen,volume=shape.Volume(),solids=len(shape.Solids()))
        for key,wanted in expected.model_dump(exclude_none=True).items():
            if key=='target':continue
            if key=='size':
                observed=sorted([actual['x'],actual['y'],actual['z']])
                if any(not math.isclose(a,b,rel_tol=1e-5,abs_tol=1e-5) for a,b in zip(observed,sorted(wanted))):
                    raise ValueError(f'Request size mismatch: {expected.target}: required dimensions {wanted}, actual {observed}. Correct the construction, keeping the user dimensions.')
                continue
            if not math.isclose(actual[key],wanted,rel_tol=1e-5,abs_tol=1e-5):
                raise ValueError(f'Request measurement mismatch: {expected.target}.{key}: required {wanted:g}, actual {actual[key]:g}. Correct the construction, keeping the user dimensions.')
        measurements.append(dict(target=expected.target,expected=expected.model_dump(exclude_none=True),actual=actual))
    notes=plan.assumptions+[s['detail'] for s in steps if s.get('detail')]
    return ToolReply(design=design,summary=plan.summary,assumptions=notes,tool_actions=steps,
                     journal_base=before if request.current is None else None,journal_steps=journal_steps,measurements=measurements)
