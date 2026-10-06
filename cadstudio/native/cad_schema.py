"""Compact tool-specific output grammar; the kernel remains the final validator."""
from copy import deepcopy


def plan_schema(allowed_tools=None,allowed_shapes=None,*,single_part=False,connections=(),new_parts=(),existing_parts=()):
    from .cad_tools import CADPlan
    number={'type':'number'};text={'type':'string'};boolean={'type':'boolean'}
    color={'type':'string','pattern':'^#[0-9A-Fa-f]{6}$'}
    def array(item,minimum=0,maximum=32):
        return dict(type='array',items=item,minItems=minimum,maxItems=maximum)
    def obj(properties,required=()):
        return dict(type='object',properties=properties,required=list(required),additionalProperties=False)
    def enum(*values):return dict(type='string',enum=list(values))
    def ref(name):return {'$ref':'#/$defs/'+name}
    vector=array(number,3,3);direction=enum('+X','-X','+Y','-Y','+Z','-Z')
    point=obj(dict(x=number,y=number),('x','y'))
    # Every concrete entity is still checked against the native sketch schema.
    entity={'type':'object','properties':{'id':text,'kind':enum('circle','line','arc','ellipse','spline'),
        'center':point,'start':point,'end':point,'radius':number,'radius_x':number,'radius_y':number,
        'start_angle':number,'sweep':number,'points':array(point,2),'closed':boolean},'required':['id','kind'],'additionalProperties':False}
    profile={'anyOf':[
        obj({'circle':obj(dict(diameter=number,center=array(number,2,2)),('diameter',))},('circle',)),
        obj({'rectangle':obj(dict(width=number,height=number,center=array(number,2,2)),('width','height'))},('rectangle',)),
        obj({'points':array(point,3)},('points',)),
        obj({'sketch_mode':{'const':'entities'},'entities':array(entity,1)},('sketch_mode','entities'))]}
    frame=obj(dict(origin=vector,normal=vector,x_direction=vector),('origin','normal','x_direction'))
    section={'anyOf':[obj(dict(z=number,profile=ref('Profile')),('z','profile')),
        obj(dict(sketch=ref('Profile'),frame=ref('Frame')),('sketch',))]}
    loft_section={'anyOf':[section['anyOf'][0],obj(dict(sketch=ref('Profile'),frame=ref('Frame')),('sketch','frame'))]}
    transform=obj({k:number for k in ('x','y','z','rx','ry','rz')})
    shapes=[]
    def shape(kind,fields,required):
        shapes.append(obj({'kind':{'const':kind},**fields},('kind',*required)))
    shape('spur_gear',dict(module=number,teeth={'type':'integer'},thickness=number,pressure_angle={'type':'integer','enum':[20,25]},backlash=number,bore_diameter=number,shaft_diameter=number,shaft_length=number),('module','teeth','thickness'))
    shape('cylinder',dict(diameter=number,height=number,bore_diameter=number),('diameter','height'))
    shape('plate',dict(length=number,width=number,thickness=number,hole_count={'const':0}),('length','width','thickness'))
    shape('extrusion',dict(thickness=number,profile=ref('Profile'),taper=number,symmetric=boolean,thin_wall=number),('thickness','profile'))
    shape('loft',dict(sections=array(ref('LoftSection'),2,8),solid=boolean,ruled=boolean),('sections',))
    shape('sweep',dict(profile=ref('Section'),path=obj(dict(points=array(vector,2),smooth=boolean),('points',)),solid=boolean,align_profile=boolean),('profile','path'))
    shape('revolve',dict(segments=array(obj(dict(length=number,diameter=number,end_diameter=number),('length','diameter')),1,14),bore_diameter=number,angle=number),('segments',))
    shape('revolve',dict(stations=array(array(number,2,2),2,28),bore_diameter=number,angle=number),('stations',))
    shape('revolve',dict(profile=ref('Section'),axis_start=vector,axis_direction=vector,angle=number),('profile','axis_start','axis_direction'))
    for kind,names in [('bracket','length width height thickness hole_diameter hole_inset'),
                       ('link','length width thickness hole_diameter hole_spacing'),
                       ('sheetmetal','length width flange_length thickness bend_radius bend_angle k_factor'),
                       ('round_specimen','length gauge_length grip_diameter gauge_diameter transition_length'),
                       ('flat_specimen','length gauge_length grip_width gauge_width thickness transition_length')]:
        shape(kind,{k:number for k in names.split()},names.split())
    actions=[]
    def tool(name,fields,required=()):
        actions.append(obj(dict(tool={'const':name},target={'type':'string','pattern':'^[a-zA-Z0-9_-]+$'},
            args=obj(fields,required)),('tool','target','args')))
    role=enum('unspecified','structure','electrical','transmission','specimen')
    tool('create',dict(name=text,geometry=ref('Geometry'),color=color,role=role,transform=ref('Transform')),('name','geometry'))
    tool('dimensions',dict(values={'type':'object','additionalProperties':{}}),('values',))
    from .cad_feature_edits import schema_fields
    tool('edit_feature',schema_fields(),('feature_id',))
    tool('transform',transform['properties'])
    tool('edit_joint',transform['properties'])
    tool('appearance',dict(name=text,color=color,role=role,material=obj(dict(name=text,density=number,youngs_modulus=number,poisson=number))))
    pattern={'anyOf':[obj(dict(kind={'const':'rectangular'},count_x={'type':'integer'},count_y={'type':'integer'},
        spacing_x=number,spacing_y=number,center=array(number,2,2)),('kind','count_x','count_y','spacing_x','spacing_y')),
        obj(dict(kind={'const':'circular'},count={'type':'integer'},diameter=number,start_angle=number,center=array(number,2,2)),('kind','count','diameter'))]}
    tool('hole',dict(face=direction,diameter=number,pattern=pattern,centers=array(array(number,2,2),1),depth=number,through_all=boolean,
        finish=enum('plain','counterbore','countersink'),head_diameter=number,head_depth=number,head_angle=number),('face','diameter'))
    for name in ('pad','pocket'):
        tool(name,dict(face=direction,profile=ref('Profile'),depth=number,through_all=boolean),('face','profile','depth'))
    for name in ('fillet','chamfer'):
        tool(name,dict(size=number,edges=enum('all','+X','-X','+Y','-Y','+Z','-Z')),('size',))
    tool('shell',dict(thickness=number,open_faces=array(direction,0,6)),('thickness',))
    tool('solid',dict(operation=enum('mirror','linear_pattern','circular_pattern','split','draft','boolean'),
        origin=vector,direction=vector,keep_original=boolean,count={'type':'integer'},count_y={'type':'integer'},
        spacing=vector,angle=number,keep_side=enum('positive','negative','all'),faces=array(direction),
        tool_part_id=text,boolean_mode=enum('union','cut','intersect')),('operation',))
    tool('thread',dict(diameter=number,pitch=number,length=number,internal=boolean,offset=number,
        handedness=enum('right','left'),clearance=number),('diameter','pitch','length'))
    tool('joint',dict(kind=enum('rigid','revolute','slider','cylindrical','ball','planar','pin_slot'),parent=text,child=text,
        parent_anchor=enum('origin'),child_anchor=enum('origin'),
        parent_cylinder=obj(dict(center=vector,direction=vector,diameter=number),('center','direction','diameter')),
        child_cylinder=obj(dict(center=vector,direction=vector,diameter=number),('center','direction','diameter')),
        flipped=boolean,
        limits=obj({axis:array(number,2,2) for axis in ('x','y','z','rx','ry','rz')}),
        **transform['properties']),('kind','parent','child'))
    tool('motion_link',dict(driver=text,driven=text,ratio=number,offset=number,driver_axis=enum('x','y','z','rx','ry','rz'),driven_axis=enum('x','y','z','rx','ry','rz')),('driver','driven','ratio'))
    tool('parameter',dict(value=text),('value',))
    tool('power_path',dict(
        name=text,source_voltage_v=number,source_internal_resistance_ohm=number,
        source_max_current_a=number,source_enabled=boolean,source_part_id=text,
        switch_closed=boolean,switch_contact_resistance_ohm=number,
        switch_max_current_a=number,switch_part_id=text,
        positive_wire_length_mm=number,positive_wire_cross_section_mm2=number,
        positive_wire_resistivity_ohm_mm2_per_m=number,positive_wire_catalog_id=text,
        positive_wire_max_current_a=number,positive_wire_part_id=text,
        return_wire_length_mm=number,return_wire_cross_section_mm2=number,
        return_wire_resistivity_ohm_mm2_per_m=number,return_wire_catalog_id=text,
        return_wire_max_current_a=number,return_wire_part_id=text,
        load_kind=enum('load','motor','actuator','mcu'),load_voltage_v=number,
        load_current_a=number,load_startup_current_a=number,load_part_id=text),
        ('source_voltage_v','positive_wire_length_mm','positive_wire_cross_section_mm2',
         'return_wire_length_mm','return_wire_cross_section_mm2','load_voltage_v','load_current_a'))
    from ..electrical_registration import RegistrationSpec
    registration_fields = RegistrationSpec.model_json_schema()['properties']
    for field in ('signal_pins','terminal_pins'):
        registration_fields[field]=array(obj(dict(pin=text,node=text),('pin','node')),0,144)
    tool('electrical_register',registration_fields)
    tool('electrical_connect',dict(pin=text,target_part_id=text,target_terminal=text),('pin','target_part_id','target_terminal'))
    tool('electrical_unregister',{})
    tool('electrical_bind',dict(component_id=text,apply_default_color=boolean),('component_id',))
    tool('electrical_unbind',{})
    wire_fields=dict(name=text,wire_color=color,length_mm=number,cross_section_mm2=number,
                     max_current_a=number,analysis_enabled=boolean)
    tool('electrical_wire_add',dict(source_terminal=text,target_id=text,target_terminal=text,**wire_fields),
         ('source_terminal','target_id','target_terminal'))
    tool('electrical_wire_edit',dict(source_id=text,source_terminal=text,target_id=text,target_terminal=text,
         closed=boolean,resistivity_ohm_mm2_per_m=number,**wire_fields))
    tool('electrical_wire_delete',{})
    # Editing-only plans cannot invent another part ID. In particular, a
    # feature ID is not its owning part ID (small models confuse the two).
    # If create remains available without declared IDs, allow new targets.
    if new_parts or (existing_parts and allowed_tools is not None and 'create' not in allowed_tools):
        for action in actions:
            name=action['properties']['tool']['const']
            if name=='create' and new_parts:action['properties']['target']=enum(*new_parts)
            elif name not in ('joint','edit_joint','parameter','motion_link','power_path','electrical_unbind',
                              'electrical_wire_add','electrical_wire_edit','electrical_wire_delete'):action['properties']['target']=enum(*dict.fromkeys((*existing_parts,*new_parts)))
    if connections:
        joint = next(a for a in actions if a['properties']['tool']['const'] == 'joint')
        actions.remove(joint)
        for connection in connections:
            constrained = deepcopy(joint)
            for key, value in connection.items():
                constrained['properties']['args']['properties'][key] = {'const': value}
            actions.append(constrained)
    schema=deepcopy(CADPlan.model_json_schema())
    if allowed_tools is not None:actions=[a for a in actions if a['properties']['tool']['const'] in allowed_tools]
    if allowed_shapes is not None:shapes=[s for s in shapes if s['properties']['kind']['const'] in allowed_shapes]
    broad_fallback=len(actions)>12
    if broad_fallback:
        # The broad fallback grammar must stay small enough for local models.
        # Electrical-only scopes receive complete arguments. Fallback plans
        # still pass the same strict PowerPathSpec/RegistrationSpec validators.
        for action in actions:
            if action['properties']['tool']['const'] in ('power_path','edit_feature','electrical_register',
                    'electrical_connect','electrical_bind','electrical_unbind','electrical_wire_add',
                    'electrical_wire_edit','electrical_wire_delete'):
                action['properties']['args']={'type':'object'}
    if not actions or not shapes:raise ValueError('At least one known tool and shape must be available.')
    # The kernel accepts explicit measurement contracts, but a small LLM's
    # guesses about bounding-box dimensions are not independent user specs.
    # Do not force it to invent such checks (e.g. two diameters != X/Y extents).
    schema['properties'].pop('checks')
    schema['$defs']={'Profile':profile,'Frame':frame,'Section':section,'LoftSection':loft_section,'Transform':transform,'Geometry':{'anyOf':shapes}}
    schema['properties']['actions']['items']={'anyOf':actions}
    schema['properties']['construction']['description']='Dimensioned steps, then implement these actions.'
    schema['required']=['construction','summary','actions']
    if single_part:
        create=next(a for a in actions if a['properties']['tool']['const']=='create')
        features=[a for a in actions if a['properties']['tool']['const'] not in ('create','joint','edit_joint','motion_link','power_path')]
        schema['properties'].pop('actions')
        schema['properties']['base']=create
        schema['properties']['actions']=array({'anyOf':features} if features else {},0,31 if features else 0)
        schema['required']=['construction','summary','base','actions']
    if broad_fallback:
        # Repeated collection/text bounds and annotations consume the small
        # model's context. Keep types, required fields, enums and references;
        # native schemas/kernel enforce every size and geometry bound on output.
        def compact(value):
            if isinstance(value,dict):
                return {key:compact(item) for key,item in value.items()
                        if key not in ('title','default','minItems','maxItems','minLength','maxLength')}
            if isinstance(value,list):return [compact(item) for item in value]
            return value
        action_bounds={key:value for key,value in schema['properties']['actions'].items()
                       if key in ('minItems','maxItems')}
        schema=compact(schema)
        # Keep the overall operation budget explicit for provider planning.
        schema['properties']['actions'].update(action_bounds)
    return schema
