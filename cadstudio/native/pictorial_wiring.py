"""Source-backed pin anchors with bounded routing outside component bodies."""
from collections import defaultdict
from bisect import bisect_left, bisect_right
import hashlib

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainterPath

from .circuit_routing import (CircuitRoutes, route_nets, _point, _on_segment,
                              _crosses_body, _shared_segment, _junctions)

_ESCAPE=6.0
_EPSILON=1e-6
_MAX_ESCAPE_ENDPOINTS=1024


def wire_color(node, endpoints):
    if any(port.legacy for _,_,_,port in endpoints):return QColor('#D79424')
    kinds={port.kind for _,_,_,port in endpoints}
    if node.upper() in ('GND','GROUND','0V') or kinds=={'ground'}:return QColor('#343D48')
    # A resistor's A/B operating-point terminals are not proof that its net is
    # a supply. Only explicit board/device supply pads or source/DC supply
    # labels give a power conductor priority over a GPIO signal conductor.
    if any((port.physical and port.kind=='power') or
           (port.kind=='power' and port.label in ('+','DC VCC'))
           for _,_,_,port in endpoints):return QColor('#D53B45')
    if 'signal' not in kinds and (node.upper().startswith(('VCC','VDD','VBAT','BAT','VIN'))
                                 or node.upper().startswith('V') and node[1:].isdigit()):return QColor('#D53B45')
    palette=('#DFB923','#AF52D5','#297DC2','#239B68','#F18429','#D65B9A')
    return QColor(palette[hashlib.sha256(node.encode()).digest()[0]%len(palette)])


def physical_routes(nets, component_items, *, reserved_points=(), reserved_segments=None):
    """Only a pin's own lead may cross its own illustrated board body.

    Physical headers can be inside an outline. Route from an explicit escaped
    anchor using the same obstacle/junction rules as logical circuits. No
    physical pin is joined just because two drawings happen to touch.
    """
    external=defaultdict(list);leads=defaultdict(list);candidates=[];bad=set()
    bodies={identifier:item.mapRectToScene(item.body_rect) for identifier,item in component_items.items()}
    reserved=[item.port_scene_position(key) for item in component_items.values()
              for key,port in item.ports.items() if port.node is None]
    reserved.extend(reserved_points)
    # All visible pads participate, including lone nets and unassigned pins.
    # Horizontal lead checks examine only the matching row, keeping dense
    # physical headers inexpensive without ignoring a neighboring socket.
    pads=sorted([(point.y(),point.x(),node) for node,rows in nets.items() for _,_,point,_ in rows]+
                [(point.y(),point.x(),None) for point in reserved],key=lambda row:row[:2])
    ys=[row[0] for row in pads]
    for node,endpoints in nets.items():
        for identifier,key,point,port in endpoints:
            if len(candidates)>=_MAX_ESCAPE_ENDPOINTS:
                bad.add((node,identifier,key));continue
            body=bodies[identifier]
            x=min(point.x(),body.left()-_ESCAPE) if port.side=='left' else max(point.x(),body.right()+_ESCAPE)
            escaped=QPointF(x,point.y())
            start,end=_point(point),_point(escaped)
            foreign_pad=any(other_node!=node and _on_segment((px,py),start,end)
                            for py,px,other_node in pads[bisect_left(ys,start[1]-_EPSILON):bisect_right(ys,start[1]+_EPSILON)])
            if foreign_pad or _crosses_body(start,end,[rect for owner,rect in bodies.items() if owner!=identifier]):
                bad.add((node,identifier,key))
            candidates.append((node,identifier,key,point,escaped,port,start,end))
    # A cramped drag must not draw two independent nets as one conductor.
    # Only perpendicular crossings away from wire endpoints may be retained.
    ordered=sorted(enumerate(candidates),key=lambda row:row[1][6][1])
    for index,(left_index,left) in enumerate(ordered):
        if (left[0],left[1],left[2]) in bad:continue
        for right_index,right in ordered[index+1:]:
            if right[6][1]-left[6][1]>_EPSILON:break
            if left[0]==right[0] or (right[0],right[1],right[2]) in bad:continue
            a,b=left[6:8];c,d=right[6:8]
            if (_shared_segment(a,b,c,d) or any(_on_segment(point,a,b) for point in (c,d))
                    or any(_on_segment(point,c,d) for point in (a,b))):
                bad.update(((left[0],left[1],left[2]),(right[0],right[1],right[2])))
    for node,identifier,key,point,escaped,port,_,_ in candidates:
        if (node,identifier,key) in bad:continue
        external[node].append((identifier,key,escaped,port))
        if point!=escaped:leads[node].append((point,escaped))
    occupied={key:list(rows) for key,rows in (reserved_segments or {}).items()}
    for key,rows in leads.items():occupied.setdefault(key,[]).extend(rows)
    routed=route_nets(external,list(bodies.values()),reserved_points=reserved,
                      reserved_segments=occupied)
    # A lone or unroutable terminal is represented by a labeled free wire end,
    # preserving connectivity without pretending an off-page lead is a junction.
    segments={node:[*leads[node],*routed.segments.get(node,[])] for node in nets}
    bad_nodes={row[0] for row in bad}
    unrouted=[*routed.unrouted]
    # Label every visual island of a partially omitted net, including an
    # otherwise valid anchor when the first original pad was the bad one.
    unrouted.extend((node,identifier,key) for node,rows in nets.items() if node in bad_nodes
                    for identifier,key,_,_ in rows)
    return CircuitRoutes(segments,tuple(dict.fromkeys(unrouted)),
        {node:_junctions([(_point(a),_point(b)) for a,b in rows]) for node,rows in segments.items()})


def wire_path(start,end):
    """Slightly rounded wire ends; endpoints remain exactly at saved pins."""
    path=QPainterPath(start)
    path.lineTo(end)
    return path
