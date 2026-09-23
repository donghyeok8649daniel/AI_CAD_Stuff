"""Model-selected geometric capabilities, never object-name routing."""
import json
from dataclasses import dataclass

from .cad_tools import CATALOG, context, messages

TOOLS = ('create', 'dimensions', 'transform', 'appearance', 'hole', 'pocket',
         'pad', 'fillet', 'chamfer', 'shell', 'solid', 'thread', 'joint', 'parameter')
SHAPES = ('cylinder', 'plate', 'extrusion', 'revolve', 'sweep', 'loft', 'bracket',
          'link', 'sheetmetal', 'round_specimen', 'flat_specimen')

SYSTEM = '''Select only CAD tools and geometric representations needed for the request. Return tools and shapes arrays. No dimensional planning yet.
intent: part=ONE connected component (its walls, sections, holes are NOT separate parts); assembly=multiple separate components; edit=modify existing components without creating a new part. When asked for a single object, prefer part unless separate moving or assembled components are necessary. A hollow body is one part.
Tools: create=new body including all its dimensions; dimensions=edit an existing body (not for a new design); pad=add material fused onto a face; pocket=remove material inside a profile, leaving a hole; hole=circular holes/patterns; shell=hollow a solid inward to uniform wall/floor thickness, optionally removing a face to make an opening; fillet=edge rounding; chamfer=edge bevel; solid=boolean/mirror/pattern/split/draft; appearance=color/material; transform=body placement; thread=helical thread; joint=connect assembly bodies; parameter=dimension variable.
Shapes: cylinder=constant OUTSIDE diameter along Z, optional bore. revolve=OUTSIDE diameter changing along Z, including stepped or tapered rotational forms, specified by height/diameter segments, automatically ONE solid. plate=rectangular block. extrusion=arbitrary planar boundary extruded. loft=transition BETWEEN profiles at different heights, all sections in ONE body. sweep=profile along a bent path. bracket=simple L; link=rounded flat bar; sheetmetal=one bend; round_specimen/flat_specimen=tensile test.
Select the minimal set. A new shape uses create only unless extra features are requested. Uniform walls and an open top use create+shell, not separate plates/pads. Repeated holes use hole with a pattern. A constant cross-section uses create/extrusion only, not another pad. Never choose dimensions just to state dimensions of a NEW body. Cutting a smaller center circle makes a bore, NOT a smaller solid external diameter. Use actual IDs and geometry in current_design to understand edits. Shapes may be empty for edits without create.'''


def scope_schema():
    return dict(type='object', properties={
        'intent': dict(type='string', enum=['part', 'assembly', 'edit']),
        'tools': dict(type='array', items=dict(type='string', enum=list(TOOLS)), minItems=1, maxItems=len(TOOLS)),
        'shapes': dict(type='array', items=dict(type='string', enum=list(SHAPES)), maxItems=len(SHAPES)),
    }, required=['intent', 'tools', 'shapes'], additionalProperties=False)


def scope_messages(request):
    return [dict(role='system', content=SYSTEM), dict(role='user', content=json.dumps(
        dict(prompt=request.prompt, selected_part=request.selected_part, current_design=context(request.current)),
        ensure_ascii=False, separators=(',', ':')))]


@dataclass(frozen=True)
class Scope:
    tools: tuple = TOOLS
    shapes: tuple = SHAPES
    intent: str = 'general'

    @classmethod
    def parse(cls, content, request):
        data = json.loads(content)
        if not isinstance(data, dict) or not {'tools', 'shapes'} <= set(data) or set(data) - {'intent', 'tools', 'shapes'}:
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
        return cls(selected['tools'], selected['shapes'] or SHAPES, intent)

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
        if self.intent == 'part':
            result[0]['content'] += '\nSINGLE PART OUTPUT: Return {construction,summary,base:{tool:"create",target:"part-id",args:{name,geometry}},actions:[...features on the SAME target...]}. The base is ONE complete outer shape with its OVERALL dimensions. actions may be empty; never create another part inside actions. Walls and floors are material remaining after shell/pocket on the base, not separate plates. Use shell thickness and open_faces to hollow a body with uniform walls. The result must be one connected part.'
        return result
