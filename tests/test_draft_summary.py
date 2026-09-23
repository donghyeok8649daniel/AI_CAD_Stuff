from cadstudio.native.draft_summary import draft_summary


def test_actual_geometry_is_shown_before_incorrect_ai_dimensions_and_color():
    response=dict(summary='반지름 100 mm 검은 바퀴',assumptions=['검은색으로 설정함'],
                  changes=['1. 부품 생성'],measurements=[dict(bounds=[200,200,20])])
    preview=dict(stats=dict(bounds=[100,100,20],parts=1,volume=117809.7245),meshes=[
        dict(name='wheel',bounds=[100,100,20],color='#2266CC')])
    text=draft_summary(response,preview)
    measured,description=text.split('\n\nAI 설명',1)
    assert '100.00 × 100.00 × 20.00 mm' in measured and '#2266CC' in measured
    assert '117,809.72 mm³' in measured and '검은' not in measured and '200.00' not in measured
    assert response['summary'] in description and '1. 부품 생성' in description
