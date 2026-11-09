"""Read SolidWorks parts and assemblies from their saved display meshes.

No SolidWorks needed and no Blender dependency: this package needs only the
standard library and numpy.
"""

from __future__ import annotations

import os
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

from .container import find_block, read_blocks
from .displaylist import DecodedPart, Section, decode_tables, read_sections, read_tables

DISPLAY_LISTS = "Contents/DisplayLists"
INSTANCE_TREE = "swXmlContents/COMPINSTANCETREE"
MAX_DEPTH = 32


class SolidWorksError(Exception):
    """The file cannot be imported; the message is meant for the user."""


@dataclass
class Node:
    """One placed component. `part` keys `Model.parts`; None for a subassembly or a miss."""

    name: str
    matrix: np.ndarray  # 4x4, column vectors, metres, relative to the parent
    hidden: bool = False
    part: str | None = None
    missing: bool = False
    appearance: tuple | None = None  # (r, g, b, alpha) set on this instance in the assembly
    children: list["Node"] = field(default_factory=list)


@dataclass
class Model:
    root: Node
    parts: dict[str, DecodedPart]
    part_names: dict[str, str]
    missing: list[str] = field(default_factory=list)
    from_part_files: list[str] = field(default_factory=list)
    config_fallback: list[str] = field(default_factory=list)
    suppressed: int = 0
    undrawn: int = 0
    placement_drift: float = 0.0  # metres, tree placement against the display list's
    rotation_drift: float = 0.0  # largest rotation matrix element difference, same check
    bounding_box: tuple[np.ndarray, np.ndarray] | None = None
    configuration: str = ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _file_name(path: str) -> str:
    return re.split(r"[\\/]", path or "")[-1]


def _stem(path: str) -> str:
    return os.path.splitext(_file_name(path))[0]


def _matrix(text: str | None) -> np.ndarray:
    """A saved placement as a column-vector matrix.

    SolidWorks stores row-major for row vectors (p' = p M), so this is a
    transpose. Mirrored components keep their negative determinant.
    """
    values = [float(v) for v in (text or "").split()]
    if len(values) != 16:
        return np.identity(4)
    return np.array(values).reshape(4, 4).T


def _hidden_by_display_state(configuration) -> set[str]:
    """`swID`s of the top-level components the active display state hides."""
    state_name = (configuration.get("swLinkDS") or "").split(",")[0]
    for state_list in configuration:
        if _local(state_list.tag) != "swDisplayStateList":
            continue
        ids = (state_list.get("swCompNameList") or "").split(",")
        for state in state_list:
            if state.get("swDisplayStateName") == state_name:
                shown = (state.get("swShowState") or "").split(",")
                return {i for i, s in zip(ids, shown) if s == "No"}
    return set()


def _parse_box(text: str | None):
    values = [float(v) for v in (text or "").split()]
    if len(values) != 6:
        return None
    return np.array(values[:3]), np.array(values[3:])


