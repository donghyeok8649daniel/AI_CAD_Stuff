"""Private per-part product reference editor; no geometry or circuit changes."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QDialogButtonBox,QFormLayout,QHBoxLayout,
    QLineEdit,QPlainTextEdit,QScrollArea,QVBoxLayout,QWidget,QComboBox,QApplication)

from ..models import Design
from ..part_product import ProductMetadata,product_for_part,product_from_catalog,product_from_reference,set_part_product
from .widgets import button,label


class PartProductDialog(QDialog):
    def __init__(self,parent,design,part_id):
        super().__init__(parent)
        self.english=getattr(getattr(QApplication.instance(),'cad_language',None),'language','ko')=='en'
        self.design=Design.model_validate(design).model_copy(deep=True)
        self.part_id=part_id;self.checked=None
        part=next(p for p in self.design.parts if p.id==part_id)
        self.setWindowTitle(self.word('부품 제품 스펙 · 구매 링크','Part product specifications / purchase links'))
        self.setObjectName('partProductDialog');self.resize(830,710)
        root=QVBoxLayout(self);root.addWidget(label(part.name,user_text=True))
        root.addWidget(label(self.word('이 부품에 제품 자료를 저장합니다. 형상·색상·회로 정격은 바꾸지 않습니다.',
            'Store product references on this part. Geometry, colors and circuit ratings are unchanged.'),True))
        search=QHBoxLayout();self.filter=QLineEdit();self.filter.setPlaceholderText(self.word('제품 카탈로그 검색…','Search product catalogs…'))
        search.addWidget(self.filter);self.catalog=QComboBox();self.catalog.setMinimumWidth(300);search.addWidget(self.catalog,1)
        search.addWidget(button(self.word('자료 가져오기','Use catalog reference'),self.use_catalog));root.addLayout(search)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();form=QFormLayout(body)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows);self.fields={}
        for key,ko,en,maximum in [('name','제품명','Product name',200),('manufacturer','제조사','Manufacturer',160),
            ('model','모델 / 품번','Model / SKU',160)]:
            field=QLineEdit();field.setMaxLength(maximum);field.setObjectName('partProduct_'+key)
            self.fields[key]=field;form.addRow(self.word(ko,en),field)
        self.specs=QPlainTextEdit();self.specs.setObjectName('partProduct_specs');self.specs.setMinimumHeight(125)
        self.specs.setPlaceholderText(self.word('치수·전압·전류 등 단위와 적용 조건을 함께 입력하세요. 모르는 값은 미정으로 남기세요.',
            'Include units and conditions for dimensions, voltage and current. Leave unknown values unspecified.'))
        form.addRow(self.word('제품 스펙 / 조건','Specifications / conditions'),self.specs)
        for key,ko,en in [('official_url','공식 제품 페이지','Official product page'),('datasheet_url','데이터시트 / 도면','Datasheet / drawing'),
            ('purchase_url','구매 페이지','Purchase page'),('source_url','자료 출처','Reference source')]:
            row=QHBoxLayout();field=QLineEdit();field.setMaxLength(1500);field.setPlaceholderText('https://…');field.setObjectName('partProduct_'+key)
            self.fields[key]=field;row.addWidget(field,1)
            row.addWidget(button(self.word('열기','Open'),lambda _=False,k=key:self.open_link(k)))
            form.addRow(self.word(ko,en),row)
        self.notes=QPlainTextEdit();self.notes.setMaximumHeight(90);form.addRow(self.word('메모','Notes'),self.notes)
        self.source_status=label('',True);form.addRow(self.source_status)
        self.reference_details=QPlainTextEdit();self.reference_details.setReadOnly(True);self.reference_details.setMaximumHeight(140)
        form.addRow(self.reference_details)
        row=QHBoxLayout();self.sources=QComboBox();row.addWidget(self.sources,1)
        row.addWidget(button(self.word('추가 출처 열기','Open reference'),self.open_extra_source));form.addRow(row)
        scroll.setWidget(body);root.addWidget(scroll,1)
        row=QHBoxLayout();row.addWidget(button(self.word('공개 URL에서 자료 가져오기…','Read public product URL…'),self.read_reference))
        row.addWidget(button(self.word('제품 연결 지우기','Clear product reference'),self.clear_reference));row.addStretch();root.addLayout(row)
        self.status=label('',True);root.addWidget(self.status)
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept);controls.rejected.connect(self.reject);root.addWidget(controls)
        self._base=None;self._clear=False;self.filter.textChanged.connect(self.filter_catalog);self.filter_catalog()
        self.load_product(product_for_part(self.design,part_id))

    def word(self,ko,en):return en if self.english else ko

    def filter_catalog(self,*_):
        from ..electrical_catalog import CATALOG as electrical
        from ..mechanical_catalog import CATALOG as mechanical
        query=self.filter.text().strip().casefold();prior=self.catalog.currentData()
        self.catalog.clear();self.catalog.addItem(self.word('제품 선택…','Choose product…'),None)
        for namespace,entries in [('electrical',electrical),('mechanical',mechanical)]:
            for entry in entries:
                title=entry.display_name
                identifier=entry.catalog_id
                if not query or query in (title+' '+identifier+' '+entry.manufacturer).casefold():
                    self.catalog.addItem(title,namespace+'/'+identifier)
        index=self.catalog.findData(prior)
        if index>=0:self.catalog.setCurrentIndex(index)

    def load_product(self,product):
        self._base=product.model_dump() if product else {};self._clear=False
        for key,field in self.fields.items():field.setText(self._base.get(key) or '')
        self.specs.setPlainText(self._base.get('spec_summary') or '')
        self.notes.setPlainText(self._base.get('notes') or '')
        facts=self._base.get('specs') or []
        sources=self._base.get('sources') or []
        self.reference_details.setPlainText('\n'.join(f"{f['label']}: {f.get('value') if f.get('value') is not None else '?'} {f.get('unit','')} · {f.get('condition','')}" for f in facts))
        self.reference_details.setVisible(bool(facts));self.sources.clear()
        for source in sources:self.sources.addItem(source.get('title') or source['url'],source['url'])
        self.source_status.setText(self.word('출처 자료: ','Reference sources: ')+str(len(sources))+
            (' · '+self._base['source_checked_at'] if self._base.get('source_checked_at') else ''))
        self.status.setText('')

    def use_catalog(self):
        selected=self.catalog.currentData()
        if selected:self.load_product(product_from_catalog(*selected.split('/',1)))

    def read_reference(self):
        from .component_specs_dialog import ComponentSpecsDialog
        dialog=ComponentSpecsDialog(self);dialog.url.setText(self.fields['source_url'].text() or self.fields['official_url'].text())
        dialog.use.hide();dialog.ai.setText(self.word('이 자료 사용','Use this reference'))
        if dialog.exec()==QDialog.DialogCode.Accepted and dialog.record:
            try:
                imported=product_from_reference(dialog.record)
                prior=self.candidate().model_dump() if not self._clear else {}
                for key in ('name','manufacturer','model','official_url','datasheet_url','purchase_url','notes'):
                    if prior.get(key):setattr(imported,key,prior[key])
                self.load_product(imported)
            except ValueError as exc:self.status.setText(str(exc)[:1200])
        dialog.deleteLater()

    def candidate(self):
        values=dict(self._base)
        values.update({key:field.text().strip() for key,field in self.fields.items()})
        values.update(spec_summary=self.specs.toPlainText().strip(),notes=self.notes.toPlainText().strip())
        identity_changed=any(values.get(key,'')!=self._base.get(key,'') for key in ('manufacturer','model'))
        specs_changed=values['spec_summary']!=self._base.get('spec_summary','')
        if identity_changed or specs_changed:
            values['provenance']='user'
            values['specs']=[]
            values['source_checked_at']=''
        if identity_changed:
            values['catalog_id']='';values['catalog_namespace']='';values['sources']=[]
            for key in ('name','spec_summary','notes'):
                if values.get(key)==self._base.get(key):values[key]=''
            # Inherited links to the former SKU must not silently become the
            # new SKU's evidence. Explicitly edited links remain user input.
            for key in ('source_url','official_url','datasheet_url','purchase_url'):
                if values.get(key)==self._base.get(key):values[key]=''
        return ProductMetadata.model_validate(values)

    def clear_reference(self):
        self.load_product(None);self._clear=True
        self.status.setText(self.word('저장하면 이 부품의 제품 자료를 지웁니다. 전장 등록은 유지됩니다.',
            'Save clears this part reference. Its electrical registration remains intact.'))

    def open_link(self,key):
        try:
            value=self.candidate();url=getattr(value,key)
            if url:QDesktopServices.openUrl(QUrl(url))
        except ValueError as exc:self.status.setText(str(exc)[:1000])

    def open_extra_source(self):
        from ..part_product import validate_product_link
        try:
            url=validate_product_link(self.sources.currentData() or '')
            if url:QDesktopServices.openUrl(QUrl(url))
        except ValueError as exc:self.status.setText(str(exc)[:1000])

    def accept(self):
        try:self.checked=set_part_product(self.design,self.part_id,self.candidate())
        except ValueError as exc:self.status.setText(str(exc)[:1200]);return
        super().accept()
