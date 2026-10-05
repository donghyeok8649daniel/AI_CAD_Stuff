"""Product references edit privately and survive full CAD project history."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication,QDialog

from cadstudio.models import Design,Part
from cadstudio.native.document import Document,read_project
from cadstudio.native.part_product_dialog import PartProductDialog
from cadstudio.part_product import ProductMetadata,set_part_product


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def close(dialog,app):
    dialog.reject();dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def design():return Design(parts=[Part(id='frame',name='Frame',geometry={'kind':'cylinder'})])


def test_manual_reference_save_preserves_geometry_and_roundtrips_history(app,tmp_path):
    original=design();before=deepcopy(original.model_dump());dialog=PartProductDialog(None,original,'frame')
    try:
        dialog.show();app.processEvents()
        dialog.fields['model'].setText('Support 10 mm')
        dialog.fields['purchase_url'].setText('https://example.com/item/10')
        dialog.fields['datasheet_url'].setText('https://example.com/drawing.pdf')
        dialog.specs.setPlainText('외경 10 mm · 사용 조건은 미정')
        dialog.accept();checked=dialog.checked
        assert checked is not None and checked.parts[0].product.model=='Support 10 mm'
        assert checked.parts[0].geometry==original.parts[0].geometry
        assert original.model_dump()==before
        document=Document();document.commit(before,'Original');document.commit(checked.model_dump(),'Product reference')
        path=tmp_path/'product.cad.json';document.write(path);loaded=read_project(path)
        assert loaded.design.parts[0].product==checked.parts[0].product
        current=document.journal.data['cursor'];prior=document.journal.index[current]['parent']
        document.commit(document.journal.at(prior),'Undo',cursor=prior)
        assert document.design==before
        document.commit(document.journal.at(current),'Redo',cursor=current)
        assert document.design==checked.model_dump()
    finally:close(dialog,app)


def test_both_catalogs_show_sources_without_assumed_purchase_link(app):
    dialog=PartProductDialog(None,design(),'frame')
    try:
        namespaces={dialog.catalog.itemData(i).split('/',1)[0] for i in range(1,dialog.catalog.count())}
        assert namespaces=={'electrical','mechanical'}
        dialog.catalog.setCurrentIndex(dialog.catalog.findData('electrical/rpi4b'));dialog.use_catalog()
        product=dialog.candidate();assert product.catalog_id=='rpi4b' and product.source_url
        assert not product.purchase_url and not product.official_url
        dialog.catalog.setCurrentIndex(next(i for i in range(1,dialog.catalog.count()) if dialog.catalog.itemData(i).startswith('mechanical/')))
        dialog.use_catalog();assert dialog.sources.count()>0
    finally:close(dialog,app)


def test_invalid_link_blocks_save_and_open_without_external_action(app,monkeypatch):
    from cadstudio.native import part_product_dialog
    opened=[];monkeypatch.setattr(part_product_dialog.QDesktopServices,'openUrl',lambda url:opened.append(url))
    dialog=PartProductDialog(None,design(),'frame')
    try:
        dialog.fields['purchase_url'].setText('file:///C:/Windows/test.exe');dialog.accept()
        assert dialog.checked is None and dialog.status.text()
        dialog.open_link('purchase_url');assert not opened
        dialog.fields['purchase_url'].setText('https://example.com/shop');dialog.open_link('purchase_url')
        assert len(opened)==1
    finally:close(dialog,app)


def test_clear_then_new_reference_keeps_newly_entered_values(app):
    original=set_part_product(design(),'frame',ProductMetadata(model='Old'))
    dialog=PartProductDialog(None,original,'frame')
    try:
        dialog.clear_reference();dialog.fields['model'].setText('New');dialog.accept()
        assert dialog.checked.parts[0].product.model=='New'
        assert original.parts[0].product.model=='Old'
    finally:close(dialog,app)


def test_public_reference_is_reviewed_and_does_not_resize_part(app,monkeypatch):
    from cadstudio.native.component_specs_dialog import ComponentSpecsDialog
    def exported(child):
        child.record={'title':'Actual SKU','url':'https://example.com/spec','excerpt':'Envelope 80 × 20 mm',
                      'retrieved_at':'2026-10-06T01:00:00+00:00','candidates':[{'dimensions_mm':[80,20]}]}
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ComponentSpecsDialog,'exec',exported)
    original=design();dialog=PartProductDialog(None,original,'frame')
    try:
        dialog.fields['purchase_url'].setText('https://example.com/shop');dialog.read_reference()
        assert dialog.candidate().provenance=='web_reference'
        assert dialog.candidate().purchase_url=='https://example.com/shop'
        dialog.accept();assert dialog.checked.parts[0].geometry==original.parts[0].geometry
        assert not dialog.checked.parts[0].product.specs
    finally:close(dialog,app)


def test_manual_sku_change_drops_previous_catalog_facts_and_unedited_source(app):
    from cadstudio.part_product import product_from_catalog
    from cadstudio.mechanical_catalog import CATALOG
    entry=next(entry for entry in CATALOG if entry.ratings or entry.dimensions)
    original=set_part_product(design(),'frame',product_from_catalog('mechanical',entry.catalog_id))
    dialog=PartProductDialog(None,original,'frame')
    try:
        assert dialog.candidate().specs
        dialog.fields['model'].setText('Different user SKU')
        dialog.fields['purchase_url'].setText('https://example.com/new-sku')
        product=dialog.candidate()
        assert product.provenance=='user' and not product.catalog_id and not product.catalog_namespace
        assert not product.specs and not product.sources and not product.source_url
        assert not product.spec_summary
        assert product.purchase_url=='https://example.com/new-sku'
        assert original.parts[0].product.provenance=='catalog'
    finally:close(dialog,app)


def test_edited_catalog_summary_is_user_reference_without_inherited_numeric_facts(app):
    from cadstudio.part_product import product_from_catalog
    from cadstudio.mechanical_catalog import CATALOG
    entry=next(entry for entry in CATALOG if entry.ratings or entry.dimensions)
    original=set_part_product(design(),'frame',product_from_catalog('mechanical',entry.catalog_id))
    dialog=PartProductDialog(None,original,'frame')
    try:
        dialog.specs.setPlainText('User condition: 10 V')
        product=dialog.candidate()
        assert product.catalog_id==entry.catalog_id and product.provenance=='user' and not product.specs
        assert not product.source_checked_at
    finally:close(dialog,app)
