from pathlib import Path
native_spec=Path(SPECPATH)/'NativeCAD.spec'
exec(compile(native_spec.read_text(encoding='utf-8'),str(native_spec),'exec'))
