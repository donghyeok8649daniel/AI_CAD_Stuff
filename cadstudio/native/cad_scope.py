"""Model-selected geometric capabilities, never object-name routing."""
import json
import re
from dataclasses import dataclass

from .cad_tools import CATALOG, context, messages

TOOLS = ('create', 'dimensions', 'transform', 'appearance', 'hole', 'pocket',
         'pad', 'fillet', 'chamfer', 'shell', 'solid', 'thread', 'joint', 'parameter', 'edit_feature')
SHAPES = ('cylinder', 'plate', 'extrusion', 'revolve', 'sweep', 'loft', 'bracket',
          'link', 'sheetmetal', 'round_specimen', 'flat_specimen')
JOINTS = ('rigid', 'revolute', 'slider', 'cylindrical', 'ball', 'planar', 'pin_slot')

SYSTEM = '''Select only CAD tools and geometric representations needed for the request. Return tools and shapes arrays. No dimensional planning yet.
intent: part=ONE connected component (its walls, sections, holes are NOT separate parts); assembly=multiple separate components; edit=modify existing components without creating a new part. When asked for a single object, prefer part unless separate moving or assembled components are necessary. A hollow body is one part.
Tools: create=new body including all its dimensions; dimensions=edit an existing body (not for a new design); pad=add material fused onto a face; pocket=remove material inside a profile, leaving a hole; hole=circular holes/patterns; shell=hollow a solid inward to uniform wall/floor thickness, optionally removing a face to make an opening; fillet=edge rounding; chamfer=edge bevel; solid=boolean/mirror/pattern/split/draft; appearance=color/material; transform=body placement; thread=helical thread; joint=connect assembly bodies; parameter=dimension variable.
Shapes: cylinder=constant OUTSIDE diameter along Z, optional bore. revolve=OUTSIDE diameter changing along Z, including stepped or tapered rotational forms, specified by height/diameter segments, automatically ONE solid. plate=rectangular block. extrusion=arbitrary planar boundary extruded. loft=transition BETWEEN profiles at different heights, all sections in ONE body. sweep=profile along a bent path. bracket=simple L; link=rounded flat bar; sheetmetal=one bend; round_specimen/flat_specimen=tensile test.
Select the minimal set. A new shape uses create only unless extra features are requested. Uniform walls and an open top use create+shell, not separate plates/pads. Repeated holes use hole with a pattern. A constant cross-section uses create/extrusion only, not another pad. Never choose dimensions just to state dimensions of a NEW body. Cutting a smaller center circle makes a bore, NOT a smaller solid external diameter. Use actual IDs and geometry in current_design to understand edits. Shapes may be empty for edits without create.'''
SYSTEM += '''
edit_feature edits an EXISTING hole, pad, pocket, fillet, chamfer, shell, pattern or thread. Use it for changing an existing feature's dimensions or suppression instead of creating another cut or body. dimensions edits only BASE geometry. parameter edits dimensions driven by variables. Current features include IDs, editable fields and dimensions; selected_feature identifies the user's selected feature.
new_parts: list descriptive ASCII IDs for ALL parts to create, one for a single part, multiple for an assembly, [] for edits that create nothing. These are the exact IDs used by create and by every later operation. Include unconnected components too. Existing IDs are already available; do not include them in new_parts.
connections: extract the assembly relationships required by the ORIGINAL request, before generating geometry. Each entry is {kind,parent,child}. parent is the supporting/reference component; child is the component moving relative to it. Use descriptive ASCII part IDs and preserve existing IDs for edits. These IDs will be mandatory in the later plan. revolute=rotation only (회전), slider=translation only, cylindrical=rotation AND translation, rigid=NO relative motion (고정 결합). Fixing the parent to ground does NOT make its moving child's joint rigid. Include new joints only; for geometry/appearance edits preserve existing joints and return connections=[]. For a single part or no assembly relationships return []. Never interchange parent and child.'''


def scope_schema():
    return dict(type='object', properties={
        'intent': dict(type='string', enum=['part', 'assembly', 'edit']),
        'tools': dict(type='array', items=dict(type='string', enum=list(TOOLS)), minItems=1, maxItems=len(TOOLS)),
        'shapes': dict(type='array', items=dict(type='string', enum=list(SHAPES)), maxItems=len(SHAPES)),
        'new_parts': dict(type='array', maxItems=16, items=dict(type='string', pattern='^[a-zA-Z0-9_-]{1,40}$')),
        'connections': dict(type='array', maxItems=8, items=dict(type='object', properties={
            'kind': dict(type='string', enum=list(JOINTS)),
            'parent': dict(type='string', pattern='^[a-zA-Z0-9_-]{1,40}$'),
            'child': dict(type='string', pattern='^[a-zA-Z0-9_-]{1,40}$'),
        }, required=['kind', 'parent', 'child'], additionalProperties=False)),
    }, required=['intent', 'tools', 'shapes', 'new_parts', 'connections'], additionalProperties=False)


def scope_messages(request):
    return [dict(role='system', content=SYSTEM), dict(role='user', content=json.dumps(
        dict(prompt=request.prompt, selected_part=request.selected_part, selected_feature=request.selected_feature, current_design=context(request.current)),
        ensure_ascii=False, separators=(',', ':')))]


