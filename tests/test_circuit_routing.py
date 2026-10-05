"""Circuit routes preserve visible separation after close component dragging."""

from itertools import combinations
from collections import defaultdict

import pytest
from PySide6.QtCore import QPointF, QRectF

from cadstudio.native.circuit_routing import route_nets


def endpoint(identifier, key, x, y):
    return identifier, key, QPointF(x,y), None


def on_segment(point, a, b):
    epsilon = 1e-6
    return ((abs(a.y()-b.y())<epsilon and abs(point.y()-a.y())<epsilon
             and min(a.x(),b.x())-epsilon<=point.x()<=max(a.x(),b.x())+epsilon)
            or (abs(a.x()-b.x())<epsilon and abs(point.x()-a.x())<epsilon
                and min(a.y(),b.y())-epsilon<=point.y()<=max(a.y(),b.y())+epsilon))


def shared(a,b,c,d):
    epsilon = 1e-6
    if abs(a.y()-b.y())<epsilon and abs(c.y()-d.y())<epsilon and abs(a.y()-c.y())<epsilon:
        return min(max(a.x(),b.x()),max(c.x(),d.x()))-max(min(a.x(),b.x()),min(c.x(),d.x()))>epsilon
    if abs(a.x()-b.x())<epsilon and abs(c.x()-d.x())<epsilon and abs(a.x()-c.x())<epsilon:
        return min(max(a.y(),b.y()),max(c.y(),d.y()))-max(min(a.y(),b.y()),min(c.y(),d.y()))>epsilon
    return False


def crosses_interior(a,b,rect):
    if a.y()==b.y():
        return (rect.top()<a.y()<rect.bottom()
                and min(max(a.x(),b.x()),rect.right())-max(min(a.x(),b.x()),rect.left())>1e-6)
    return (rect.left()<a.x()<rect.right()
            and min(max(a.y(),b.y()),rect.bottom())-max(min(a.y(),b.y()),rect.top())>1e-6)


def assert_valid(result,nets,obstacles):
    for node,segments in result.segments.items():
        for a,b in segments:
            assert a.x()==b.x() or a.y()==b.y()
            assert not any(crosses_interior(a,b,rect) for rect in obstacles)
        for identifier,key,point,_ in nets[node]:
            if (node,identifier,key) not in result.unrouted and len(nets[node])>1:
                assert any(on_segment(point,a,b) for a,b in segments)
    for left,right in combinations(result.segments,2):
        for a,b in result.segments[left]:
            for c,d in result.segments[right]:
                assert not shared(a,b,c,d)
                assert not any(on_segment(point,a,b) for point in (c,d))
                assert not any(on_segment(point,c,d) for point in (a,b))
        for point in result.junctions[left]:
            assert not any(on_segment(point,a,b) for a,b in result.segments[right])


def test_close_nonoverlapping_battery_and_board_do_not_look_short_circuited():
    # This 22-unit gap between item bounding boxes previously sent a long
    # battery GND lead through the board and its BAT lead through the battery.
    nets = dict(BAT=[endpoint('battery','a',0,72),endpoint('board','a',220,72)],
                GND=[endpoint('battery','b',180,72),endpoint('board','b',500,72)])
    bodies = [QRectF(18,32,144,102),QRectF(238,32,244,110)]
    result = route_nets(nets,bodies)
    assert not result.unrouted
    assert_valid(result,nets,bodies)


@pytest.mark.parametrize('dx,dy',[(0,0),(15,0),(-160,40),(400,-70),(-90,-190),(220,210)])
def test_dragged_board_layout_keeps_independent_signal_wires_distinct(dx,dy):
    nets = dict(VCC=[endpoint('battery','a',0,72),endpoint('board','a',360+dx,72+dy)],
                GND=[endpoint('battery','b',180,72),endpoint('board','b',640+dx,72+dy),
                     endpoint('resistor','b',1030,92)],
                SIGNAL_A=[endpoint('board','pin:A',360+dx,108+dy),endpoint('resistor','a',850,92)],
                SIGNAL_B=[endpoint('board','pin:B',360+dx,126+dy),endpoint('device','port:B',850,270)])
    bodies = [QRectF(18,32,144,102),QRectF(378+dx,32+dy,244,170),
              QRectF(870,62,140,70),QRectF(870,240,220,110)]
    result = route_nets(nets,bodies)
    # Some moved boards geometrically cover a terminal from another symbol.
    # A bounded router must disclose that route rather than forging a wire.
    assert_valid(result,nets,bodies)


def test_perpendicular_crossings_are_allowed_without_shared_junctions():
    nets = dict(horizontal=[endpoint('left','a',-100,0),endpoint('right','a',100,0)],
                vertical=[endpoint('top','a',0,-100),endpoint('bottom','a',0,100)])
    result = route_nets(nets,[])
    assert not result.unrouted
    assert len(result.segments['horizontal'])==len(result.segments['vertical'])==1
    assert not result.junctions['horizontal'] and not result.junctions['vertical']
    assert_valid(result,nets,[])


def test_same_coordinate_independent_ports_do_not_get_a_shared_conductor():
    nets = dict(one=[endpoint('a','a',0,0),endpoint('b','a',100,0)],
                two=[endpoint('c','a',0,0),endpoint('d','a',100,0)])
    result = route_nets(nets,[])
    assert result.unrouted
    assert not result.segments['one'] and not result.segments['two']


def test_route_failure_inside_a_body_is_explicit_and_does_not_draw_fake_connection():
    nets = dict(BAT=[endpoint('a','a',0,0),endpoint('b','a',50,50)])
    result = route_nets(nets,[QRectF(30,30,40,40)])
    assert set(result.unrouted) == {('BAT','b','a'),('BAT','a','a')}
    assert result.segments['BAT'] == []


