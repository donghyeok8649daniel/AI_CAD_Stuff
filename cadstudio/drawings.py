"""Three orthographic views, OCCT hidden lines, mm paper geometry."""
from html import escape
from pathlib import Path
import numpy as np
from pydantic import Field
from .models import StrictModel,Coordinate
from typing import Literal


class DrawingSettings(StrictModel):
    part_id: str = ''  # empty = assembly in world placement
    title: str = Field(default='부품 도면',max_length=80)
    number: str = Field(default='CAD-001',max_length=40)
    revision: str = Field(default='A',max_length=20)
    page: str = Field(default='A4',pattern='^A[34]$')
    scale: float = Field(default=0,ge=0,le=100) # 0 = fit
    hidden: bool = True
    dimensions: bool = True
    extra_view: Literal['none','section','detail'] = 'none'
    section_axis: Literal['X','Y','Z'] = 'Y'
    section_offset: Coordinate = 0
    detail_center: list[Coordinate] = Field(default_factory=lambda:[0,0],min_length=2,max_length=2)
    detail_radius: float = Field(default=10,ge=.01,le=2000)
    detail_factor: float = Field(default=2,ge=1,le=20)
    all_parts: bool = False
    notes: str = Field(default='',max_length=800)


def projected_lines(shape,normal,x_direction):
    import cadquery as cq
    from OCP.HLRBRep import HLRBRep_Algo,HLRBRep_HLRToShape
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.gp import gp_Ax2,gp_Pnt,gp_Dir
    from OCP.BRepLib import BRepLib
    algo=HLRBRep_Algo();algo.Add(shape.wrapped);algo.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(),gp_Dir(*normal),gp_Dir(*x_direction))));algo.Update();algo.Hide();hlr=HLRBRep_HLRToShape(algo);lines=[]
    for hidden,names in [(False,['VCompound','Rg1LineVCompound','OutLineVCompound']),(True,['HCompound','OutLineHCompound'])]:
        for name in names:
            raw=getattr(hlr,name)()
            if raw.IsNull():continue
            BRepLib.BuildCurves3d_s(raw,1e-7)
            for edge in cq.Shape(raw).Edges():
                # HLR projection is exact; display/export curves use a bounded
                # chord approximation, documented as a polyline drawing.
                points=edge.tessellate(.01)[0]
                if len(points)<2:points=edge.sample(2 if edge.geomType()=='LINE' else 96)[0]
                if edge.IsClosed() and points:points.append(points[0])
                lines.append(dict(points=[[p.x,p.y] for p in points],hidden=hidden))
    return lines


