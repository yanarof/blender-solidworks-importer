"""Import SolidWorks parts and assemblies into Blender without SolidWorks.

Adds File > Import > SolidWorks and drag and drop of .sldasm / .sldprt files.
"""

import time
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, StringProperty
from bpy.types import FileHandler, Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper

from . import builder
from .swreader import SolidWorksError, read_file

MAX_LISTED = 8


class IMPORT_SCENE_OT_solidworks(Operator, ImportHelper):
    """Import a SolidWorks assembly or part from its saved display meshes"""

    bl_idname = "import_scene.solidworks"
    bl_label = "Import SolidWorks"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".sldasm"
    filter_glob: StringProperty(default="*.sldasm;*.sldprt", options={"HIDDEN"})
    files: CollectionProperty(type=OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    y_up_to_z_up: BoolProperty(
        name="Y Up to Z Up",
        description="Rotate the model so it stands upright in Blender",
        default=True,
    )
    import_hidden: BoolProperty(
        name="Import Hidden Components",
        description="Keep components hidden in SolidWorks, hidden in the outliner",
        default=True,
    )

    def _paths(self):
        if self.files and self.directory:
            return [Path(self.directory) / f.name for f in self.files if f.name]
        return [Path(self.filepath)]

    def invoke(self, context, event):
        # A dropped file arrives with its path set: no file browser. A path merely
        # remembered from the last import does not count as set.
        if self.files or self.properties.is_property_set("filepath"):
            return self.execute(context)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        window_manager = context.window_manager
        imported = 0
        window_manager.progress_begin(0, 100)
        try:
            for path in self._paths():
                try:
                    imported += self._import_one(context, path, window_manager)
                except (SolidWorksError, OSError) as exc:
                    self.report({"ERROR"}, str(exc))
        finally:
            window_manager.progress_end()
        return {"FINISHED"} if imported else {"CANCELLED"}

    def _import_one(self, context, path, window_manager):
        started = time.time()
        model = read_file(path)
        root = builder.build(
            model, context,
            y_up_to_z_up=self.y_up_to_z_up,
            import_hidden=self.import_hidden,
            progress=lambda f: window_manager.progress_update(int(f * 100)),
        )

        for obj in context.selected_objects:
            obj.select_set(False)
        root.select_set(True)
        context.view_layer.objects.active = root

        triangles = sum(len(p.triangles) for p in model.parts.values())
        self.report(
            {"INFO"},
            f"{path.name}: {len(model.parts)} parts, {triangles:,} triangles "
            f"in {time.time() - started:.1f}s",
        )
        if model.missing:
            names = ", ".join(sorted(set(model.missing))[:MAX_LISTED])
            self.report(
                {"WARNING"},
                f"{path.name}: {len(model.missing)} components have no saved mesh and were "
                f"not imported: {names}",
            )
        if model.config_fallback:
            names = ", ".join(sorted(set(model.config_fallback))[:MAX_LISTED])
            self.report(
                {"WARNING"},
                f"{path.name}: {len(model.config_fallback)} components use another configuration's "
                f"mesh, because theirs was not saved: {names}",
            )
        return 1

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "y_up_to_z_up")
        layout.prop(self, "import_hidden")


class IO_FH_solidworks(FileHandler):
    bl_idname = "IO_FH_solidworks"
    bl_label = "SolidWorks"
    bl_import_operator = "import_scene.solidworks"
    bl_file_extensions = ".sldasm;.sldprt"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type in {"VIEW_3D", "OUTLINER"}


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_solidworks.bl_idname, text="SolidWorks (.sldasm, .sldprt)")


classes = (IMPORT_SCENE_OT_solidworks, IO_FH_solidworks)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
