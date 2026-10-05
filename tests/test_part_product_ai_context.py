"""A large per-part product library must not become an unbounded AI request."""
import json
from cadstudio.models import Design,Part
from cadstudio.part_product import ProductMetadata,ProductSpec
from cadstudio.native.cad_tools import context


def test_many_long_reference_records_have_aggregate_budget_and_explicit_omission():
    product=ProductMetadata(model='User SKU',spec_summary='S'*16000,
        source_url='https://example.com/'+'p'*1400,
        specs=[ProductSpec(label='Dimension',value='V'*1000,unit='mm',condition='C'*1000,
            source_url='https://example.com/'+'s'*1400) for _ in range(64)])
    design=Design(parts=[Part(id=f'body{i}',name=f'Body {i}',geometry={'kind':'cylinder'},product=product) for i in range(12)])
    result=context(design)
    references=[part['product_reference'] for part in result['parts'] if part['product_reference']]
    size=sum(len(json.dumps(item,ensure_ascii=False,separators=(',',':'))) for item in references)
    assert size<=24000
    assert result['product_reference_scope']['omitted_parts']>0
    assert any(part['product_reference'] is None for part in result['parts'])
    assert all(len(fact['value'])<=160 and len(fact['condition'])<=200 for item in references for fact in item['specs'])
    assert all(len(item['spec_summary'])<=1200 for item in references)
    assert design.parts[0].product.specs[0].value=='V'*1000
