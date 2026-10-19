"""STL sampling is independent of display triangulation and cached preview LOD."""
import cadquery as cq


def export_stl(shapes,path,*,tolerance=.025):
    # Copy analytic geometry without its display triangles. OCCT otherwise
    # refines an existing display mesh differently depending on prior LOD.
    source=[shape.copy(mesh=False) for shape in shapes]
    cq.exporters.export(cq.Compound.makeCompound(source),str(path),exportType='STL',
        tolerance=tolerance,angularTolerance=.1)