def sheet(design,settings):
    import cadquery as cq
    from .kernel import build,local_shape
    if settings.part_id:
        part=next((p for p in design.parts if p.id==settings.part_id),None)
        if part is None:raise ValueError('도면의 부품이 삭제되었습니다.')
        shape=local_shape(design,part)
    else:
        shapes=build(design)
        if not shapes:raise ValueError('도면으로 만들 부품이 없습니다.')
        shape=cq.Compound.makeCompound(shapes)
    width,height=(297,210) if settings.page=='A4' else (420,297)
    cellw=(width-52)/2;cellh=(height-65)/2
    views=[]
    for name,normal,xd,col,row in [('TOP · XY',(0,0,1),(1,0,0),0,0),('FRONT · XZ',(0,-1,0),(1,0,0),0,1),('RIGHT · YZ',(1,0,0),(0,1,0),1,1)]:
        lines=projected_lines(shape,normal,xd);points=np.array([p for line in lines for p in line['points']]);low=points.min(axis=0);high=points.max(axis=0)
        views.append(dict(name=name,lines=lines,low=low,high=high,factor=1,center=np.array([20+col*(cellw+18)+cellw/2,17+row*(cellh+12)+cellh/2])))
    if settings.extra_view!='none':
        lines,name,factor=extra_view(shape,settings);points=np.array([p for line in lines for p in line['points']])
        if not len(points):raise ValueError('상세 / 단면 범위에 형상이 없습니다.')
        views.append(dict(name=name,lines=lines,low=points.min(axis=0),high=points.max(axis=0),factor=factor,center=np.array([20+(cellw+18)+cellw/2,17+cellh/2])))
    fit=min(min((cellw-22)/max(v['high'][0]-v['low'][0],.001),(cellh-22)/max(v['high'][1]-v['low'][1],.001))/v['factor'] for v in views)
    scale=settings.scale or min(1,fit)
    if scale>fit+1e-9:raise ValueError(f'축척이 용지보다 큽니다. {fit:.3g} 이하 또는 자동 맞춤을 사용하세요.')
    paths=[];texts=[]
    def line(points,hidden=False):paths.append(dict(points=points,hidden=hidden))
    def text(x,y,value,size=3):texts.append(dict(x=x,y=y,text=value,size=size))
    for view in views:
        middle=(view['low']+view['high'])/2
        def project(p):return (view['center']+(np.array(p)-middle)*[scale*view['factor'],-scale*view['factor']]).tolist()
        for item in view['lines']:
            if not item['hidden'] or settings.hidden:line([project(p) for p in item['points']],item['hidden'])
        low,high=view['low'],view['high'];left,top=project([low[0],high[1]]);right,bottom=project([high[0],low[1]])
        text(view['center'][0],top-5,view['name'])
        if settings.dimensions:
            line([[left,bottom+2],[left,bottom+10]]);line([[right,bottom+2],[right,bottom+10]]);line([[left,bottom+8],[right,bottom+8]])
            for x in (left,right):line([[x-1.3,bottom+9.3],[x+1.3,bottom+6.7]])
            text((left+right)/2,bottom+6,f'{high[0]-low[0]:.3f}')
            line([[right+2,top],[right+11,top]]);line([[right+2,bottom],[right+11,bottom]]);line([[right+9,top],[right+9,bottom]])
            text(right+14,(top+bottom)/2,f'{high[1]-low[1]:.3f}',2.6)
    from .fits import FitSettings,calculate_fit
    fits=[]
    for study in design.studies:
        if study.kind!='fit':continue
        record=calculate_fit(design,FitSettings.model_validate(study.settings))
        if settings.part_id and settings.part_id not in (record['shaft']['part'],record['hole']['part']):continue
        fits.append(record)
    if fits and settings.extra_view=='none':
        x=width*.74;text(x,22,'DIAMETER LIMITS · mm',3)
        for i,r in enumerate(fits[:4]):
            y=31+i*13
            text(x,y,f"{i+1}. Shaft {r['shaft']['low']:.4f} / {r['shaft']['high']:.4f}",2.7)
            text(x,y+4,f"Hole {r['hole']['low']:.4f} / {r['hole']['high']:.4f}",2.7)
            text(x,y+8,f"IDs: {r['shaft']['part'] or 'manual'} / {r['hole']['part'] or 'manual'}",2.1)
        if len(fits)>4:text(x,87,f'+ {len(fits)-4} fits: see project / fit CSV',2.5)
    line([[7,7],[width-7,7],[width-7,height-7],[7,height-7],[7,7]])
    line([[7,height-28],[width-7,height-28]]);line([[width-100,height-28],[width-100,height-7]])
    text(13,height-19,settings.title,4);text(13,height-11,'mm · Third angle · Overall dimensions',2.5)
    text(width-52,height-19,f'{settings.number} / Rev {settings.revision}',3)
    text(width-52,height-11,f'Scale {scale:.4g}:1 · {settings.page}',2.7)
    if settings.notes:
        for i,row in enumerate(settings.notes.splitlines()[:4]):text(13,height-36-i*3.3,row[:110],2.4)
    return dict(width=width,height=height,scale=scale,paths=paths,texts=texts)


def extra_view(shape,settings):
    import cadquery as cq
    if settings.extra_view=='detail':
        center=np.array(settings.detail_center);radius=settings.detail_radius;lines=[]
        for row in projected_lines(shape,(0,0,1),(1,0,0)):
            for p,q in zip(row['points'],row['points'][1:]):
                a=np.array(p)-center;delta=np.array(q)-np.array(p);length=delta@delta
                if length<1e-18:continue
                b=2*(a@delta);c=a@a-radius**2;disc=b*b-4*length*c
                if disc<0:continue
                low=max(0,(-b-np.sqrt(disc))/(2*length));high=min(1,(-b+np.sqrt(disc))/(2*length))
                if high>low:lines.append(dict(points=[(center+a+delta*t).tolist() for t in (low,high)],hidden=row['hidden']))
        if not lines:raise ValueError('확대할 상면 상세 범위에 선이 없습니다.')
        lines.append(dict(points=[(center+radius*np.array([np.cos(a),np.sin(a)])).tolist() for a in np.linspace(0,2*np.pi,129)],hidden=False))
        return lines,f'DETAIL A · TOP ×{settings.detail_factor:g}',settings.detail_factor
    from .inspection import section
    axis='XYZ'.index(settings.section_axis);normal=[int(i==axis) for i in range(3)];origin=[v*settings.section_offset for v in normal];xd=[0,1,0] if axis==0 else [1,0,0];cut=section(shape,origin,normal);lines=projected_lines(cut,normal,xd);plane=cq.Plane(origin=origin,normal=normal,xDir=xd)
    samples=[plane.toLocalCoords(p) for edge in cut.Edges() for p in edge.sample(24)[0]];x0=min(p.x for p in samples);x1=max(p.x for p in samples);y0=min(p.y for p in samples);y1=max(p.y for p in samples);span=max(x1-x0,y1-y0,1)
    for start in np.arange(x0-span,x1+span,span/25):
        edge=cq.Edge.makeLine(plane.toWorldCoords((start,y0-1)),plane.toWorldCoords((start+y1-y0+2,y1+1)))
        for piece in cut.intersect(edge).Edges():
            points=[plane.toLocalCoords(p) for p in (piece.startPoint(),piece.endPoint())];lines.append(dict(points=[[p.x,p.y] for p in points],hidden=False))
    return lines,f'SECTION A-A · {settings.section_axis}={settings.section_offset:g} mm',1


