# Blender SolidWorks Importer

Import SolidWorks `.SLDPRT` parts and `.SLDASM` assemblies into Blender. You don't need SolidWorks or a converter.

The add-on reads the display meshes SolidWorks saves inside each file. Most assemblies therefore open without their part files beside them.

## Install

1. Download `solidworks_import-<version>.zip` from the [Releases](../../releases) page. Don't unzip it.
2. In Blender, open **Edit > Preferences > Get Extensions**.
3. Click the **▾** menu at the top right, choose **Install from Disk…**, and pick the zip.
4. Check that **SolidWorks Import** is enabled in the list.

Or from a terminal:

    blender --command extension install-file -r user_default --enable solidworks_import-0.1.0.zip

Requires Blender 4.2 or newer. Tested on Blender 5.2.

## Use

- **Drag and drop** a `.SLDASM` or `.SLDPRT` file onto the 3D viewport or the outliner, or
- **File > Import > SolidWorks (.sldasm, .sldprt)**.

You get:

- one collection with the assembly tree as a parent hierarchy
- one object per component, at real size in metres; identical parts share one mesh
- colours and transparency from the file
- components hidden in SolidWorks, imported but hidden in Blender. Turn off **Import Hidden Components** in the file browser to skip them.

## Limits

- **Mesh only:** the geometry is the display mesh SolidWorks saved. Its density follows the file's image quality setting, and there is no editable CAD data.
- **Configuration:** only the configuration the file was last saved in is imported.
- **Missing meshes:** for a component with no saved mesh, the add-on looks for its `.SLDPRT` in the assembly's folder and subfolders. If it isn't found, the component becomes an empty and is named in a warning.
- **Older storage form:** assemblies that store meshes in a `FaceTessellations` block aren't supported yet.
- **Reverse-engineered format:** the per-instance layout of assemblies was worked out from real files, not from a specification, so some SolidWorks versions may behave differently. Please open an issue if a file doesn't import correctly.

## Development

    "<blender>/<version>/python/bin/python.exe" tests/test_reader.py
    blender --command extension build --source-dir solidworks_import --output-dir dist

`tools/` holds the scripts used to check the importer against real CAD files.

## License

GPL-3.0-or-later. Parts are adapted from [sldprt-export](https://github.com/XRTC5/sldprt-export) (MIT); see [`solidworks_import/THIRD_PARTY.md`](solidworks_import/THIRD_PARTY.md).

SolidWorks is a trademark of Dassault Systèmes. This project is independent of it.
