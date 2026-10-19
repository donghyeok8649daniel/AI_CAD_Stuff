"""Bounded JSON cache of this user's authenticated, completed open previews.

Never reads pickle/code. A hit requires checked project bytes, complete input
Design, exact app build/runtime and display policy. Cache failure is a miss.
The key is cache-specific, not a login/session/AI credential.
"""
from hashlib import sha256
import hmac,json,math,os,re,secrets,stat,zlib
from pathlib import Path
from . import __build_id__
from .models import Design

MAGIC=b'PCAD_VERIFIED_PREVIEW_1\n'
MAX_PACKED=64*1024**2
MAX_RAW=256*1024**2
MAX_FILES=4
MAX_TOTAL=256*1024**2
NAME=re.compile(r'[0-9a-f]{64}[.]preview\Z')


def regular(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        try:s=item.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:raise OSError('Reparse cache path')
    return path


def design_digest(design):return sha256(design.model_dump_json().encode('utf-8')).hexdigest()


class VerifiedPreviewCache:
    def __init__(self,folder):self.folder=Path(folder);self.error=None

    def binding(self,file_sha,design,quality):
        assert re.fullmatch('[0-9a-f]{64}',file_sha) and quality in ('auto','fine','fast')
        # OCP identifies the actual native runtime, even for source development.
        import OCP
        return dict(schema=1,build=__build_id__,runtime=getattr(OCP,'__version__','unknown'),
            file_sha256=file_sha,design_sha256=design_digest(design),quality=quality,
            part_ids=[p.id for p in design.parts])

    def _key(self,create=False):
        folder=regular(self.folder)
        if create:folder.mkdir(parents=True,exist_ok=True)
        path=regular(folder/'cache-key.bin')
        try:
            if path.stat().st_nlink!=1:raise ValueError('Linked cache key')
            with path.open('rb') as stream:key=stream.read(33)
        except FileNotFoundError:
            if not create:return None
            key=secrets.token_bytes(32)
            try:
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:return self._key(False)
            with os.fdopen(fd,'wb') as stream:stream.write(key);stream.flush();os.fsync(stream.fileno())
        if len(key)!=32:raise ValueError('Invalid cache key')
        return key

    def _path(self,binding):
        token=sha256(json.dumps(binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return regular(self.folder/(token+'.preview'))

    def _read(self,path,key):
        path=regular(path)
        if not path.is_file() or path.stat().st_size>MAX_PACKED+4096:raise ValueError('Cache size')
        if path.stat().st_nlink!=1:raise ValueError('Linked cache data')
        with path.open('rb') as stream:
            if stream.read(len(MAGIC))!=MAGIC:raise ValueError('Cache format')
            header=stream.readline(2049)
            if len(header)>2048 or not header.endswith(b'\n'):raise ValueError('Cache header')
            tag=stream.read(32);packed=stream.read(MAX_PACKED+1)
        if len(packed)>MAX_PACKED or not hmac.compare_digest(tag,hmac.digest(key,header+packed,'sha256')):
            raise ValueError('Cache authentication')
        meta=json.loads(header)
        if type(meta['raw_bytes']) is not int or not 0<meta['raw_bytes']<=MAX_RAW:raise ValueError('Cache raw size')
        decoder=zlib.decompressobj();raw=decoder.decompress(packed,meta['raw_bytes']+1)
        if len(raw)!=meta['raw_bytes'] or not decoder.eof or decoder.unused_data:raise ValueError('Cache compression')
        def reject(value):raise ValueError('Nonfinite cache number')
        return meta,json.loads(raw,parse_constant=reject)

    def get(self,binding):
        try:
            key=self._key()
            if key is None:return None
            path=self._path(binding);meta,value=self._read(path,key)
            if meta['binding_sha256']!=path.stem:raise ValueError('Cache input binding')
            resolved=Design.model_validate(value['design']);result=value['preview']
            from .preview_metadata import geometry_key
            if (result.get('_geometry_key')!=geometry_key(resolved) or result.get('_display_quality')!=binding['quality']
                    or result['stats']['valid'] is not True or result['stats']['parts']!=len(binding['part_ids'])
                    or [m['id'] for m in result['meshes']]!=binding['part_ids']
                    or [p.id for p in resolved.parts]!=binding['part_ids']):raise ValueError('Cache result binding')
            try:os.utime(path,None)
            except OSError:pass
            return resolved,result
        except (OSError,ValueError,KeyError,TypeError,OverflowError,zlib.error,MemoryError) as exc:
            self.error=type(exc).__name__;return None

    def put(self,binding,design,result):
        try:
            if result['stats']['valid'] is not True:return False
            from .preview_metadata import geometry_key
            if (result.get('_geometry_key')!=geometry_key(design) or result.get('_display_quality')!=binding['quality']
                    or [m['id'] for m in result['meshes']]!=binding['part_ids']):return False
            # Names/colors can change without geometry. Persist current saved
            # metadata around immutable arrays instead of stale UI labels.
            result={**result,'meshes':[dict(mesh,name=part.name,color=part.color) for mesh,part in zip(result['meshes'],design.parts)]}
            raw=json.dumps(dict(design=design.model_dump(),preview=result),ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
            if len(raw)>MAX_RAW:return False
            packed=zlib.compress(raw,1);size=len(raw);del raw
            if len(packed)>MAX_PACKED:return False
            key=self._key(True);path=self._path(binding)
            header=(json.dumps(dict(binding_sha256=path.stem,raw_bytes=size),sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
            if len(header)>2048:return False
            from .native.document import _atomic_project_write
            _atomic_project_write(path,MAGIC+header+hmac.digest(key,header+packed,'sha256')+packed)
            self._prune(key,path)
            return True
        except (OSError,ValueError,KeyError,TypeError,OverflowError,zlib.error,MemoryError) as exc:
            self.error=type(exc).__name__;return False

    def _prune(self,key,current):
        # Delete only regular cache files authenticated by this app's own key.
        rows=[]
        for path in regular(self.folder).iterdir():
            if not NAME.fullmatch(path.name):continue
            try:
                path=regular(path);info=path.stat()
                if not stat.S_ISREG(info.st_mode):continue
                rows.append((info.st_mtime_ns,path,info.st_size))
            except OSError:continue
        total=sum(size for _,_,size in rows);count=len(rows)
        for _,path,size in sorted(rows):
            if count<=MAX_FILES and total<=MAX_TOTAL:break
            if path==current:continue
            try:
                self._read(path,key)
                path.unlink();total-=size;count-=1
            except (OSError,ValueError,KeyError,TypeError,zlib.error):continue
