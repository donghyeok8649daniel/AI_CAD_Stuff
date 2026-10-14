"""Small, process-local mesh cache. Never stores verification verdicts or BReps.

The pickle payload is created here from our own kernel output and is never read
from project files, disk, AI responses or other external inputs.
"""
from collections import OrderedDict
import io
import pickle
import zlib


class _TooLarge(ValueError):
    pass


class _BoundedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__();self.limit=limit

    def write(self, data):
        if self.tell()+len(data)>self.limit:raise _TooLarge('Mesh cache admission limit')
        return super().write(data)


class MeshCache:
    def __init__(self, max_bytes=16*1024**2, max_entries=3, max_raw_bytes=64*1024**2):
        self.max_bytes=max_bytes;self.max_entries=max_entries;self.max_raw_bytes=max_raw_bytes
        self.items=OrderedDict();self.bytes=0;self.hits=0;self.misses=0

    def clear(self):
        self.items.clear();self.bytes=0;self.hits=0;self.misses=0

    def get(self,key):
        entry=self.items.get(key)
        if entry is None:self.misses+=1;return None
        packed,size=entry
        try:
            decoder=zlib.decompressobj();raw=decoder.decompress(packed,self.max_raw_bytes+1)
            if len(raw)!=size or len(raw)>self.max_raw_bytes or not decoder.eof or decoder.unused_data:
                raise ValueError('Invalid internal mesh cache entry')
            result=pickle.loads(raw)
        except (ValueError,zlib.error,pickle.UnpicklingError,EOFError,MemoryError):
            self.bytes-=len(packed);del self.items[key];self.misses+=1;return None
        self.items.move_to_end(key);self.hits+=1
        return result

    def put(self,key,meshes):
        try:
            with _BoundedBuffer(self.max_raw_bytes) as stream:
                pickle.Pickler(stream,protocol=5).dump(meshes)
                packed=zlib.compress(stream.getvalue(),1)
                size=stream.tell()
        except (MemoryError,_TooLarge):return False
        if len(packed)>self.max_bytes or self.max_entries<1:return False
        old=self.items.pop(key,None)
        if old:self.bytes-=len(old[0])
        while self.items and (len(self.items)>=self.max_entries or self.bytes+len(packed)>self.max_bytes):
            _,entry=self.items.popitem(last=False);self.bytes-=len(entry[0])
        self.items[key]=(packed,size);self.bytes+=len(packed)
        return True

    def info(self):
        return dict(entries=len(self.items),compressed_bytes=self.bytes,max_bytes=self.max_bytes,
                    max_raw_bytes=self.max_raw_bytes,hits=self.hits,misses=self.misses)