def test_same_net_three_way_branch_dot_is_real_and_never_other_net_crossing():
    nets = dict(main=[endpoint('a','a',0,0),endpoint('b','a',200,0),endpoint('c','a',100,100)],
                other=[endpoint('d','a',75,-80),endpoint('e','a',75,80)])
    result = route_nets(nets,[])
    assert not result.unrouted
    assert_valid(result,nets,[])
    for point in result.junctions['main']:
        assert sum(on_segment(point,a,b) for a,b in result.segments['main'])>=2


def test_single_endpoint_is_a_net_label_and_input_order_has_deterministic_routes():
    nets = dict(UNCONNECTED=[endpoint('board','pin:A',0,0)],
                signal=[endpoint('a','a',0,40),endpoint('b','a',100,40)])
    first = route_nets(nets,[]); second = route_nets(nets,[])
    assert first.segments == second.segments and first.unrouted == second.unrouted
    assert first.segments['UNCONNECTED'] == [] and not first.unrouted


def test_unassigned_visible_physical_pad_does_not_acquire_a_wire_crossing():
    nets = dict(SIGNAL=[endpoint('left','a',0,0),endpoint('right','a',100,0)])
    unassigned = QPointF(50,0)
    result = route_nets(nets,[],reserved_points=[unassigned])
    assert not result.unrouted
    assert not any(on_segment(unassigned,a,b) for a,b in result.segments['SIGNAL'])
    assert_valid(result,nets,[])


def test_many_connections_hit_bounded_budget_and_report_remaining_endpoint_labels():
    nets = {'shared':[endpoint(str(index),'a',index*20,0) for index in range(520)]}
    result = route_nets(nets,[])
    assert len(result.unrouted)==7
    assert result.unrouted[-1]==('shared','519','a')
    assert len(result.segments['shared'])==512


def test_foreign_physical_escape_segments_are_reserved_even_for_a_lone_net():
    nets=dict(other=[endpoint('first','a',0,0),endpoint('second','a',100,0)])
    fixed=dict(physical=[(QPointF(20,0),QPointF(80,0))])
    result=route_nets(nets,[],reserved_segments=fixed)
    assert not result.unrouted
    for a,b in result.segments['other']:
        for c,d in fixed['physical']:
            assert not shared(a,b,c,d)
            assert not any(on_segment(point,a,b) for point in (c,d))
            assert not any(on_segment(point,c,d) for point in (a,b))


def test_foreign_physical_lead_can_be_crossed_perpendicularly_without_a_junction():
    nets=dict(other=[endpoint('first','a',0,0),endpoint('second','a',100,0)])
    fixed=dict(physical=[(QPointF(50,-30),QPointF(50,30))])
    result=route_nets(nets,[],reserved_segments=fixed)
    assert not result.unrouted and not result.junctions['other']
    assert len(result.segments['other'])==1
    assert set((point.x(),point.y()) for point in result.segments['other'][0])=={(0,0),(100,0)}


def test_route_must_not_terminate_on_a_foreign_physical_lead_interior():
    nets=dict(other=[endpoint('first','a',50,0),endpoint('second','a',50,40)])
    result=route_nets(nets,[],reserved_segments=dict(physical=[(QPointF(0,0),QPointF(100,0))]))
    assert result.unrouted and not result.segments['other']


@pytest.mark.parametrize('expanded',[False,True])
def test_actual_miniature_board_pads_stay_distinct_after_close_drag_and_expansion(expanded):
    from PySide6.QtWidgets import QApplication, QGraphicsScene
    from cadstudio.electrical import ElectricalComponent
    from cadstudio.native.circuit_symbols import CircuitComponentItem

    qt=QApplication.instance() or QApplication([])
    qt.setQuitOnLastWindowClosed(False)
    scene=QGraphicsScene()
    items=[CircuitComponentItem(ElectricalComponent.model_validate(raw)) for raw in [
        dict(id='battery',name='Battery',kind='battery',a='VCC',b='GND',voltage_v=5),
        dict(id='board',name='Pi4',kind='mcu',catalog_id='rpi4b',pinout_catalog_id='rpi4b',
             a='VCC',b='GND',analysis_enabled=False,signal_pins={'GPIO17':'SIG_A','GPIO18':'SIG_B'}),
        dict(id='driver',name='Manual driver',kind='load',a='VCC',b='GND',analysis_enabled=False,
             terminal_pins={'IN_A':'SIG_A','IN_B':'SIG_B'}),
    ]]
    try:
        for item,(x,y) in zip(items,[(0,0),(220,0),(900,400)]):
            scene.addItem(item);item.setPos(x,y)
        items[1].show_all_pins(expanded)
        nets=defaultdict(list);reserved=[];bodies=[]
        for item in items:
            bodies.append(item.mapRectToScene(item.body_rect))
            for key,port in item.ports.items():
                point=item.port_scene_position(key)
                if port.node:nets[port.node].append((item.component.id,key,point,port))
                else:reserved.append(point)
        result=route_nets(nets,bodies,reserved_points=reserved)
        assert not result.unrouted
        assert reserved
        assert_valid(result,nets,bodies)
        assert not any(on_segment(point,a,b) for point in reserved for segments in result.segments.values()
                       for a,b in segments)
        assert ('board','pin:GPIO17') in {(identifier,key) for rows in nets.values() for identifier,key,_,_ in rows}
    finally:
        scene.clear()