def drawing_book(design,settings):
    from copy import deepcopy
    first=sheet(design,settings);pages=[first]
    if settings.all_parts:
        for i,part in enumerate(design.parts):
            if part.id==settings.part_id:continue
            page=sheet(design,settings.model_copy(update={'part_id':part.id,'title':part.name,'number':settings.number+'-'+str(i+1),'extra_view':'none','all_parts':False}));pages.append(page)
    for i,page in enumerate(pages):page['texts'].append(dict(x=page['width']-13,y=12,text=f'{i+1}/{len(pages)}',size=2.5))
    return pages


def export_book(pages,path):
    from PySide6.QtCore import QByteArray,QRectF,QSizeF,QMarginsF
    from PySide6.QtGui import QPdfWriter,QPainter,QPageSize,QPageLayout
    from PySide6.QtSvg import QSvgRenderer
    writer=QPdfWriter(str(path));writer.setResolution(300);writer.setPageSize(QPageSize(QSizeF(pages[0]['width'],pages[0]['height']),QPageSize.Unit.Millimeter));writer.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter);painter=QPainter(writer)
    try:
        for i,page in enumerate(pages):
            if i:writer.newPage()
            QSvgRenderer(QByteArray(svg(page).encode())).render(painter,QRectF(0,0,writer.width(),writer.height()))
    finally:painter.end()


def export_bom(design,path):
    import csv
    from .kernel import local_shape
    from .inspection import mass_properties
    rows=[]
    for part in design.parts:
        shape=local_shape(design,part);mass=mass_properties(shape,part.material.density)['mass_kg'] if part.material and shape.Solids() else ''
        rows.append([part.id,part.name,part.source_part_id or part.id,1,part.material.name if part.material else '',mass,shape.Volume() if shape.Solids() else '',part.color])
    with Path(path).open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.writer(stream);writer.writerow(['Part ID','Name','Source ID','Quantity','Material','Mass kg','Volume mm3','Color']);writer.writerows(rows)


def svg(sheet):
    w,h=sheet['width'],sheet['height'];out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">',f'<rect width="{w}" height="{h}" fill="white"/>']
    for path in sheet['paths']:
        points=' '.join(f'{x:.5f},{y:.5f}' for x,y in path['points']);dash=' stroke-dasharray="1.8 1"' if path['hidden'] else '';color='#7b8691' if path['hidden'] else '#202832'
        out.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="0.22"{dash}/>')
    for t in sheet['texts']:
        anchor='start' if t['x']==13 else 'middle';out.append(f'<text x="{t["x"]}" y="{t["y"]}" text-anchor="{anchor}" font-family="Malgun Gothic,Arial" font-size="{t["size"]}" fill="#172330">{escape(t["text"])}</text>')
    return '\n'.join(out+['</svg>'])


def export_sheet(data,path):
    path=Path(path);suffix=path.suffix.lower()
    if suffix=='.svg':path.write_text(svg(data),encoding='utf-8');return
    if suffix=='.dxf':
        import ezdxf
        doc=ezdxf.new('R2010');doc.units=4;doc.linetypes.new('CAD_HIDDEN',dxfattribs={'pattern':[2.8,1.8,-1.]});doc.layers.new('VISIBLE');doc.layers.new('HIDDEN',dxfattribs={'linetype':'CAD_HIDDEN','color':8});space=doc.modelspace()
        for line in data['paths']:space.add_lwpolyline([(x,data['height']-y) for x,y in line['points']],dxfattribs={'layer':'HIDDEN' if line['hidden'] else 'VISIBLE'})
        for t in data['texts']:space.add_text(t['text'],dxfattribs={'height':t['size'],'insert':(t['x'],data['height']-t['y'])})
        doc.saveas(path);return
    if suffix=='.pdf':
        from PySide6.QtCore import QByteArray,QRectF,QSizeF,QMarginsF
        from PySide6.QtGui import QPdfWriter,QPainter,QPageSize,QPageLayout
        from PySide6.QtSvg import QSvgRenderer
        writer=QPdfWriter(str(path));writer.setPageSize(QPageSize(QSizeF(data['width'],data['height']),QPageSize.Unit.Millimeter));writer.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter);writer.setResolution(300)
        painter=QPainter(writer);QSvgRenderer(QByteArray(svg(data).encode())).render(painter,QRectF(0,0,writer.width(),writer.height()));painter.end();return
    raise ValueError('SVG / DXF / PDF 형식으로 저장하세요.')
