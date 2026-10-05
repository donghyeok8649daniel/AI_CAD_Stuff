"""Physical own-board escape leads never create another saved net's junction."""
from itertools import combinations
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF,QRectF
from PySide6.QtWidgets import QApplication

from cadstudio.electrical import ElectricalComponent
from cadstudio.native.circuit_symbols import CircuitPort
from cadstudio.native.pictorial_wiring import physical_routes,wire_color
from cadstudio.native.circuit_routing import _on_segment,_point,_shared_segment


def item(identifier,rect,rows):
    ports={key:CircuitPort(key,key,node,'signal',side,physical=True)
           for key,(x,y,node,side) in rows.items()}
    return SimpleNamespace(component=SimpleNamespace(id=identifier),body_rect=QRectF(*rect),ports=ports,
        mapRectToScene=lambda rect:rect,port_scene_position=lambda key:QPointF(*rows[key][:2]))


def nets_for(items):
    nets={}
    for identifier,current in items.items():
        for key,port in current.ports.items():
            if port.node:nets.setdefault(port.node,[]).append((identifier,key,current.port_scene_position(key),port))
    return nets


def separated(result):
    for left,right in combinations(result.segments,2):
        for a,b in result.segments[left]:
            for c,d in result.segments[right]:
                points=[_point(point) for point in (a,b,c,d)]
                assert not _shared_segment(*points)
                assert not any(_on_segment(point,*points[:2]) for point in points[2:])
                assert not any(_on_segment(point,*points[2:]) for point in points[:2])
        for point in result.junctions[left]:
            assert not any(_on_segment(_point(point),_point(a),_point(b)) for a,b in result.segments[right])


def test_own_body_lead_exception_preserves_exact_pad_coordinates():
    items={'one':item('one',(0,0,100,100),{'signal':(40,50,'FIRST','right')})}
    result=physical_routes(nets_for(items),items)
    assert not result.unrouted
    assert result.segments['FIRST']==[(QPointF(40,50),QPointF(106,50))]


@pytest.mark.parametrize('gap',[8,12])
def test_facing_independent_leads_that_overlap_or_touch_are_labeled_not_falsely_joined(gap):
    items={'one':item('one',(0,0,100,100),{'first':(40,50,'FIRST','right')}),
           'two':item('two',(100+gap,0,100,100),{'second':(150+gap,50,'SECOND','left')})}
    result=physical_routes(nets_for(items),items)
    assert result.segments=={'FIRST':[],'SECOND':[]}
    assert set(result.unrouted)=={('FIRST','one','first'),('SECOND','two','second')}


def test_twenty_two_unit_gap_does_not_create_shared_physical_escape_wire():
    items={'one':item('one',(0,0,100,100),{'first':(40,50,'FIRST','right')}),
           'two':item('two',(122,0,100,100),{'second':(162,50,'SECOND','left')})}
    result=physical_routes(nets_for(items),items)
    assert not result.unrouted
    separated(result)


def test_escape_lead_cannot_cross_foreign_body_or_an_unassigned_visible_socket():
    for other in (item('two',(60,30,20,40),{}),
                  item('two',(160,100,20,20),{'empty':(75,50,None,'left')})):
        items={'one':item('one',(0,0,100,100),{'signal':(40,50,'FIRST','right')}),'two':other}
        result=physical_routes(nets_for(items),items)
        assert result.segments['FIRST']==[] and ('FIRST','one','signal') in result.unrouted


def test_escape_lead_cannot_cross_a_foreign_net_pad_even_when_its_own_lead_is_invalid():
    items={'one':item('one',(0,0,100,100),{'first':(40,50,'FIRST','right')}),
           'two':item('two',(160,100,20,20),{'second':(75,50,'SECOND','left')})}
    result=physical_routes(nets_for(items),items)
    assert not result.segments['FIRST']
    assert ('FIRST','one','first') in result.unrouted
    separated(result)


def test_coincident_unassigned_and_assigned_pad_is_omitted_without_python_sort_error():
    items={'one':item('one',(0,0,100,100),{'first':(40,50,'FIRST','right'),
                                          'empty':(40,50,None,'left')})}
    result=physical_routes(nets_for(items),items)
    assert not result.segments['FIRST'] and result.unrouted


@pytest.mark.parametrize('gap',[8,12,22,80])
def test_real_pi_header_leads_remain_separate_after_close_drag(gap):
    global _APP
    _APP=QApplication.instance() or QApplication([])
    from cadstudio.native.physical_board_symbols import PhysicalComponentItem
    def board(identifier,pin,node):
        return PhysicalComponentItem(ElectricalComponent.model_validate(dict(id=identifier,name=identifier,
            kind='mcu',catalog_id='rpi4b',analysis_enabled=False,a=identifier+'_DC',b='GND',
            pinout_catalog_id='rpi4b',signal_pins={pin:node})))
    one=board('one','GPIO14','FIRST');two=board('two','GPIO17','SECOND')
    first=one.port_scene_position('pin:GPIO14')
    two.setPos(one.body_rect.right()+gap-two.body_rect.left(),
               first.y()-two.pin_positions['pin:GPIO17'].y())
    second=two.port_scene_position('pin:GPIO17')
    nets=dict(FIRST=[('one','pin:GPIO14',first,one.ports['pin:GPIO14'])],
              SECOND=[('two','pin:GPIO17',second,two.ports['pin:GPIO17'])])
    for expanded in (False,True):
        one.show_all_pins(expanded);two.show_all_pins(expanded)
        result=physical_routes(nets,dict(one=one,two=two))
        separated(result)
        if gap>=22:assert not result.unrouted
        else:assert result.unrouted


def test_signal_net_with_a_passive_a_b_terminal_is_not_colored_as_supply():
    signal=CircuitPort('signal','GPIO17','SIG','signal','left',physical=True)
    passive=CircuitPort('a','A','SIG','power','left')
    assert wire_color('SIG',[('board','signal',QPointF(),signal),('resistor','a',QPointF(),passive)]).name()!='#d53b45'
    supply=CircuitPort('supply','5V','VCC','power','right',physical=True)
    assert wire_color('VCC',[('board','supply',QPointF(),supply)]).name()=='#d53b45'


def test_polarized_capacitor_positive_terminal_does_not_invent_a_power_supply():
    capacitor=CircuitPort('a','+','FILTER','passive','left')
    resistor=CircuitPort('b','B','FILTER','power','right')
    assert wire_color('FILTER',[('capacitor','a',QPointF(),capacitor),
                                ('resistor','b',QPointF(),resistor)]).name()!='#d53b45'
    source=CircuitPort('a','+','FILTER','power','left')
    assert wire_color('FILTER',[('battery','a',QPointF(),source),
                                ('capacitor','a',QPointF(),capacitor)]).name()=='#d53b45'
