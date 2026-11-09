"""Turn a swreader Model into Blender data."""

from __future__ import annotations

import bpy
import numpy as np
from mathutils import Matrix

# SolidWorks is Y-up, Blender is Z-up.
Y_UP_TO_Z_UP = Matrix.Rotation(np.pi / 2, 4, "X")
DEFAULT_APPEARANCE = (200, 200, 200, 1.0)


def _linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _material(appearance, cache):
    material = cache.get(appearance)
    if material is None:
        r, g, b, alpha = appearance
        material = bpy.data.materials.new(f"SW_{r:02X}{g:02X}{b:02X}_{int(alpha * 100):02d}")
        material.diffuse_color = (_linear(r), _linear(g), _linear(b), alpha)
        material.use_nodes = True
        bsdf = next(
            (n for n in material.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"),
            None,
        )
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (_linear(r), _linear(g), _linear(b), 1.0)
            bsdf.inputs["Alpha"].default_value = alpha
        if alpha < 1.0:
            material.surface_render_method = "BLENDED"
        cache[appearance] = material
    return material


def _mesh(name, part, materials):
    mesh = bpy.data.meshes.new(name)
    verts = part.positions.astype(np.float32)
    tris = part.triangles.astype(np.intc)

    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(len(tris) * 3)
    mesh.loops.foreach_set("vertex_index", tris.ravel())
    mesh.polygons.add(len(tris))
    mesh.polygons.foreach_set("loop_start", np.arange(len(tris), dtype=np.intc) * 3)

    # One slot per distinct appearance; each table's appearance selects a slot.
    slots: dict[tuple, int] = {}
    table_slot = np.zeros(max(len(part.appearances), 1), np.intc)
    for index, appearance in enumerate(part.appearances):
        appearance = appearance or DEFAULT_APPEARANCE
        if appearance not in slots:
            slots[appearance] = len(slots)
            mesh.materials.append(_material(appearance, materials))
        table_slot[index] = slots[appearance]
    if len(slots) > 1:
        mesh.polygons.foreach_set("material_index", table_slot[part.triangle_table])

    mesh.update()
    mesh.validate(clean_customdata=False)
    if part.normals is not None and len(tris) and len(mesh.polygons) == len(tris):
        mesh.shade_smooth()
        mesh.normals_split_custom_set(part.normals.reshape(-1, 3))
    return mesh


def build(model, context, y_up_to_z_up=True, import_hidden=True, progress=None):
    """Create the objects in a new collection and return the root object."""
    collection = bpy.data.collections.new(model.root.name)
    context.scene.collection.children.link(collection)

    materials: dict[tuple, bpy.types.Material] = {}
    meshes: dict[str, bpy.types.Mesh] = {}
    objects: list[tuple[bpy.types.Object, bool]] = []
    total = len(model.parts)

    def mesh_for(key):
        mesh = meshes.get(key)
        if mesh is None:
            mesh = _mesh(model.part_names[key], model.parts[key], materials)
            meshes[key] = mesh
            if progress is not None:
                progress(len(meshes) / max(total, 1))
        return mesh

    def add(node, parent, hidden, inherited):
        hidden = hidden or node.hidden
        if hidden and not import_hidden:
            return None
        appearance = inherited or node.appearance
        data = mesh_for(node.part) if node.part is not None else None
        obj = bpy.data.objects.new(node.name, data)
        if data is None:
            obj.empty_display_size = 0.05
        collection.objects.link(obj)
        # An appearance set in the assembly overrides the part's, for this instance.
        if data is not None and appearance is not None:
            for slot in obj.material_slots:
                slot.link = "OBJECT"
                slot.material = _material(appearance, materials)
        obj.parent = parent
        obj.matrix_local = Matrix(node.matrix.tolist())
        objects.append((obj, hidden))
        for child in node.children:
            add(child, obj, hidden, appearance)
        return obj

    root = add(model.root, None, False, None)
    # The model is in metres; keep its real size whatever the scene's unit scale.
    scale = context.scene.unit_settings.scale_length or 1.0
    orient = Y_UP_TO_Z_UP if y_up_to_z_up else Matrix.Identity(4)
    root.matrix_local = Matrix.Scale(1.0 / scale, 4) @ orient @ root.matrix_local

    context.view_layer.update()
    for obj, hidden in objects:
        if hidden:
            obj.hide_set(True)
            obj.hide_render = True

    return root
