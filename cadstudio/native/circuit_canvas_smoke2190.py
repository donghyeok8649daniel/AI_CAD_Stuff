"""Owned native circuit workspace flow using a synthetic, source-backed fixture."""
from copy import deepcopy
import json
import time
import traceback

from PySide6.QtCore import QPoint,QPointF,QThreadPool,QTimer,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPushButton


def run(app,window,path):
    from ..electrical import ElectricalWorkspace,evaluate_electrical
    from ..models import Design,Part
    from .document import read_project
    from .electrical_schematic import ElectricalSchematicDialog,NET_ROLE

    path.parent.mkdir(parents=True,exist_ok=True)
    report={'checks':[],'live_ai_calls':0,'fixture':'Synthetic component circuit; no private user project'}
    dialogs=[];errors=[]

    def check(condition,title):
        if not condition:raise AssertionError(title)
        report['checks'].append(title)

    def wait(predicate):
        end=time.monotonic()+60
        while not predicate():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('Owned circuit canvas flow')
        app.processEvents()

    def click(dialog,identifier,key):
        point=dialog.view.mapFromScene(dialog.component_items[identifier].port_scene_position(key))
        QTest.mouseClick(dialog.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
        app.processEvents()

    def own_modal(callback):
        def handle():
            child=QApplication.activeModalWidget()
            try:
                if not isinstance(child,ElectricalSchematicDialog):raise AssertionError('Expected owned circuit editor modal')
                callback(child)
            except Exception:
                errors.append(traceback.format_exc())
                if child:child.reject()
        QTimer.singleShot(100,handle)

    try:
        app.setQuitOnLastWindowClosed(False);window.show_error=errors.append
        check(window.document.design is None,'native startup stays an empty CAD document')
        workspace=ElectricalWorkspace.model_validate(dict(name='Controller and actuator · example values',
            nodes=['GND','BAT','POWER','INPUT','SWITCHED'],components=[
                dict(id='battery',name='Battery · virtual 5 V',kind='battery',a='BAT',b='GND',voltage_v=5,
                     internal_resistance_ohm=.05,max_current_a=3),
                dict(id='switch',name='Power switch',kind='switch',a='BAT',b='SWITCHED',contact_resistance_ohm=.01),
                dict(id='wire',name='Power cable · sample dimensions',kind='wire',a='SWITCHED',b='POWER',
                     length_mm=250,cross_section_mm2=.5,max_current_a=3),
                dict(id='pi',name='Raspberry Pi 4 controller',kind='mcu',catalog_id='rpi4b',a='POWER',b='GND',
                     rated_voltage_v=5,rated_current_a=.2,part_id='controller'),
                dict(id='driver',name='DRV8833 driver · operating data pending',kind='load',catalog_id='pololu_2130',
                     a='POWER',b='GND',analysis_enabled=False),
                dict(id='motor',name='DC actuator · virtual operating values',kind='motor',a='POWER',b='GND',
                     rated_voltage_v=5,rated_current_a=.15),
                dict(id='resistor',name='Input pull-down',kind='resistor',a='INPUT',b='GND',resistance_ohm=1000),
            ]))
        design=Design(name='Synthetic circuit verification',electrical=workspace,parts=[
            Part(id='controller',name='Controller CAD body',role='electrical',geometry=dict(kind='cylinder'),
                 transform=dict(x=-80)),
            Part(id='frame',name='Structural CAD body',role='structure',geometry=dict(kind='cylinder'),
                 transform=dict(x=80))]).model_dump()
        window.apply_design(design,'Synthetic circuit fixture');wait(lambda:not window.busy)
        check(set(window.viewport.actors)=={'controller','frame'},'original CAD solids remain available')
        original=deepcopy(window.document.design)
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        from PySide6.QtTest import QSignalSpy
        import shiboken6
        for _ in range(30):
            window.show_part_role('electrical')
            iterator=QTreeWidgetItemIterator(window.tree);rows={}
            while iterator.value():
                item=iterator.value();data=item.data(0,Qt.ItemDataRole.UserRole)
                if data and data[0]=='part':rows[data[1]]=item
                iterator+=1
            source=rows['frame'];source.setExpanded(False)
            changed=QSignalSpy(window.tree.itemChanged)
            source.setCheckState(0,Qt.CheckState.Checked);app.processEvents()
            assert window.role_view is None and changed.count()==1 and not source.isExpanded()
            assert all(shiboken6.isValid(row) and row.treeWidget() is window.tree
                       and (row.checkState(0)==Qt.CheckState.Checked)==(identifier not in window.viewport.hidden)
                       for identifier,row in rows.items())
        check(window.document.design==original,'thirty role-filter checkbox overrides preserve live Qt rows, visibility and CAD data')
        window.show_circuit_workspace();app.processEvents()
        panel=window.circuit_panel
        check(window.workspace.currentData()=='circuit' and window.stack.currentWidget() is panel,
              'workspace selector opens the integrated main circuit canvas')
        check(panel.objectName()=='mainCircuitWorkspace' and not panel.editable,
              'main circuit display is explicit and protects uncommitted editing')
        check(set(panel.component_items)=={component.id for component in workspace.components},
              'boards, battery, resistor, switch, cable and actuator share one component canvas')
        check(panel.pin_panel.isHidden(),'the default canvas has no oversized separate pin table')
        pi=panel.component_items['pi']
        check(panel.view_mode=='physical' and pi.board.model=='Raspberry Pi 4 Model B'
              and len([port for port in pi.ports.values() if port.physical])==40,
              'the default physical MPU board exposes all forty real header sockets')
        check(pi.all_ports['supply:3V3_1'].node is None and pi.all_ports['supply:3V3_1'].connectable
              and pi.all_ports['supply:GND_6'].node is None,
              'real supply sockets remain explicitly unassigned until the user wires them')
        check('port:AIN1' in panel.component_items['driver'].ports,
              'registered driver exposes its documented product terminals on the same canvas')
        check(panel.component_items['driver'].component.analysis_enabled is False,
              'missing device operating data stays pending rather than inventing a DC load')
        check(window.document.design==original,'viewing and selecting a circuit does not alter the saved design')
        panel.focus_component('pi');app.processEvents()
        check(panel.cad_button.isEnabled(),'a registered electronic board exposes its linked CAD part')
        QTest.mouseClick(panel.cad_button,Qt.MouseButton.LeftButton);app.processEvents()
        check(window.workspace.currentData()=='model' and window.selected_parts==['controller'],
              'Show CAD part selects the registered controller in the real 3D viewport')
        wiring=window.wiring_window;dialogs.append(wiring)
        check(wiring.isVisible() and wiring.objectName()=='floatingWiringDiagram'
              and wiring._selected_id()=='pi' and not wiring.editable,
              'linked CAD selection retains the same component in a separate physical wiring window')
        wiring.reject();window.actions['wiring_diagram'].trigger();app.processEvents()
        check(wiring.isVisible() and window.actions['wiring_diagram'] in window.toolbar.actions(),
              'the top toolbar circuit action opens the separate board and wiring window')
        wiring.reject();window.show_circuit_workspace();app.processEvents();panel=window.circuit_panel
        docks=(window.browser_dock,window.property_dock,window.ai_dock,window.timeline_dock)
        old_visibility=[dock.isVisible() for dock in docks]
        window.property_dock.hide();app.processEvents()
        preferences=[dock.isVisible() for dock in docks]
        focus=next(item for item in panel.findChildren(QPushButton)
                   if item.text().startswith(('회로도 크게 보기','Focus circuit')))
        focus.click();app.processEvents()
        check(not any(dock.isVisible() for dock in docks),'Focus circuit removes all four CAD side and timeline panels')
        check(window.circuit_focus_panels==preferences,'focused circuit stores the exact prior panel visibility preferences')
        focus.click();app.processEvents()
        check([dock.isVisible() for dock in docks]==preferences,'restoring circuit panels preserves deliberately hidden panels')
        focus.click();app.processEvents();panel.fit_scene()
        window.grab().save(str(path.with_name('circuit-focused2190.png')))
        panel.component_items['pi'].setSelected(True);panel.expand_selected();panel.fit_scene();app.processEvents()
        check(len([port for port in panel.component_items['pi'].ports.values() if port.physical])==40,
              'all forty documented Raspberry Pi header pins can be inspected in place')
        check(not panel.workspace_changed,'expanding the reference pins does not dirty the CAD document')
        panel.view.grab().save(str(path.with_name('circuit-main2190.png')))
        window.workspace.setCurrentIndex(window.workspace.findData('model'));app.processEvents()
        check([dock.isVisible() for dock in docks]==preferences and window.circuit_focus_panels is None,
              'leaving a focused circuit automatically restores the prior panel visibility')
        for dock,visible in zip(docks,old_visibility):dock.setVisible(visible)
        check(window.stack.currentWidget() is window.viewport and set(window.viewport.actors)=={'controller','frame'},
              'returning to design restores the original 3D viewport and bodies')
        from . import codex_connection
        save_settings=codex_connection.save_settings;settings_calls=[]
        config=deepcopy(window.codex_config);catalog=deepcopy(window.codex_catalog)
        previous_provider=window.provider.currentData();window.provider.setCurrentIndex(window.provider.findData('codex'))
        previous_effort=window.cloud_effort.currentData()
        codex_connection.save_settings=lambda executable,model:settings_calls.append((executable,model))
        try:
            window.codex_catalog=[dict(model='server-A',name='Owned test A',efforts=['low','high']),
                                  dict(model='server-B',name='Owned test B',efforts=['medium','max'])]
            window.codex_config={**config,'model':'server-A'}
            window.codex_models.set_catalog(window.codex_catalog,'server-A');window.update_codex_effort()
            window.cloud_effort.setCurrentIndex(window.cloud_effort.findData('high'))
            window.codex_models.setCurrentIndex(window.codex_models.findData('server-B'));app.processEvents()
            check(settings_calls==[(config['executable'],'server-B')] and window.codex_config['model']=='server-B',
                  'inline Codex model selection persists only the server-returned model with a mocked settings writer')
            check({window.cloud_effort.itemData(index) for index in range(window.cloud_effort.count())}=={'medium','max'}
                  and window.cloud_effort.currentData()=='medium',
                  'changing a Codex model updates reasoning choices to that model catalog')
            window.ai_task=object();window.select_codex_model('server-A');window.ai_task=None
            window.codex_probe_task=object();window.select_codex_model('server-A');window.codex_probe_task=None
            window.select_codex_model('unlisted-model')
            check(len(settings_calls)==1 and window.codex_config['model']=='server-B',
                  'busy AI, a connection check, and unknown model names cannot change the saved model')
        finally:
            window.ai_task=None;window.codex_probe_task=None;codex_connection.save_settings=save_settings
            window.codex_config=config;window.codex_catalog=catalog
            window.codex_models.set_catalog(catalog,config['model']);window.update_codex_effort()
            index=window.cloud_effort.findData(previous_effort)
            if index>=0:window.cloud_effort.setCurrentIndex(index)
            window.provider.setCurrentIndex(window.provider.findData(previous_provider))
        window.show_circuit_workspace();app.processEvents()
        window.grab().save(str(path.with_name('circuit-workspace2190.png')))

        def cancel_editor(child):
            child.component_items['motor'].setPos(QPointF(1510,360))
            check(child.workspace_changed and child.apply_button.isEnabled(),'native circuit editing exposes unsaved layout changes')
            child.reject()
        own_modal(cancel_editor);window.edit_main_circuit();app.processEvents()
        check(window.document.design==original,'canceling the native circuit editor preserves the exact CAD and circuit')

        draft=ElectricalSchematicDialog(window,workspace,evaluate_electrical(workspace),design['parts'])
        dialogs.append(draft);draft.resize(1280,850);draft.show();app.processEvents();draft.fit_scene()
        start_calc=evaluate_electrical(draft.workspace).model_dump()
        motor=draft.component_items['motor'];start=motor.pos()
        point=draft.view.mapFromScene(motor.mapToScene(motor.body_rect.center()))
        QTest.mousePress(draft.view.viewport(),Qt.MouseButton.LeftButton,pos=point)
        for offset in (QPoint(16,8),QPoint(32,16),QPoint(48,24)):
            QTest.mouseMove(draft.view.viewport(),point+offset,delay=15)
        QTest.mouseRelease(draft.view.viewport(),Qt.MouseButton.LeftButton,pos=point+QPoint(48,24))
        wait(lambda:draft.endpoint_coordinates[('motor','a')]==motor.port_scene_position('a'))
        check((motor.pos()-start).manhattanLength()>5,'an actual mouse drag moves the actuator circuit symbol')
        position=draft.workspace.schematic_positions['motor']
        check((position.x,position.y)==(motor.pos().x(),motor.pos().y()),'dragged schematic positions are preserved in the draft')
        check(draft.endpoint_coordinates[('motor','a')]==motor.port_scene_position('a'),
              'conductors follow the moved component terminal')
        check(evaluate_electrical(draft.workspace).model_dump()==start_calc,
              'arranging symbols does not change electrical values, nets or calculated currents')
        draft.component_items['pi'].setSelected(True);draft.expand_selected();draft.fit_scene()
        draft.wire_button.click();click(draft,'pi','supply:5V_2');click(draft,'battery','a')
        wait(lambda:next(component for component in draft.workspace.components if component.id=='pi').board_supply_pins.get('5V_2')=='BAT')
        click(draft,'pi','supply:GND_6');click(draft,'battery','b')
        wait(lambda:next(component for component in draft.workspace.components if component.id=='pi').board_supply_pins.get('GND_6')=='GND')
        pi_model=next(component for component in draft.workspace.components if component.id=='pi')
        check(pi_model.board_supply_pins=={'5V_2':'BAT','GND_6':'GND'}
              and (pi_model.a,pi_model.b)==('POWER','GND') and '5V_4' not in pi_model.board_supply_pins,
              'real physical 5V and GND clicks create explicit wires without inventing sibling pads or changing the DC load')
        check(not draft.supply_warnings.text(),'correct physical supply wiring has no rail mismatch warning')
        wired_wrong_rail=draft.connect_terminals('pi','supply:3V3_1','battery','a')
        battery_voltage=evaluate_electrical(draft.workspace).node_voltages_v['BAT']
        check(wired_wrong_rail and '3.3 V' in draft.supply_warnings.text()
              and f'{battery_voltage:.4g} V' in draft.supply_warnings.text() and battery_voltage>4.5,
              'a physical 3.3V socket connected to the calculated battery rail displays its actual voltage warning')
        draft.wire_button.click();click(draft,'pi','supply:3V3_1')
        check(draft.disconnect_button.isEnabled(),'a connected physical socket can be selected for disconnection')
        QTest.mouseClick(draft.disconnect_button,Qt.MouseButton.LeftButton);app.processEvents()
        check('3V3_1' not in next(component for component in draft.workspace.components if component.id=='pi').board_supply_pins
              and not draft.supply_warnings.text(),'Disconnect selected pin removes only the incorrect supply wire and its warning')
        draft.wire_button.click();click(draft,'pi','pin:GPIO17')
        check(draft.pending_terminal==('pi','pin:GPIO17'),'a real canvas pin click selects the wire source')
        click(draft,'driver','port:AIN1')
        pi_model=next(component for component in draft.workspace.components if component.id=='pi')
        driver=next(component for component in draft.workspace.components if component.id=='driver')
        net=pi_model.signal_pins['GPIO17']
        check(net==driver.terminal_pins['AIN1'],'real GPIO-to-driver port clicks create one explicit shared net')
        check(net in draft.net_segments and all(segment.data(NET_ROLE)==net for segment in draft.net_segments[net]),
              'drawn wire segments retain their saved net identity')
        check('GPIO18' not in pi_model.signal_pins and 'AIN2' not in driver.terminal_pins,
              'neighboring GPIO and product terminals remain independent and unassigned')
        click(draft,'motor','a');check(draft.pending_terminal==('motor','a'),'another connection can be started without closing the editor')
        QTest.keyClick(draft.view,Qt.Key.Key_Escape);app.processEvents()
        check(draft.pending_terminal is None,'Escape cancels a pending wire without discarding the edited circuit')
        check(workspace.model_dump()==ElectricalWorkspace.model_validate(original['electrical']).model_dump(),
              'editable circuit draft never mutates its input workspace')
        draft.fit_scene();draft.grab().save(str(path.with_name('circuit-editor2190.png')))
        draft.accept();accepted=draft.accepted_workspace
        check(accepted is not None and accepted.schematic_positions,'native save returns the layout and wiring together')

        def save_editor(child):
            child._adopt(accepted);child.apply_button.click()
        own_modal(save_editor);window.edit_main_circuit();wait(lambda:not window.busy)
        check(window.document.design['electrical']==accepted.model_dump(),'main editor save applies the exact accepted electrical draft')
        check(window.workspace.currentData()=='circuit' and window.stack.currentWidget() is window.circuit_panel,
              'saving the circuit keeps the main circuit workspace visible')
        check(window.circuit_panel.branch_layout['pi']['signals']['GPIO17']['node']==net,
              'the main circuit view immediately reflects saved pin wiring')
        check(window.document.design['parts']==original['parts'],'circuit edits preserve all mechanical CAD bodies and colors')
        final=deepcopy(window.document.design);saved=path.with_suffix('.cad.json');window.document.write(saved)
        loaded=read_project(saved)
        check(loaded.design.model_dump()==final,'project save and reload preserve the complete circuit and display placement')
        check(loaded.history is not None and len(loaded.history.entries)>=2,'circuit editing remains a real CAD history transaction')
        window.undo();wait(lambda:not window.busy)
        check(window.document.design==original,'Undo restores the original electrical circuit and prior layout absence')
        window.redo();wait(lambda:not window.busy)
        check(window.document.design==final,'Redo restores exact pin wiring, symbols and placement')
        window.circuit_panel.fit_scene();app.processEvents()
        window.grab().save(str(path.with_name('circuit-saved-main2190.png')))
        language=getattr(app,'cad_language',None)
        if language:
            previous=language.language;language.set_language('en',persist=False)
            english=ElectricalSchematicDialog(window,accepted);dialogs.append(english);english.show();app.processEvents()
            check('components' in english.windowTitle().lower() and 'Wire pins' in english.wire_button.text(),
                  'English mode exposes the same component-oriented circuit workflow')
            english.grab().save(str(path.with_name('circuit-english2190.png')));english.reject()
            language.set_language(previous,persist=False)
        check(not errors,'no native CAD worker, modal or circuit canvas errors')
        report['success']=True
    except Exception:
        report.update(success=False,error=traceback.format_exc())
    finally:
        for dialog in reversed(dialogs):dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        window.document.dirty=False;window.close()
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