@dataclass(frozen=True)
class Scope:
    tools: tuple = TOOLS
    shapes: tuple = SHAPES
    intent: str = 'general'
    connections: tuple = ()
    new_parts: tuple = ()

    @classmethod
    def parse(cls, content, request):
        data = json.loads(content)
        if not isinstance(data, dict) or not {'tools', 'shapes'} <= set(data) or set(data) - {'intent', 'tools', 'shapes', 'connections', 'new_parts'}:
            raise ValueError('Expected tool and shape selections.')
        intent = data.get('intent', 'general')
        if intent not in ('part', 'assembly', 'edit', 'general'):
            raise ValueError('Unknown CAD intent.')
        selected = {}
        for key, allowed in (('tools', TOOLS), ('shapes', SHAPES)):
            values = data[key]
            if not isinstance(values, list) or any(not isinstance(v, str) or v not in allowed for v in values):
                raise ValueError('Unknown CAD capability selection.')
            selected[key] = tuple(dict.fromkeys(values))
        if not request.current or not request.current.parts:
            selected['tools'] = tuple(t for t in selected['tools'] if t != 'dimensions')
        if not selected['tools'] or ('create' in selected['tools'] and not selected['shapes']):
            raise ValueError('The plan has no usable CAD capabilities.')
        # Editing-only plans do not use Geometry, but keep its schema valid.
        if intent == 'part' and 'create' not in selected['tools']:
            raise ValueError('A new part needs create.')
        connections = data.get('connections', [])
        if not isinstance(connections, list) or len(connections) > 8:
            raise ValueError('Invalid assembly requirements.')
        for joint in connections:
            if (not isinstance(joint, dict) or set(joint) != {'kind', 'parent', 'child'}
                    or joint['kind'] not in JOINTS
                    or any(not isinstance(joint[key], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', joint[key]) for key in ('parent', 'child'))
                    or joint['parent'] == joint['child']):
                raise ValueError('Invalid assembly relationship.')
        if connections and ('joint' not in selected['tools'] or intent == 'part'):
            raise ValueError('Assembly requirements need the joint tool.')
        if len({j['child'] for j in connections}) != len(connections):
            raise ValueError('Each child needs one parent joint.')
        new_parts = data.get('new_parts', [])
        if (not isinstance(new_parts, list) or len(new_parts)>16
                or any(not isinstance(v,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',v) for v in new_parts)
                or len(set(new_parts)) != len(new_parts)):
            raise ValueError('Invalid new part IDs.')
        if new_parts:
            existing = {p.id for p in request.current.parts} if request.current else set()
            if 'create' not in selected['tools'] or existing & set(new_parts) or (intent=='part' and len(new_parts)!=1):
                raise ValueError('New part IDs do not match the requested operation.')
            if any(j[key] not in existing | set(new_parts) for j in connections for key in ('parent','child')):
                raise ValueError('Joint IDs must refer to the listed new or existing parts.')
        return cls(selected['tools'], selected['shapes'] or SHAPES, intent, tuple(connections), tuple(new_parts))

    def validate_result(self, result):
        """Check the independently selected joint contract on actual CAD data."""
        missing = set(self.new_parts) - {p.id for p in result.design.parts}
        if missing:
            raise ValueError('Missing planned parts: '+', '.join(sorted(missing))+'. Use the declared part IDs, not synonyms.')
        for required in self.connections:
            if not any(all(getattr(mate, key) == value for key, value in required.items()) for mate in result.design.mates):
                raise ValueError('Assembly requirement not met: ' + json.dumps(required) +
                                 '. Preserve these parent/child part IDs and the requested motion. '
                                 'A grounded parent still permits its child to move; rigid is not revolute.')
        return result

    def plan_messages(self, request):
        keep = []
        for line in CATALOG.splitlines():
            prefix = line.split(':')[0]
            if prefix in TOOLS and prefix not in self.tools:
                continue
            if prefix in SHAPES and prefix not in self.shapes:
                continue
            if line.startswith('pocket or pad:') and not set(self.tools) & {'pocket', 'pad'}:
                continue
            if line.startswith('fillet or chamfer:') and not set(self.tools) & {'fillet', 'chamfer'}:
                continue
            if line.startswith('- Add a circular boss') and 'pad' not in self.tools:
                continue
            if line.startswith('- Transition between') and 'loft' not in self.shapes:
                continue
            keep.append(line)
        result = messages(request)
        result[0]['content'] = '\n'.join(keep) + '\nThe tools listed here are AVAILABLE, not a required sequence. Use only operations needed for the ORIGINAL request; do not use every tool just because it is listed.'
        if self.new_parts:
            result[0]['content'] += '\nNEW PART IDs: '+json.dumps(self.new_parts)+'. Create every listed part using EXACTLY its declared target ID. Reuse that ID for holes, features, appearance and joints. Synonyms belong only in the display name, never in target IDs.'
        if self.connections:
            result[0]['content'] += '\nMANDATORY ASSEMBLY RELATIONSHIPS extracted from the original request: ' + json.dumps(self.connections) + '. Use exactly these descriptive part IDs when creating their geometry. Preserve the parent/child direction and joint kind; these will be checked against the resulting CAD assembly. Grounding the supporting parent does not lock its moving child.'
        if self.intent == 'part':
            result[0]['content'] += '\nSINGLE PART OUTPUT: Return {construction,summary,base:{tool:"create",target:"part-id",args:{name,geometry}},actions:[...features on the SAME target...]}. The base is ONE complete outer shape with its OVERALL dimensions. actions may be empty; never create another part inside actions. Walls and floors are material remaining after shell/pocket on the base, not separate plates. Use shell thickness and open_faces to hollow a body with uniform walls. The result must be one connected part.'
        return result
