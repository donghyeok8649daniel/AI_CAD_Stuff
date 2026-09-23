"""Explicit diameter deviations and worst-case fits; no inferred ISO classes."""
from pydantic import Field,model_validator
from .models import StrictModel


class FitSettings(StrictModel):
    shaft_ref: str = Field(default='',max_length=160)
    hole_ref: str = Field(default='',max_length=160)
    shaft_nominal: float = Field(default=10,gt=0,le=2000)
    hole_nominal: float = Field(default=10,gt=0,le=2000)
    shaft_lower: float = Field(default=-.02,ge=-100,le=100)
    shaft_upper: float = Field(default=0,ge=-100,le=100)
    hole_lower: float = Field(default=0,ge=-100,le=100)
    hole_upper: float = Field(default=.02,ge=-100,le=100)
    @model_validator(mode='after')
    def limits(self):
        for side in ('shaft','hole'):
            if getattr(self,side+'_lower')>getattr(self,side+'_upper'):raise ValueError('하한 편차는 상한 편차 이하여야 합니다.')
        return self


def diameter_choices(design,side):
    out=[]
    for p in design.parts:
        g=p.geometry
        if side=='shaft' and g.kind=='cylinder':out.append(dict(ref=p.id+'/diameter',part=p.id,label=p.name+' · 외경',nominal=g.diameter))
        if side=='hole':
            if g.kind=='cylinder' and g.bore_diameter>0:out.append(dict(ref=p.id+'/bore_diameter',part=p.id,label=p.name+' · 내경',nominal=g.bore_diameter))
            if g.kind in ('plate','link','bracket') and getattr(g,'hole_count',1):out.append(dict(ref=p.id+'/hole_diameter',part=p.id,label=p.name+' · 구멍',nominal=g.hole_diameter))
            for f in p.features:
                if hasattr(f,'sketch') and f.operation=='cut':
                    es=[e for e in f.sketch.entities if not e.construction]
                    if f.sketch.sketch_mode=='entities' and len(es)==1 and es[0].kind=='circle':out.append(dict(ref=p.id+'/'+f.id+'/'+es[0].id,part=p.id,label=p.name+' · '+f.name,nominal=es[0].radius*2))
    return out


def calculate_fit(design,settings):
    result={}
    for side in ('shaft','hole'):
        ref=getattr(settings,side+'_ref');nominal=getattr(settings,side+'_nominal');item=None
        if ref:
            item=next((r for r in diameter_choices(design,side) if r['ref']==ref),None)
            if item is None:raise ValueError('공차가 참조하는 축 / 구멍이 삭제되거나 형상이 변경되었습니다. 대상을 다시 선택하세요.')
            nominal=item['nominal']
        low=nominal+getattr(settings,side+'_lower');high=nominal+getattr(settings,side+'_upper')
        if low<=0:raise ValueError('공차를 반영한 최소 지름은 0보다 커야 합니다.')
        result[side]=dict(nominal=nominal,low=low,high=high,part=item['part'] if item else None,label=item['label'] if item else '직접 입력')
    minimum=result['hole']['low']-result['shaft']['high'];maximum=result['hole']['high']-result['shaft']['low']
    result.update(minimum=minimum,maximum=maximum,kind='틈새 끼워맞춤' if minimum>=-1e-10 else '억지 끼워맞춤' if maximum<=1e-10 else '중간 끼워맞춤')
    return result
