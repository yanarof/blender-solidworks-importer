# Third-party notices

## sldprt-export

`swreader/container.py` and the strip-table parsing in `swreader/displaylist.py` are adapted from
[sldprt-export](https://github.com/XRTC5/sldprt-export), MIT licensed. See `LICENSE-sldprt-export.txt`.

## cadmpeg format documentation

The container layout, the strip-table descriptors, the instance tree and the visual-property layout
follow the format documentation of [cadmpeg](https://github.com/cadmpeg/cadmpeg), licensed CC BY 4.0.
No cadmpeg code is included.

## Not from these sources

These were worked out from real assemblies, so they may not hold for every SolidWorks version:
per-instance sections in an assembly's `Contents/DisplayLists`, the world placement and bounds after
each instance path, the empty-bounds marker, and the list of hiding display states after the file path.

SolidWorks is a trademark of Dassault Systèmes. This project is independent of it.