class _PartFiles:
    """Part files beside the assembly, for components the assembly did not cache."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.index: dict[str, Path] | None = None

    def find(self, name: str) -> Path | None:
        if self.index is None:
            self.index = {}
            for dirpath, _dirs, files in os.walk(self.folder):
                for file in files:
                    if file.lower().endswith(".sldprt") and not file.startswith("~$"):
                        self.index.setdefault(file.lower(), Path(dirpath) / file)
        return self.index.get(name.lower())


def _read_part_file(path: Path) -> DecodedPart | None:
    blocks = read_blocks(path.read_bytes())
    block = find_block(blocks, DISPLAY_LISTS)
    if block is None:
        return None
    data = block.inflate()
    tables = read_tables(data)
    if not tables:
        return None
    read_sections(data, tables)
    return decode_tables(data, tables)


def read_part(path: str | os.PathLike) -> Model:
    path = Path(path)
    decoded = _read_part_file(path)
    if decoded is None or not len(decoded.triangles):
        raise SolidWorksError(
            f"{path.name} has no saved display mesh. Open and save it in SolidWorks "
            "with display data, or export it to STEP or STL."
        )
    key = path.stem
    root = Node(path.stem, np.identity(4), part=key)
    return Model(root, {key: decoded}, {key: path.stem})


def read_assembly(path: str | os.PathLike) -> Model:
    path = Path(path)
    blocks = read_blocks(path.read_bytes())
    tree_block = find_block(blocks, INSTANCE_TREE)
    display_block = find_block(blocks, DISPLAY_LISTS)
    if tree_block is None:
        raise SolidWorksError(f"{path.name} has no component tree; it is not a readable assembly.")

    xml = ElementTree.fromstring(tree_block.inflate().decode("utf-8", "replace"))
    sections: list[Section] = []
    data = b""
    if display_block is not None:
        data = display_block.inflate()
        sections, _loose = read_sections(data, read_tables(data))

    by_instance = {s.instance: s for s in sections}
    by_file_config: dict[tuple[str, str], Section] = {}
    by_file: dict[str, Section] = {}
    for section in sections:
        if section.tables:
            by_file_config.setdefault((section.file.lower(), section.config.lower()), section)
            by_file.setdefault(section.file.lower(), section)

    def children_named(parent, tag):
        return [c for c in parent if _local(c.tag) == tag]

    def only(tag):
        found = children_named(xml, tag)
        if len(found) != 1:
            raise SolidWorksError(f"{path.name}: the component tree has no single {tag}.")
        return found[0]

    files = {f.get("id"): f for f in children_named(only("swHeader"), "swFile")}
    models = {m.get("id"): m for m in children_named(only("swModelList"), "swModel")}
    configurations = children_named(only("swConfigurationList"), "swConfiguration")
    active = next(
        (c for c in configurations if c.get("swMostRecentConfiguration") == "YES"),
        configurations[0] if configurations else None,
    )
    root_model = models.get(active.get("swModelRef")) if active is not None else None
    if root_model is None:
        raise SolidWorksError(f"{path.name}: the active configuration could not be resolved.")

    model = Model(
        Node(path.stem, np.identity(4)), {}, {},
        bounding_box=_parse_box(root_model.get("swBoundingBox")),
        configuration=active.get("swName") or "",
    )
    part_files = _PartFiles(path.parent)
    shown_off = _hidden_by_display_state(active)
    decoded_sections: dict[int, str] = {}

    def file_of(model_el):
        record = files.get(model_el.get("swFileRef"))
        return record.get("swPath", "") if record is not None else "", (
            record.get("swDocType", "") if record is not None else ""
        )

    def part_for(instance: str, file: str, config: str, name: str) -> str | None:
        section = by_instance.get(instance)
        if section is None or not section.tables:
            section = by_file_config.get((file.lower(), config.lower()))
            if section is None:
                section = by_file.get(file.lower())
                if section is not None:
                    model.config_fallback.append(name)
        if section is not None:
            key = decoded_sections.get(id(section))
            if key is None:
                decoded = decode_tables(data, section.tables)
                key = f"{file}|{config}|{len(decoded_sections)}" if len(decoded.triangles) else ""
                decoded_sections[id(section)] = key
                if key:
                    model.parts[key] = decoded
                    model.part_names[key] = _stem(file)
            if key:
                return key

        key = f"file:{file.lower()}"
        if key in model.parts:
            return key
        found = part_files.find(file)
        try:
            decoded = _read_part_file(found) if found else None
        except OSError:
            decoded = None
        if decoded is None or not len(decoded.triangles):
            return None
        model.parts[key] = decoded
        model.part_names[key] = _stem(file)
        model.from_part_files.append(file)
        return key

    def walk(model_el, node, scope, depth, parent_world, hidden=False):
        parent_stem = _stem(file_of(model_el)[0])
        for reference in children_named(model_el, "swReference"):
            if reference.get("swSuppressed") == "YES":
                model.suppressed += 1
                continue
            child = models.get(reference.get("swModelRef"))
            name = f"{reference.get('swName')}-{reference.get('swReferenceNumber')}"
            step = f"{name}@{parent_stem}"
            instance = f"{scope}/{step}" if scope else step
            section = by_instance.get(instance)
            child_node = Node(
                name,
                _matrix(reference.get("swTransform")),
                hidden=(
                    reference.get("swHidden") == "YES"
                    or (depth == 0 and reference.get("swID") in shown_off)
                    or (section is not None and section.hidden)
                ),
                appearance=section.appearance if section is not None else None,
            )
            world = parent_world @ child_node.matrix
            if section is not None and section.world is not None:
                drift = float(np.abs(section.world[:3, 3] - world[:3, 3]).max())
                model.placement_drift = max(model.placement_drift, drift)
                turn = float(np.abs(section.world[:3, :3] - world[:3, :3]).max())
                model.rotation_drift = max(model.rotation_drift, turn)
            node.children.append(child_node)
            if child is None:
                child_node.missing = True
                model.missing.append(name)
                continue

            file_path, doc_type = file_of(child)
            if doc_type == "ASSEMBLY":
                if depth < MAX_DEPTH:
                    walk(child, child_node, instance, depth + 1, world, hidden or child_node.hidden)
                continue

            if section is not None and not section.drawn:
                node.children.pop()
                model.undrawn += 1
                continue

            config = reference.get("swConfigurationName") or ""
            child_node.part = part_for(instance, _file_name(file_path), config, name)
            if child_node.part is None:
                child_node.missing = True
                if not hidden and not child_node.hidden:
                    model.missing.append(name)

    walk(root_model, model.root, "", 0, np.identity(4))

    if not model.parts:
        raise SolidWorksError(
            f"{path.name} holds no saved meshes for its components and no part files "
            "were found beside it. Put the assembly and its parts in one folder "
            "(Pack and Go), then import again."
        )
    return model


def read_file(path: str | os.PathLike) -> Model:
    """Read a .SLDPRT or .SLDASM."""
    suffix = Path(path).suffix.lower()
    if suffix not in (".sldprt", ".sldasm"):
        raise SolidWorksError(f"Unsupported file type: {suffix or 'no extension'}")
    try:
        return read_part(path) if suffix == ".sldprt" else read_assembly(path)
    except (ElementTree.ParseError, ValueError, struct.error, zlib.error) as exc:
        raise SolidWorksError(f"{Path(path).name} could not be read: {exc}") from exc


def world_bounds(model: Model) -> tuple[np.ndarray, np.ndarray] | None:
    """Overall bounds of the visible geometry, metres, in SolidWorks axes."""
    lows, highs = [], []

    def visit(node: Node, parent: np.ndarray):
        matrix = parent @ node.matrix
        if node.hidden:
            return
        if node.part is not None:
            verts = model.parts[node.part].positions.astype(np.float64)
            placed = verts @ matrix[:3, :3].T + matrix[:3, 3]
            lows.append(placed.min(axis=0))
            highs.append(placed.max(axis=0))
        for child in node.children:
            visit(child, matrix)

    visit(model.root, np.identity(4))
    if not lows:
        return None
    return np.min(lows, axis=0), np.max(highs, axis=0)
