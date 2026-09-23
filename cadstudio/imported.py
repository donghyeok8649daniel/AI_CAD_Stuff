"""Portable embedded BREP assets; no source path is needed after import."""
import base64,hashlib,io,zlib
from pathlib import Path
from functools import lru_cache
import cadquery as cq
from .models import ShapeAsset

MAX_BREP=64_000_000


def encode_shape(shape,name,format='brep'):
    if not shape.isValid() or not shape.Faces():raise ValueError('가져온 CAD 형상이 유효하지 않습니다.')
    stream=io.BytesIO();shape.exportBrep(stream);raw=stream.getvalue()
    if len(raw)>MAX_BREP:raise ValueError('가져온 BREP가 64 MB를 넘습니다. 부품별로 나누어 가져오세요.')
    return ShapeAsset(name=Path(name).name,format=format,data=base64.b64encode(zlib.compress(raw,6)).decode('ascii'),sha256=hashlib.sha256(raw).hexdigest())


@lru_cache(maxsize=12)
def decode_shape(data,sha256):
    encoded=base64.b64decode(data,validate=True);decoder=zlib.decompressobj();raw=decoder.decompress(encoded,MAX_BREP+1)
    if len(raw)>MAX_BREP or not decoder.eof or decoder.unused_data:raise ValueError('CAD 데이터 크기 또는 압축 형식이 잘못됐습니다.')
    if hashlib.sha256(raw).hexdigest()!=sha256:raise ValueError('가져온 부품 데이터의 해시가 일치하지 않습니다.')
    shape=cq.Shape.importBrep(io.BytesIO(raw))
    if not shape.isValid() or not shape.Faces():raise ValueError('가져온 부품을 복원할 수 없습니다.')
    return shape


def import_asset(path):
    path=Path(path)
    if path.stat().st_size>MAX_BREP:raise ValueError('가져올 파일은 64 MB 이하여야 합니다.')
    suffix=path.suffix.lower()
    if suffix in ('.step','.stp'):
        objects=cq.importers.importStep(str(path)).vals();shape=cq.Compound.makeCompound(objects) if len(objects)>1 else objects[0];fmt='step'
    elif suffix in ('.iges','.igs'):
        from OCP.IGESControl import IGESControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        reader=IGESControl_Reader()
        if reader.ReadFile(str(path))!=IFSelect_RetDone:raise ValueError('IGES 파일을 읽지 못했습니다.')
        reader.TransferRoots();shape=cq.Shape.cast(reader.OneShape());fmt='iges'
    elif suffix=='.stl':
        from OCP.StlAPI import StlAPI_Reader
        from OCP.TopoDS import TopoDS_Shape
        result=TopoDS_Shape()
        if not StlAPI_Reader().Read(result,str(path)):raise ValueError('STL 파일을 읽지 못했습니다.')
        shape=cq.Shape.cast(result);fmt='stl'
        if len(shape.Faces())>20000:raise ValueError('STL 삼각형이 20,000개를 넘습니다. 메시를 줄인 뒤 가져오세요.')
    elif suffix=='.brep':shape=cq.Shape.importBrep(str(path));fmt='brep'
    else:raise ValueError('STEP, IGES, STL, BREP 파일을 선택하세요.')
    return encode_shape(shape,path.name,fmt)
