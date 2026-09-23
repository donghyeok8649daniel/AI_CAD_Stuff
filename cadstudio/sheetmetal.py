"""Single cylindrical sheet bend with explicit tangent lengths and neutral axis."""
import math
import cadquery as cq


def bend_allowance(g):return math.radians(g.bend_angle)*(g.bend_radius+g.k_factor*g.thickness)
def flat_length(g):return g.length+g.flange_length+bend_allowance(g)


def construct_sheet(g):
    if g.flat:return cq.Workplane('XY').box(flat_length(g),g.width,g.thickness,centered=(False,True,False)).val()
    angle=math.radians(g.bend_angle);r=g.bend_radius;t=g.thickness
    def p(radius,a):return radius*math.sin(a),r-radius*math.cos(a)
    inner=p(r,angle);outer=p(r+t,angle);delta=(g.flange_length*math.cos(angle),g.flange_length*math.sin(angle))
    wire=(cq.Workplane('XZ').moveTo(-g.length,-t).lineTo(0,-t).threePointArc(p(r+t,angle/2),outer).lineTo(outer[0]+delta[0],outer[1]+delta[1]).lineTo(inner[0]+delta[0],inner[1]+delta[1]).lineTo(*inner).threePointArc(p(r,angle/2),(0,0)).lineTo(-g.length,0).close())
    shape=wire.extrude(g.width).translate((0,g.width/2,0)).val()
    if not shape.isValid() or len(shape.Solids())!=1:raise ValueError('절곡부가 겹칩니다. 각도·반경·플랜지 길이를 확인하세요.')
    return shape


def export_flat(g,path):
    import ezdxf
    d=ezdxf.new('R2010');d.units=4;d.layers.new('CUT');d.layers.new('BEND');space=d.modelspace();length=flat_length(g);half=g.width/2
    space.add_lwpolyline([(0,-half),(length,-half),(length,half),(0,half)],close=True,dxfattribs={'layer':'CUT'})
    for x in (g.length,g.length+bend_allowance(g)):space.add_line((x,-half),(x,half),dxfattribs={'layer':'BEND'})
    d.saveas(path)
