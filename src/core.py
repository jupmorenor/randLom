"""Core randomizer operations."""

from __future__ import annotations

import random
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from src.third_party.lom_decomp_compression.compressor import compress as _compress_overlay
from src.third_party.lom_decomp_compression.decompress import decompress as _decompress_overlay
from src.lang import get_text


LEGEND_OF_MANA_DISC_IDS = (b"SLUS_010.13", b"SLPS_021.70")

_FIELD_MONSTER_LEVEL_TABLE = {
    "us": {"load_address": 0x8004FC70, "table_address": 0x800F0AE8},
    "jp": {"load_address": 0x8004FDD8, "table_address": 0x800F05F8},
}
_FIELD_MONSTER_LEVEL_RANK_COUNT = 64
_FIELD_RUN_FUNCTION = {
    "us": {"load_address": 0x8004FC70, "function_address": 0x80091AC8},
    "jp": {"load_address": 0x8004FDD8, "function_address": 0x80091554},
}


def _error_message(key: str, **values: object) -> str:
    """Return a localized error string, formatting any supplied values."""
    return get_text(key).format(**values)


def is_legend_of_mana_disc(disc_image: str | Path) -> bool:
    """Check whether a raw PlayStation disc image contains a supported game ID."""
    image = Path(disc_image).expanduser().resolve()
    if not image.is_file():
        return False

    image_files = [image]
    if image.suffix.lower() == ".cue":
        cue_text = image.read_text(encoding="utf-8", errors="replace")
        image_files = []
        for filename in re.findall(r'^\s*FILE\s+"?(.+?)"?\s+(?:BINARY|MOTOROLA|WAVE|AIFF|MP3)', cue_text, re.IGNORECASE | re.MULTILINE):
            track = (image.parent / filename).resolve()
            if track.is_file():
                image_files.append(track)
    elif image.suffix.lower() in {".ccd", ".mds"}:
        companion_suffix = ".img" if image.suffix.lower() == ".ccd" else ".mdf"
        companion = image.with_suffix(companion_suffix)
        if companion.is_file():
            image_files.append(companion)

    identifiers = tuple(identifier.lower() for identifier in LEGEND_OF_MANA_DISC_IDS)
    overlap = max(map(len, identifiers)) - 1
    for image_file in image_files:
        tail = b""
        try:
            with image_file.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    data = (tail + chunk).lower()
                    if any(identifier in data for identifier in identifiers):
                        return True
                    tail = data[-overlap:]
        except OSError:
            continue
    return False


def _detect_disc_region(project: Path, bin_directory: Path) -> str:
    if (bin_directory / "SLUS_010.13").is_file():
        return "us"
    if (bin_directory / "SLPS_021.70").is_file():
        return "jp"

    system_config = project / "SYSTEM.CNF"
    config_text = (
        system_config.read_text(encoding="ascii", errors="ignore").upper()
        if system_config.is_file()
        else ""
    )
    if "SLUS_010.13" in config_text:
        return "us"
    if "SLPS_021.70" in config_text:
        return "jp"
    raise RuntimeError(_error_message("error_game_region_unknown"))


def _read_decompressed_field(field_overlay: Path) -> bytearray:
    original_overlay = field_overlay.read_bytes()
    if not original_overlay or original_overlay[0] != 0x01:
        raise ValueError(_error_message("error_field_compression_format"))
    decompressed = bytearray(b"\x01")
    decompressed.extend(_decompress_overlay(original_overlay[1:]))
    return decompressed


def _write_compressed_field(field_overlay: Path, decompressed: bytes) -> None:
    compressed_overlay = b"\x01" + _compress_overlay(decompressed[1:])
    if bytes(_decompress_overlay(compressed_overlay[1:])) != decompressed[1:]:
        raise RuntimeError(_error_message("error_field_recompression_verification"))

    temporary_overlay = field_overlay.with_name(field_overlay.name + ".tmp")
    temporary_overlay.write_bytes(compressed_overlay)
    temporary_overlay.replace(field_overlay)


def _randomize_land_levels_data(
    decompressed: bytearray, region: str, seed: int
) -> int:
    layout = _FIELD_MONSTER_LEVEL_TABLE[region]
    table_offset = layout["table_address"] - layout["load_address"]
    table_end = table_offset + _FIELD_MONSTER_LEVEL_RANK_COUNT
    if table_offset < 0 or table_end > len(decompressed):
        raise ValueError(_error_message("error_field_level_table_bounds"))

    table = list(decompressed[table_offset:table_end])
    if any(level > 99 for level in table) or table[0] != 0:
        raise ValueError(_error_message("error_field_level_table_values"))

    original_values = table[1:]
    shuffled_values = original_values.copy()
    rng = random.Random(seed)
    for _ in range(512):
        rng.shuffle(shuffled_values)
        if shuffled_values != original_values:
            break
    else:
        return 0

    changed = sum(old != new for old, new in zip(original_values, shuffled_values))
    decompressed[table_offset + 1:table_end] = bytes(shuffled_values)
    return changed


def _enable_autorun_data(decompressed: bytearray, region: str) -> bool:
    layout = _FIELD_RUN_FUNCTION[region]
    function_offset = layout["function_address"] - layout["load_address"]

    # The original code masks Circle|L1, then branches to the walk path when
    # neither is held. Autorun masks Circle alone and inverts that branch, so
    # holding Circle selects walking and releasing it selects running.
    original = struct.pack("<II", 0x30420044, 0x10400007)
    patched = struct.pack("<II", 0x30420040, 0x14400007)
    search_end = min(function_offset + 0x200, len(decompressed))
    function_code = bytes(decompressed[function_offset:search_end])

    if patched in function_code:
        return False
    patch_offset = function_code.find(original)
    if patch_offset < 0 or function_code.find(original, patch_offset + 1) >= 0:
        raise RuntimeError(_error_message("error_autorun_patch_sequence"))

    absolute_patch_offset = function_offset + patch_offset
    decompressed[absolute_patch_offset:absolute_patch_offset + len(original)] = patched
    return True


def modify_field_overlay(
    project_directory: str | Path,
    seed: int | None = None,
    autorun_enabled: bool = False,
) -> tuple[int, bool]:
    """Apply selected FIELD edits using one decompression and compression pass."""
    if seed is None and not autorun_enabled:
        return 0, False

    project = Path(project_directory).expanduser().resolve()
    bin_directory = project / "BIN"
    field_overlay = bin_directory / "FIELD.BIN"
    if not field_overlay.is_file():
        raise FileNotFoundError(
            _error_message("error_field_overlay_missing", path=field_overlay)
        )

    region = _detect_disc_region(project, bin_directory)
    decompressed = _read_decompressed_field(field_overlay)
    land_levels_changed = (
        _randomize_land_levels_data(decompressed, region, seed)
        if seed is not None
        else 0
    )
    autorun_changed = (
        _enable_autorun_data(decompressed, region) if autorun_enabled else False
    )

    if land_levels_changed or autorun_changed:
        _write_compressed_field(field_overlay, bytes(decompressed))
    return land_levels_changed, autorun_changed


def randomize_land_levels(project_directory: str | Path, seed: int) -> int:
    """Shuffle the nonzero entries in FIELD's monster-level curve."""
    changed, _ = modify_field_overlay(project_directory, seed=seed)
    return changed


def enable_autorun(project_directory: str | Path) -> bool:
    """Patch FIELD so the controlled character runs unless Circle is held."""
    _, changed = modify_field_overlay(project_directory, autorun_enabled=True)
    return changed


def _find_executable(project_root: Path, name: str) -> Path:
    for candidate in (project_root / name, project_root / "bin" / name):
        if candidate.is_file():
            return candidate

    ignored_directories = {".git", ".venv", "venv", "__pycache__"}
    candidates = sorted(
        (
            path
            for path in project_root.rglob(name)
            if not any(part in ignored_directories for part in path.relative_to(project_root).parts)
        ),
        key=lambda path: (len(path.relative_to(project_root).parts), str(path).lower()),
    )
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        _error_message("error_required_executable_missing", name=name)
    )


def _run_command(command: list[str], working_directory: Path) -> None:
    options = {
        "cwd": working_directory,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "check": False,
    }
    if sys.platform.startswith("win"):
        options["creationflags"] = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(command, **options)
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        if not details:
            details = _error_message(
                "error_process_exit_code", returncode=result.returncode
            )
        raise RuntimeError(_error_message("error_external_command", details=details))


def extract_disc_image(disc_image: str | Path, project_root: str | Path) -> Path:
    """Extract a PS1 image to legend_of_mana and create the project XML there."""
    image = Path(disc_image).expanduser().resolve()
    root = Path(project_root).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(
            _error_message("error_disc_image_missing", path=image)
        )

    destination = root / "legend_of_mana"
    destination.mkdir(parents=True, exist_ok=True)
    executable = _find_executable(
        root, "dumpsxiso.exe" if sys.platform.startswith("win") else "dumpsxiso"
    )
    project_xml = destination / "legend_of_mana.xml"

    _run_command(
        [str(executable), "-x", str(destination), "-s", str(project_xml), str(image)],
        root,
    )
    return destination


def build_disc_image(
    project_directory: str | Path,
    output_directory: str | Path,
    project_root: str | Path,
) -> Path:
    """Build a BIN/CUE from legend_of_mana in the selected directory."""
    source = Path(project_directory).expanduser().resolve()
    output = Path(output_directory).expanduser().resolve()
    root = Path(project_root).expanduser().resolve()
    project_xml = source / "legend_of_mana.xml"
    if not project_xml.is_file():
        raise FileNotFoundError(
            _error_message("error_project_xml_missing", path=project_xml)
        )
    if not output.is_dir():
        raise NotADirectoryError(
            _error_message("error_output_directory_missing", path=output)
        )

    base_name = "legend_of_mana"
    output_image = output / f"{base_name}.bin"
    output_cue = output / f"{base_name}.cue"
    existing_files = [file for file in (output_image, output_cue) if file.exists()]
    if existing_files:
        paths = ", ".join(str(file) for file in existing_files)
        raise FileExistsError(
            _error_message("error_output_files_exist", paths=paths)
        )

    executable = _find_executable(
        root, "mkpsxiso.exe" if sys.platform.startswith("win") else "mkpsxiso"
    )
    _run_command(
        [
            str(executable),
            "-o",
            str(output_image),
            "-c",
            str(output_cue),
            str(project_xml),
        ],
        output,
    )
    return output_image


# Scene transition decoding follows lom-decomp/tools/data/scenes/event_opcodes.py
# and event_scripts.py. Only decoded, reachable 0x85 instructions are edited.
_EVENT_FIXED_FORMATS = {
    0x00: "", 0x01: "h", 0x02: "h", 0x03: "B", 0x04: "h", 0x05: "h",
    0x06: "", 0x07: "", 0x0F: "B", 0x10: "H", 0x11: "BHBBB", 0x12: "BB",
    0x13: "BH", 0x14: "B", 0x15: "B", 0x16: "B", 0x18: "H", 0x19: "BB",
    0x1A: "BB", 0x1E: "B", 0x1F: "", 0x27: "B", 0x29: "", 0x2E: "",
    0x38: "",
}
_EVENT_PAIR_FIELDS = {
    **{opcode: 2 for opcode in range(0x40, 0x60)},
    **{opcode: 4 for opcode in range(0x80, 0x90)},
}
_EVENT_TYPED_OPERANDS = {
    0x0A: (0,), 0x28: (6, 4, 2), 0x2A: (6, 4, 2, 0), 0x2B: (6, 4, 2),
    0x2C: (0,), 0x2D: (6, 4), 0x2F: (6, 4), 0x31: (6, 4, 2, 0),
    0x32: (6, 4, 2, 0), 0x33: (6, 4, 2), 0x34: (0, 2, 4),
    0x35: (0, 2, 4), 0x37: (6, 4),
}


def _event_operand_end(
    data: bytes, position: int, kind: int, *, nibble: bool = False
) -> tuple[int, int | None, int]:
    """Read one lom-decomp basic (2-bit) or nibble (4-bit) event operand."""
    kind &= 0xF
    if nibble:
        if kind == 0:
            return position + 1, data[position] if position < len(data) else None, 1
        if kind in (1, 4):
            end = position + 2
            return end, struct.unpack_from("<H", data, position)[0] if end <= len(data) else None, 2
        if kind == 2:
            end = position + 4
            return end, struct.unpack_from("<i", data, position)[0] if end <= len(data) else None, 4
        if kind == 3:
            return position + 2, None, 2
        if kind == 5:
            end = position + 2
            value = struct.unpack_from("<H", data, position)[0] if end <= len(data) else None
            return end, value + 0x10000 if value is not None else None, -2
        if kind in (6, 7):
            return position, None, 0
        if kind in (8, 9, 10):
            return position, {8: 0, 9: 1, 10: 255}[kind], 0
        raise ValueError(_error_message("error_unknown_nibble_type", kind=kind))

    kind &= 0x3
    if kind == 0:
        return position + 2, None, 2
    if kind == 1:
        return position + 1, data[position] if position < len(data) else None, 1
    if kind == 2:
        end = position + 2
        return end, struct.unpack_from("<H", data, position)[0] if end <= len(data) else None, 2
    if kind == 3:
        end = position + 4
        return end, struct.unpack_from("<i", data, position)[0] if end <= len(data) else None, 4
    raise ValueError(
        _error_message("error_unknown_event_operand_type", kind=kind)
    )


def _decode_event_instruction(
    section: bytes, position: int
) -> tuple[int, list[tuple[int, int, int]], list[int]]:
    """Decode instruction length, scene-id operand offsets and static successors."""
    if position >= len(section):
        raise ValueError(_error_message("error_event_instruction_out_of_range"))
    start = position
    opcode = section[position]
    position += 1
    scene_operands: list[tuple[int, int, int]] = []
    successors: list[int] = []

    def read(fmt: str) -> int:
        nonlocal position
        size = struct.calcsize("<" + fmt)
        if position + size > len(section):
            raise ValueError(_error_message("error_event_instruction_truncated"))
        value = struct.unpack_from("<" + fmt, section, position)[0]
        position += size
        return value

    if opcode in _EVENT_FIXED_FORMATS:
        fmt = _EVENT_FIXED_FORMATS[opcode]
        values = [read(code) for code in fmt]
        if opcode in (0x01, 0x02, 0x04, 0x05) and values[0]:
            # The signed delta is relative to the instruction cursor after its
            # operand, as in lom-decomp's branch_target(base + position, ...).
            successors.append(position + values[0])
        if opcode not in (0x00, 0x01, 0x2E):
            successors.append(position)
    elif opcode in _EVENT_PAIR_FIELDS:
        count = _EVENT_PAIR_FIELDS[opcode]
        descriptors = [read("B") for _ in range(count // 2)]
        kinds = [kind for descriptor in descriptors for kind in (descriptor & 0xF, descriptor >> 4)]
        for field_index, kind in enumerate(kinds):
            operand_offset = position
            position, value, operand_width = _event_operand_end(
                section, position, kind, nibble=True
            )
            if opcode == 0x85 and field_index == 0 and value is not None:
                scene_operands.append((operand_offset, value, operand_width))
        if opcode != 0x85:
            successors.append(position)
    elif opcode in _EVENT_TYPED_OPERANDS:
        descriptor = read("B")
        shifts = _EVENT_TYPED_OPERANDS[opcode]
        for shift in shifts:
            position, _, _ = _event_operand_end(section, position, (descriptor >> shift) & 3)
        successors.append(position)
    elif opcode in (0x08, 0x09, 0x0B, 0x0C, 0x0D, 0x1B, 0x1C, 0x1D):
        descriptor = read("B")
        if opcode == 0x08:
            read("H")
            position, _, _ = _event_operand_end(section, position, descriptor)
            position, _, _ = _event_operand_end(section, position, descriptor >> 2)
            successors.append(position)
        elif opcode == 0x09:
            position, _, _ = _event_operand_end(section, position, descriptor)
            while True:
                key = read("B")
                delta = read("h")
                if delta:
                    successors.append(position - 3 + delta)
                if key == 0xFF:
                    break
        elif opcode == 0x0B:
            position, _, _ = _event_operand_end(section, position, descriptor)
            read("H")
            read("H")
            position, _, _ = _event_operand_end(section, position, descriptor >> 2)
            read("H")
            successors.append(position)
        elif opcode in (0x0C, 0x0D):
            read("B")
            position, _, _ = _event_operand_end(section, position, descriptor)
            read("I")
            if opcode == 0x0C:
                read("H")
            else:
                position, _, _ = _event_operand_end(section, position, descriptor >> 2)
            successors.append(position)
        elif opcode == 0x1B:
            read("H")
            position, _, _ = _event_operand_end(section, position, descriptor)
            successors.append(position)
        elif opcode == 0x1C:
            position, _, _ = _event_operand_end(section, position, descriptor)
            position, _, _ = _event_operand_end(section, position, descriptor >> 2)
            read("H")
            successors.append(position)
        else:
            position, _, _ = _event_operand_end(section, position, descriptor)
            read("H")
            successors.append(position)
    elif opcode == 0x0E:
        read("H")
    else:
        raise ValueError(
            _error_message("error_unknown_event_opcode", opcode=f"0x{opcode:02X}")
        )

    if opcode in (0x02, 0x04, 0x05):
        successors.append(position)
    return position - start, scene_operands, successors


def _scene_paths_from_manifest(project_directory: Path) -> list[Path]:
    """Use mkpsxiso's preserved directory order as the FIELD scene resource order."""
    manifest = project_directory / "legend_of_mana.xml"
    if not manifest.is_file():
        raise FileNotFoundError(
            _error_message("error_disc_manifest_missing", path=manifest)
        )
    root = ET.parse(manifest).getroot()
    tree = root.find(".//directory_tree")
    if tree is None:
        raise ValueError(_error_message("error_manifest_directory_tree_missing"))
    scenes: list[Path] = []

    def collect_group(element: ET.Element, parts: tuple[str, ...]) -> None:
        for child in element:
            if child.tag == "dir":
                collect_group(child, parts + (child.get("name", ""),))
            elif child.tag == "file" and child.get("name", "").lower().endswith(".img"):
                scenes.append(project_directory.joinpath(*parts, child.get("name", "")))

    def find_ana(element: ET.Element) -> bool:
        for child in element:
            if child.tag != "dir":
                continue
            if child.get("name", "").upper() == "ANA":
                for group in child:
                    if group.tag == "dir" and (
                        group.get("name", "").upper().startswith("INFO_")
                        or group.get("name", "").upper() == "MAPINFO"
                    ):
                        collect_group(group, ("ANA", group.get("name", "")))
                return True
            if find_ana(child):
                return True
        return False

    find_ana(tree)
    return scenes

def randomize_artifact_event_rewards(
    project_directory: str | Path, seed: int
) -> int:
    """Permute literal artifact unlocks in reachable scene event scripts.

    Artifact rewards are FIELD's ``make_land_available`` command (opcode
    0x44, subcommand 0x0F), not inventory item IDs. Only direct literal land
    indices in the valid 0..63 range are included; variable-driven and other
    dynamic operands are left unchanged. Reward values are shuffled without
    replacement, preserving the original multiset of unlocked artifacts.
    """
    project = Path(project_directory).expanduser().resolve()
    ana = project / "ANA"
    records: list[tuple[Path, int, int, int]] = []

    for scene_path in _scene_paths_from_manifest(project):
        if not scene_path.is_file() or scene_path.parent.parent.resolve() != ana:
            continue
        data = scene_path.read_bytes()
        if len(data) < 40:
            continue
        offsets = struct.unpack_from("<10I", data)
        if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
            offset > len(data) or offset % 4 for offset in offsets
        ):
            continue

        section_start, section_end = offsets[1], offsets[2]
        section = data[section_start:section_end]
        if len(section) < 2:
            continue
        table_size = struct.unpack_from("<H", section)[0]
        if table_size < 2 or table_size % 2 or table_size > len(section):
            continue
        script_offsets = struct.unpack_from(f"<{table_size // 2}H", section)
        pending = [offset for offset in script_offsets if table_size <= offset < len(section)]
        visited: set[int] = set()

        while pending:
            position = pending.pop()
            if position in visited or position < table_size or position >= len(section):
                continue
            visited.add(position)
            try:
                instruction_size, _, successors = _decode_event_instruction(
                    section, position
                )
            except (ValueError, struct.error):
                continue
            if instruction_size <= 0:
                continue

            if section[position] == 0x44 and position + 1 < len(section):
                descriptor = section[position + 1]
                operand_position = position + 2
                try:
                    operand_position, subcommand, _ = _event_operand_end(
                        section, operand_position, descriptor & 0x0F, nibble=True
                    )
                    argument_offset = operand_position
                    _, artifact_id, argument_width = _event_operand_end(
                        section, operand_position, descriptor >> 4, nibble=True
                    )
                except (ValueError, struct.error, IndexError):
                    subcommand = None
                    artifact_id = None
                    argument_width = 0
                if (
                    subcommand == 0x0F
                    and artifact_id is not None
                    and 0 <= artifact_id < 64
                    and argument_width in (1, 2)
                ):
                    records.append(
                        (scene_path, section_start + argument_offset, argument_width, artifact_id)
                    )

            pending.extend(
                target for target in successors if 0 <= target < len(section)
            )

    if len(records) < 2:
        return 0

    original_values = [record[3] for record in records]
    shuffled_values = original_values.copy()
    rng = random.Random(seed)
    for _ in range(512):
        rng.shuffle(shuffled_values)
        if shuffled_values != original_values:
            break
    else:
        return 0

    changed_by_path: dict[Path, bytearray] = {}
    changed = 0
    for (scene_path, offset, width, old_value), new_value in zip(records, shuffled_values):
        if old_value == new_value:
            continue
        scene_data = changed_by_path.setdefault(
            scene_path, bytearray(scene_path.read_bytes())
        )
        struct.pack_into("<B" if width == 1 else "<H", scene_data, offset, new_value)
        changed += 1

    for scene_path, scene_data in changed_by_path.items():
        scene_path.write_bytes(scene_data)
    return changed


def _connected_components(
    nodes: list[int], adjacency: dict[int, set[int]]
) -> dict[int, int]:
    """Return weak component IDs for a directed scene graph."""
    reverse_adjacency = {node: set() for node in nodes}
    for origin, destinations in adjacency.items():
        for destination in destinations:
            if destination in reverse_adjacency:
                reverse_adjacency[destination].add(origin)

    components: dict[int, int] = {}
    component_id = 0
    for root in nodes:
        if root in components:
            continue
        components[root] = component_id
        pending_positions = [root]
        while pending_positions:
            current_node = pending_positions.pop()
            neighbors = adjacency.get(current_node, set()) | reverse_adjacency.get(current_node, set())
            for neighbor in neighbors:
                if neighbor not in components:
                    components[neighbor] = component_id
                    pending_positions.append(neighbor)
        component_id += 1
    return components


def randomize_local_scene_transitions(
    project_directory: str | Path, seed: int
) -> int:
    """Randomize room links within their source land without splitting room groups.

    Scene IDs come from the ISO manifest's directory order. Destinations must
    remain in the source scene's three-letter land prefix. World-map and
    cross-land destinations are preserved. Destinations are permuted only
    within their original weakly connected room group, and each accepted
    permutation is checked to keep that group connected. Every room retains
    its original number of outgoing transitions and every land exit remains.
    """
    project = Path(project_directory).expanduser().resolve()
    ana = project / "ANA"
    manifest_scenes = _scene_paths_from_manifest(project)
    scene_by_id = {
        index: path for index, path in enumerate(manifest_scenes)
        if path.is_file() and path.parent.parent.resolve() == ana.resolve()
    }
    if not scene_by_id:
        raise RuntimeError(_error_message("error_manifest_field_scenes_missing"))

    def is_scene_group(path: Path) -> bool:
        group = path.parent.name.upper()
        return group.startswith("INFO_") or group == "MAPINFO"

    records: list[tuple[Path, int, int, int, str, int]] = []
    nodes_by_location: dict[str, list[int]] = {}
    for scene_id, path in scene_by_id.items():
        if is_scene_group(path):
            location = path.stem.split("_", 1)[0].upper()
            if location:
                nodes_by_location.setdefault(location, []).append(scene_id)

    for source_id, scene_path in scene_by_id.items():
        if not scene_path.is_file() or not is_scene_group(scene_path):
            continue
        data = scene_path.read_bytes()
        if len(data) < 40:
            continue
        offsets = struct.unpack_from("<10I", data)
        if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
            offset > len(data) or offset % 4 for offset in offsets
        ):
            continue
        section_start, section_end = offsets[1], offsets[2]
        section = data[section_start:section_end]
        if len(section) < 2:
            continue
        table_size = struct.unpack_from("<H", section)[0]
        if table_size < 2 or table_size % 2 or table_size > len(section):
            continue
        script_offsets = struct.unpack_from(f"<{table_size // 2}H", section)
        pending = [offset for offset in script_offsets if table_size <= offset < len(section)]
        visited: set[int] = set()
        while pending:
            pos = pending.pop()
            if pos in visited or pos < table_size or pos >= len(section):
                continue
            visited.add(pos)
            try:
                instruction_size, operands, successors = _decode_event_instruction(section, pos)
            except (ValueError, struct.error):
                continue
            if instruction_size <= 0:
                continue
            for operand_offset, destination, operand_width in operands:
                destination_id = destination & 0x7FFF
                destination_path = scene_by_id.get(destination_id)
                if destination_path is None or destination >= 0xFFFE:
                    continue
                # The origin prefix defines the land: using the old target's
                # prefix here could redirect a doorway across land boundaries.
                location = scene_path.stem.split("_", 1)[0].upper()
                if not location:
                    continue
                absolute_operand = section_start + operand_offset
                records.append((scene_path, absolute_operand, destination, source_id, location, operand_width))
            pending.extend(target for target in successors if 0 <= target < len(section))

    if not records:
        raise RuntimeError(_error_message("error_no_local_scene_transitions"))

    adjacency_by_location: dict[str, dict[int, set[int]]] = {}
    for index, (_, _, old_destination, source_id, location, operand_width) in enumerate(records):
        destination_id = old_destination & 0x7FFF
        if operand_width not in (1, 2) or destination_id not in nodes_by_location.get(location, []):
            continue
        graph = adjacency_by_location.setdefault(location, {
            node: set() for node in nodes_by_location[location]
        })
        graph[source_id].add(destination_id)

    component_by_location: dict[str, dict[int, int]] = {}
    for location, nodes in nodes_by_location.items():
        graph = adjacency_by_location.get(location, {node: set() for node in nodes})
        component_by_location[location] = _connected_components(nodes, graph)

    rng = random.Random(seed)
    changed_by_path: dict[Path, bytearray] = {}
    changed = 0
    edge_groups: dict[tuple[str, int, int], list[int]] = {}
    edge_indexes_by_component: dict[tuple[str, int], list[int]] = {}
    for index, (_, _, old_destination, source_id, location, operand_width) in enumerate(records):
        destination_id = old_destination & 0x7FFF
        components = component_by_location.get(location, {})
        if operand_width not in (1, 2) or components.get(source_id) != components.get(destination_id):
            continue
        component_id = components[source_id]
        edge_indexes_by_component.setdefault((location, component_id), []).append(index)
        edge_groups.setdefault((location, component_id, operand_width), []).append(index)

    targets = [record[2] & 0x7FFF for record in records]
    for (location, component_id, operand_width), indexes in edge_groups.items():
        if len(indexes) < 2:
            continue
        nodes = [
            node for node, component in component_by_location[location].items()
            if component == component_id
        ]
        original_destinations = [targets[index] for index in indexes]
        accepted: list[int] | None = None
        # Preserve destination counts while trying different endpoint
        # assignments. A candidate is accepted only if it keeps every room in
        # this original group connected to the others.
        for _ in range(512):
            candidate = original_destinations.copy()
            rng.shuffle(candidate)
            if candidate == original_destinations:
                continue
            candidate_by_index = dict(zip(indexes, candidate))
            weak_graph = {node: set() for node in nodes}
            for edge_index in edge_indexes_by_component[(location, component_id)]:
                _, _, old_destination, source_id, _, _ = records[edge_index]
                edge_dest = candidate_by_index.get(edge_index, targets[edge_index])
                weak_graph[source_id].add(edge_dest)
                weak_graph[edge_dest].add(source_id)
            reached = {nodes[0]} if nodes else set()
            pending_nodes = list(reached)
            while pending_nodes:
                current = pending_nodes.pop()
                for neighbor in weak_graph[current] - reached:
                    reached.add(neighbor)
                    pending_nodes.append(neighbor)
            if reached == set(nodes):
                accepted = candidate
                break
        if accepted is None:
            continue
        for index, new_destination in zip(indexes, accepted):
            if new_destination == targets[index]:
                continue
            targets[index] = new_destination
            changed += 1

    for index, (scene_path, operand_offset, old_destination, _, _, operand_width) in enumerate(records):
        new_destination = targets[index]
        if new_destination == (old_destination & 0x7FFF):
            continue
        mutable = changed_by_path.get(scene_path)
        if mutable is None:
            mutable = bytearray(scene_path.read_bytes())
            changed_by_path[scene_path] = mutable
        if operand_width == 1:
            struct.pack_into("<B", mutable, operand_offset, new_destination & 0xFF)
        else:
            old_word = struct.unpack_from("<H", mutable, operand_offset)[0]
            new_word = (old_word & 0x8000) | (new_destination & 0x7FFF)
            struct.pack_into("<H", mutable, operand_offset, new_word)

    for path, data in changed_by_path.items():
        path.write_bytes(data)
    return changed


def randomize_global_scene_transitions_with_return(
    project_directory: str | Path, seed: int
) -> int:
    """Swap reciprocal doorway links between lands while keeping each return.

    A reciprocal pair is accepted only when a scene has exactly one literal
    transition to the other scene and that scene has exactly one literal
    transition back. Two pairs are rewired together: each entry receives the
    destination parameters of the counterpart doorway, including its object,
    audio and spawn values. This makes the doorway reached on arrival point back
    through the paired transition. Ambiguous or dynamic transitions are kept.
    """
    project = Path(project_directory).expanduser().resolve()
    ana = project / "ANA"
    manifest_scenes = _scene_paths_from_manifest(project)
    scene_by_id = {
        index: path for index, path in enumerate(manifest_scenes)
        if path.is_file() and path.parent.parent.resolve() == ana.resolve()
        and (path.parent.name.upper().startswith("INFO_")
             or path.parent.name.upper() == "MAPINFO")
    }
    if not scene_by_id:
        raise RuntimeError(_error_message("error_manifest_field_scenes_missing"))
    non_land_prefixes = {"BTL", "DMY", "END", "INIT", "MID"}

    # Each record is one 0x85 instruction and its four operands: scene, object,
    # audio and spawn. A complete, compatible literal payload moves together.
    records: list[
        tuple[int, Path, tuple[tuple[int, int | None, int, bytes], ...]]
    ] = []
    transitions_by_pair: dict[tuple[int, int], list[int]] = {}
    connectivity_edges: list[tuple[int, int]] = []
    prefix_by_scene = {
        scene_id: path.stem.split("_", 1)[0].upper()
        for scene_id, path in scene_by_id.items()
    }
    for source_id, scene_path in scene_by_id.items():
        data = scene_path.read_bytes()
        if len(data) < 40:
            continue
        offsets = struct.unpack_from("<10I", data)
        if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
            offset > len(data) or offset % 4 for offset in offsets
        ):
            continue
        section_start, section_end = offsets[1], offsets[2]
        section = data[section_start:section_end]
        if len(section) < 2:
            continue
        table_size = struct.unpack_from("<H", section)[0]
        if table_size < 2 or table_size % 2 or table_size > len(section):
            continue
        script_offsets = struct.unpack_from(f"<{table_size // 2}H", section)
        pending = [offset for offset in script_offsets if table_size <= offset < len(section)]
        visited: set[int] = set()
        while pending:
            pos = pending.pop()
            if pos in visited or pos < table_size or pos >= len(section):
                continue
            visited.add(pos)
            try:
                instruction_size, scene_operands, successors = _decode_event_instruction(
                    section, pos
                )
            except (ValueError, struct.error):
                continue
            if instruction_size <= 0:
                continue
            for _, destination, _ in scene_operands:
                if destination is None or destination >= 0xFFFE:
                    continue
                target_id = destination & 0x7FFF
                if (target_id in scene_by_id
                        and prefix_by_scene[source_id] not in non_land_prefixes
                        and prefix_by_scene[target_id] not in non_land_prefixes):
                    connectivity_edges.append((source_id, target_id))
            if section[pos] == 0x85:
                descriptor_start = pos + 1
                if descriptor_start + 2 > len(section):
                    continue
                descriptors = section[descriptor_start:descriptor_start + 2]
                kinds = [kind for descriptor in descriptors
                         for kind in (descriptor & 0xF, descriptor >> 4)]
                operand_pos = descriptor_start + 2
                fields: list[tuple[int, int | None, int, bytes]] = []
                for kind in kinds:
                    field_offset = operand_pos
                    operand_pos, value, width = _event_operand_end(
                        section, operand_pos, kind, nibble=True
                    )
                    raw_value = section[field_offset:operand_pos]
                    fields.append((section_start + field_offset, value, width, raw_value))
                if (len(fields) == 4 and all(field[1] is not None for field in fields)
                        and all(field[2] in (0, 1, 2, 4) for field in fields)
                        and fields[0][2] in (1, 2)
                        and fields[3][2] in (0, 1, 2)):
                    destination = fields[0][1]
                    target_id = destination & 0x7FFF
                    if (destination < 0xFFFE and target_id in scene_by_id
                            and prefix_by_scene[source_id] not in non_land_prefixes
                            and prefix_by_scene[target_id] not in non_land_prefixes):
                        record_index = len(records)
                        records.append((source_id, scene_path, tuple(fields)))
                        transitions_by_pair.setdefault((source_id, target_id), []).append(
                            record_index
                        )
            pending.extend(target for target in successors if 0 <= target < len(section))

    # Only unique reverse links can be identified as the exact paired doorway
    # from these scene scripts. Multiple links between the same rooms are
    # ambiguous, so they remain untouched.
    reciprocal_pairs: list[tuple[int, int, int, int]] = []
    for (source_id, target_id), forward_indexes in transitions_by_pair.items():
        if source_id >= target_id or len(forward_indexes) != 1:
            continue
        reverse_indexes = transitions_by_pair.get((target_id, source_id), [])
        if len(reverse_indexes) != 1:
            continue
        reciprocal_pairs.append(
            (source_id, target_id, forward_indexes[0], reverse_indexes[0])
        )
    if len(reciprocal_pairs) < 2:
        raise RuntimeError(_error_message("error_not_enough_reciprocal_door_pairs"))

    def fields_compatible(first: int, second: int) -> bool:
        first_fields = records[first][2]
        second_fields = records[second][2]
        return all(
            first_field[2] == second_field[2]
            and (first_field[2] != 0 or first_field[1] == second_field[1])
            for first_field, second_field in zip(first_fields, second_fields)
        )

    scene_nodes = [
        scene_id for scene_id, prefix in prefix_by_scene.items()
        if prefix not in non_land_prefixes
    ]
    edge_counts: dict[tuple[int, int], int] = {}
    for source_id, target_id in connectivity_edges:
        edge = (min(source_id, target_id), max(source_id, target_id))
        edge_counts[edge] = edge_counts.get(edge, 0) + 1

    def component_map(counts: dict[tuple[int, int], int]) -> dict[int, int]:
        adjacency = {scene_id: set() for scene_id in scene_nodes}
        for (first, second), count in counts.items():
            if count and first in adjacency and second in adjacency:
                adjacency[first].add(second)
                adjacency[second].add(first)
        return _connected_components(scene_nodes, adjacency)

    def swap_keeps_groups_connected(
        a: int, b: int, x: int, y: int, left: int, right: int
    ) -> bool:
        before = component_map(edge_counts)
        affected_components = {before[a], before[x]}
        affected_nodes = {
            node for node, component in before.items()
            if component in affected_components
        }
        candidate = edge_counts.copy()
        for edge in ((min(a, b), max(a, b)), (min(x, y), max(x, y))):
            candidate[edge] = candidate.get(edge, 0) - 2
        for edge in ((min(a, left), max(a, left)), (min(b, right), max(b, right))):
            candidate[edge] = candidate.get(edge, 0) + 2
        adjacency = {scene_id: set() for scene_id in affected_nodes}
        for (first, second), count in candidate.items():
            if count > 0 and first in adjacency and second in adjacency:
                adjacency[first].add(second)
                adjacency[second].add(first)
        root = next(iter(affected_nodes), None)
        if root is None:
            return False
        reached = {root}
        pending = [root]
        while pending:
            current = pending.pop()
            for neighbor in adjacency[current] - reached:
                reached.add(neighbor)
                pending.append(neighbor)
        return reached == affected_nodes

    rng = random.Random(seed)
    rng.shuffle(reciprocal_pairs)
    consumed: set[int] = set()
    new_payload_by_record: dict[int, int] = {}
    for first_index, first_pair in enumerate(reciprocal_pairs):
        if first_index in consumed:
            continue
        a, b, ab, ba = first_pair
        selected: tuple[int, tuple[int, int, int, int]] | None = None
        candidate_indexes = list(range(first_index + 1, len(reciprocal_pairs)))
        rng.shuffle(candidate_indexes)
        for second_index in candidate_indexes:
            if second_index in consumed:
                continue
            x, y, xy, yx = reciprocal_pairs[second_index]
            if {a, b} & {x, y}:
                continue
            orientations = [(x, y, xy, yx, False), (y, x, yx, xy, True)]
            rng.shuffle(orientations)
            for left, right, left_to_right, right_to_left, _ in orientations:
                # Both resulting connections must cross land-prefix groups.
                if (prefix_by_scene[a] == prefix_by_scene[left]
                        or prefix_by_scene[b] == prefix_by_scene[right]):
                    continue
                # Exchange complete entry payloads so each arrival uses the
                # spawn that leads back through the paired doorway.
                assignments = (
                    (ab, right_to_left), (right_to_left, ab),
                    (ba, left_to_right), (left_to_right, ba),
                )
                if not all(fields_compatible(source, payload)
                           for source, payload in assignments):
                    continue
                if not swap_keeps_groups_connected(a, b, x, y, left, right):
                    continue
                selected = (second_index, assignments)
                break
            if selected is not None:
                break
        if selected is None:
            continue
        second_index, assignments = selected
        x, y, _, _ = reciprocal_pairs[second_index]
        left = int(records[assignments[0][1]][2][0][1]) & 0x7FFF
        right = int(records[assignments[2][1]][2][0][1]) & 0x7FFF
        for edge in ((min(a, b), max(a, b)), (min(x, y), max(x, y))):
            edge_counts[edge] = edge_counts.get(edge, 0) - 2
        for edge in ((min(a, left), max(a, left)), (min(b, right), max(b, right))):
            edge_counts[edge] = edge_counts.get(edge, 0) + 2
        consumed.update((first_index, second_index))
        new_payload_by_record.update(assignments)

    if not new_payload_by_record:
        raise RuntimeError(_error_message("error_no_compatible_return_door_pairs"))

    changed_by_path: dict[Path, bytearray] = {}
    changed_destinations = 0
    for record_index, payload_index in new_payload_by_record.items():
        _, path, current_fields = records[record_index]
        _, _, payload_fields = records[payload_index]
        if current_fields[0][1] != payload_fields[0][1]:
            changed_destinations += 1
        mutable = changed_by_path.get(path)
        if mutable is None:
            mutable = bytearray(path.read_bytes())
            changed_by_path[path] = mutable
        for (offset, _, width, _), (_, _, _, raw_value) in zip(
            current_fields, payload_fields
        ):
            if width:
                mutable[offset:offset + width] = raw_value

    for path, data in changed_by_path.items():
        path.write_bytes(data)
    return changed_destinations


def randomize_extreme_global_scene_transitions(
    project_directory: str | Path, seed: int
) -> int:
    """Permute complete compatible scene-transition payloads globally.

    Scene entries and exits are treated as independent transitions: no reverse
    link is created. Literal destinations may point to any indexed scene, the
    world map (0xFFFF), or the title screen (0xFFFE). Scenes with BTL, DMY or
    MID filename prefixes are excluded as both transition sources and ordinary
    scene destinations. Dynamic operands and payloads whose operand formats do
    not match another transition are left untouched.
    """
    project = Path(project_directory).expanduser().resolve()
    ana = project / "ANA"
    manifest_scenes = _scene_paths_from_manifest(project)
    scene_by_id = {
        index: path for index, path in enumerate(manifest_scenes)
        if path.is_file() and path.parent.parent.resolve() == ana.resolve()
        and (path.parent.name.upper().startswith("INFO_")
             or path.parent.name.upper() == "MAPINFO")
    }
    if not scene_by_id:
        raise RuntimeError(_error_message("error_manifest_field_scenes_missing"))

    excluded_prefixes = {"BTL", "DMY", "MID"}
    prefix_by_scene = {
        scene_id: path.stem.split("_", 1)[0].upper()
        for scene_id, path in scene_by_id.items()
    }
    # (source scene, file, (offset, value, width, raw bytes)*, operand kinds)
    records: list[
        tuple[int, Path, tuple[tuple[int, int | None, int, bytes], ...], tuple[int, ...]]
    ] = []
    groups: dict[tuple[int, ...], list[int]] = {}

    for source_id, scene_path in scene_by_id.items():
        if prefix_by_scene[source_id] in excluded_prefixes:
            continue
        data = scene_path.read_bytes()
        if len(data) < 40:
            continue
        offsets = struct.unpack_from("<10I", data)
        if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
            offset > len(data) or offset % 4 for offset in offsets
        ):
            continue
        section_start, section_end = offsets[1], offsets[2]
        section = data[section_start:section_end]
        if len(section) < 2:
            continue
        table_size = struct.unpack_from("<H", section)[0]
        if table_size < 2 or table_size % 2 or table_size > len(section):
            continue
        script_offsets = struct.unpack_from(f"<{table_size // 2}H", section)
        pending = [offset for offset in script_offsets if table_size <= offset < len(section)]
        visited: set[int] = set()

        while pending:
            pos = pending.pop()
            if pos in visited or pos < table_size or pos >= len(section):
                continue
            visited.add(pos)
            try:
                instruction_size, _, successors = _decode_event_instruction(section, pos)
            except (ValueError, struct.error):
                continue
            if instruction_size <= 0:
                continue

            if section[pos] == 0x85:
                descriptor_start = pos + 1
                if descriptor_start + 2 > len(section):
                    continue
                descriptors = section[descriptor_start:descriptor_start + 2]
                kinds = tuple(
                    kind for descriptor in descriptors
                    for kind in (descriptor & 0xF, descriptor >> 4)
                )
                operand_pos = descriptor_start + 2
                fields: list[tuple[int, int | None, int, bytes]] = []
                for kind in kinds:
                    field_offset = operand_pos
                    try:
                        operand_pos, value, width = _event_operand_end(
                            section, operand_pos, kind, nibble=True
                        )
                    except (ValueError, struct.error):
                        fields = []
                        break
                    if operand_pos > len(section):
                        fields = []
                        break
                    fields.append((
                        section_start + field_offset,
                        value,
                        width,
                        section[field_offset:operand_pos],
                    ))

                if len(fields) == 4:
                    destination = fields[0][1]
                    target_eligible = False
                    if destination in (0xFFFE, 0xFFFF):
                        target_eligible = True
                    elif destination is not None and 0 <= destination < 0xFFFE:
                        target_id = destination & 0x7FFF
                        target_eligible = (
                            target_id in scene_by_id
                            and prefix_by_scene[target_id] not in excluded_prefixes
                        )
                    compatible_literals = (
                        all(field[1] is not None for field in fields)
                        and all(field[2] in (0, 1, 2, 4) for field in fields)
                        and fields[0][2] in (1, 2)
                    )
                    if target_eligible and compatible_literals:
                        record_index = len(records)
                        records.append((source_id, scene_path, tuple(fields), kinds))
                        groups.setdefault(kinds, []).append(record_index)

            pending.extend(target for target in successors if 0 <= target < len(section))

    if not records:
        raise RuntimeError(_error_message("error_no_global_scene_transitions"))

    rng = random.Random(seed)
    payload_for_record: dict[int, int] = {}
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        shuffled_payloads = indexes.copy()
        rng.shuffle(shuffled_payloads)
        # Avoid leaving a whole group untouched when a derangement is possible.
        for _ in range(10):
            if any(
                records[index][2][0][3] != records[payload][2][0][3]
                for index, payload in zip(indexes, shuffled_payloads)
            ):
                break
            rng.shuffle(shuffled_payloads)
        payload_for_record.update(zip(indexes, shuffled_payloads))

    changed_by_path: dict[Path, bytearray] = {}
    changed = 0
    for record_index, payload_index in payload_for_record.items():
        _, path, current_fields, _ = records[record_index]
        _, _, payload_fields, _ = records[payload_index]
        if all(
            current_field[3] == payload_field[3]
            for current_field, payload_field in zip(current_fields, payload_fields)
        ):
            continue
        changed += 1
        mutable = changed_by_path.get(path)
        if mutable is None:
            mutable = bytearray(path.read_bytes())
            changed_by_path[path] = mutable
        for (offset, _, width, _), (_, _, _, raw_value) in zip(
            current_fields, payload_fields
        ):
            if width:
                mutable[offset:offset + width] = raw_value

    if not changed:
        raise RuntimeError(_error_message("error_seed_no_scene_transition_changes"))
    for path, data in changed_by_path.items():
        path.write_bytes(data)
    return changed


# Format and signature taken from lom-decomp/tools/data/scenes/layout.py.
# FieldLayoutRecord is 48 bytes; scripts[4] (item_id) starts at byte 24.
_FIELD_LAYOUT_RECORD = struct.Struct("<IHBBIHH16H")
_CHEST_INITIALIZER = bytes.fromhex(
    "40 84 20 c0 "
    "0c 01 02 ff 10 00 08 40 40 e0 "
    "0c 01 02 ff 10 00 09 40 50 e0"
)


def _find_scene_chests(data: bytes) -> list[tuple[int, int]]:
    """Return (item_id offset in the IMG, item_id) for each confirmed chest."""
    if len(data) < 40:
        return []
    offsets = struct.unpack_from("<10I", data)
    if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
        offset > len(data) or offset % 4 for offset in offsets
    ):
        return []

    layout_offset, event_offset, strings_offset = offsets[:3]
    if event_offset - layout_offset < 4:
        return []
    record_count = struct.unpack_from("<I", data, layout_offset)[0]
    if event_offset - layout_offset != 4 + record_count * _FIELD_LAYOUT_RECORD.size:
        return []

    event_scripts = data[event_offset:strings_offset]
    chests = []
    for index in range(record_count):
        record_offset = layout_offset + 4 + index * _FIELD_LAYOUT_RECORD.size
        record = _FIELD_LAYOUT_RECORD.unpack_from(data, record_offset)
        control, source, scripts = record[0], record[5], record[7:]
        kind = (control >> 4) & 0xF
        initializer = scripts[15]
        if kind not in (0, 7) or (source & 7) != 5 or initializer == 0xFFFF:
            continue
        if not initializer & 0x8000:
            continue
        table_offset = (initializer & 0x7FFF) * 2
        if table_offset + 2 > len(event_scripts):
            continue
        script_offset = struct.unpack_from("<H", event_scripts, table_offset)[0]
        if script_offset < table_offset + 2 or not event_scripts[script_offset:].startswith(
            _CHEST_INITIALIZER
        ):
            continue
        item_id = scripts[4]
        if item_id >= 0xFF:
            raise ValueError(
                _error_message("error_chest_reserved_item_id", index=index)
            )
        chests.append((record_offset + 24, item_id))
    return chests


def randomize_chests(project_directory: str | Path, seed: int) -> int:
    """Shuffle chest item_ids and write them to their original IMG files.

    Detection and offsets follow the format documented by lom-decomp. The item
    list is preserved as a multiset, and the seed makes the permutation
    reproducible.
    """
    ana = Path(project_directory).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(_error_message("error_ana_folder_missing", path=ana))

    scenes = sorted(
        path
        for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG")
        for path in ana.glob(pattern)
        if path.is_file()
    )
    changed_files: dict[Path, tuple[bytearray, list[tuple[int, int]]]] = {}
    original_ids: list[int] = []
    for scene in scenes:
        data = scene.read_bytes()
        chests = _find_scene_chests(data)
        if chests:
            mutable = bytearray(data)
            changed_files[scene] = (mutable, chests)
            original_ids.extend(item_id for _, item_id in chests)

    if not original_ids:
        raise RuntimeError(_error_message("error_no_compatible_chests"))

    randomized_ids = original_ids.copy()
    random.Random(seed).shuffle(randomized_ids)
    cursor = 0
    for mutable, chests in changed_files.values():
        for offset, _ in chests:
            struct.pack_into("<H", mutable, offset, randomized_ids[cursor])
            cursor += 1

    for scene, (mutable, _) in changed_files.items():
        scene.write_bytes(mutable)
    return len(original_ids)


_BATTLE_RESOURCE_ID = 1
_MONSTER_HEADER_SIZE = 0x54


def _battle_template_ids(data: bytes, offsets: tuple[int, ...]) -> set[int] | None:
    """Read battle template IDs when the scene has a single battle resource.

    Follows read_resource_directory() and read_battle_resource() from
    lom-decomp/tools/data/scenes/scene_resources.py. None indicates an
    ambiguous link or a structure that cannot be safely validated.
    """
    records_start, actors_start = offsets[4], offsets[5]
    section = data[records_start:actors_start]
    if not section or len(section) < 4:
        return None
    table_size = struct.unpack_from("<I", section)[0]
    if table_size < 4 or table_size % 4 or table_size > len(section):
        return None
    directory = struct.unpack_from(f"<{table_size // 4}I", section)
    if any(offset < table_size or offset > len(section) or offset % 4 for offset in directory):
        return None

    starts = sorted(set(directory))
    resources = [
        (start, section[start:end])
        for start, end in zip(starts, starts[1:] + [len(section)])
    ]
    battles = [resource for _, resource in resources
               if len(resource) >= 2 and struct.unpack_from("<H", resource)[0] == _BATTLE_RESOURCE_ID]
    if len(battles) != 1:
        return None

    battle = battles[0]
    if len(battle) < 12:
        return None
    _, templates, rewards = struct.unpack_from("<3I", battle)
    if not (12 <= templates <= rewards <= len(battle) - 4
            and templates % 4 == 0 and rewards % 4 == 0):
        return None
    template_count = struct.unpack_from("<I", battle, templates)[0]
    table_bytes = 4 + template_count * 4
    if table_bytes > rewards - templates:
        return None
    relative_offsets = struct.unpack_from(
        f"<{template_count}I", battle, templates + 4
    ) if template_count else ()
    if any(offset < table_bytes or offset >= rewards - templates or offset % 4
           for offset in relative_offsets):
        return None

    distinct_offsets = sorted(set(relative_offsets))
    ends = dict(zip(distinct_offsets, distinct_offsets[1:] + [rewards - templates]))
    template_ids = set()
    for relative_offset in relative_offsets:
        start = templates + relative_offset
        end = templates + ends[relative_offset]
        monster = battle[start:end]
        if len(monster) < _MONSTER_HEADER_SIZE:
            return None
        action_count = struct.unpack_from("<i", monster, 0x50)[0]
        if action_count < 0 or _MONSTER_HEADER_SIZE + action_count * 8 > len(monster):
            return None
        template_ids.add(monster[0x18])
    return template_ids


def _find_scene_item_drops(data: bytes) -> list[tuple[int, int]]:
    """Return (value offset, current item kind) for direct item drops."""
    if len(data) < 40:
        return []
    section_offsets = struct.unpack_from("<10I", data)
    if (section_offsets[0] != 40
            or tuple(sorted(section_offsets)) != section_offsets
            or section_offsets[-1] > len(data)):
        return []

    records_start, records_end = section_offsets[4:6]
    section = data[records_start:records_end]
    if len(section) < 4:
        return []
    directory_size = struct.unpack_from("<I", section)[0]
    if (directory_size < 4 or directory_size % 4
            or directory_size > len(section)):
        return []
    resource_offsets = struct.unpack_from(f"<{directory_size // 4}I", section)
    if any(offset < directory_size or offset > len(section) or offset % 4
           for offset in resource_offsets):
        return []

    starts = sorted(set(resource_offsets))
    resources = [
        (start, section[start:end])
        for start, end in zip(starts, starts[1:] + [len(section)])
    ]
    battles = [
        (start, resource) for start, resource in resources
        if len(resource) >= 2
        and struct.unpack_from("<H", resource)[0] == _BATTLE_RESOURCE_ID
    ]
    if len(battles) != 1:
        return []

    battle_section_offset, battle = battles[0]
    if len(battle) < 12:
        return []
    _, templates_offset, rewards_offset = struct.unpack_from("<3I", battle)
    if (not 12 <= templates_offset <= rewards_offset <= len(battle) - 4
            or templates_offset % 4 or rewards_offset % 4):
        return []
    template_count = struct.unpack_from("<I", battle, templates_offset)[0]
    table_size = 4 + template_count * 4
    if table_size > rewards_offset - templates_offset:
        return []
    relative_offsets = struct.unpack_from(
        f"<{template_count}I", battle, templates_offset + 4
    ) if template_count else ()
    if any(offset < table_size or offset >= rewards_offset - templates_offset
           or offset % 4 for offset in relative_offsets):
        return []

    unique_offsets = sorted(set(relative_offsets))
    ends = dict(zip(
        unique_offsets,
        unique_offsets[1:] + [rewards_offset - templates_offset],
    ))
    battle_absolute = records_start + battle_section_offset
    result = []
    for relative in unique_offsets:
        template = battle[templates_offset + relative:
                          templates_offset + ends[relative]]
        if len(template) < _MONSTER_HEADER_SIZE:
            continue
        action_count = struct.unpack_from("<i", template, 0x50)[0]
        if (action_count < 0
                or _MONSTER_HEADER_SIZE + action_count * 8 > len(template)):
            continue
        template_absolute = battle_absolute + templates_offset + relative
        for slot in range(8):
            handler_offset = template_absolute + 0x40 + slot * 2
            if data[handler_offset] == 2:
                result.append((handler_offset + 1, data[handler_offset + 1]))
    return result


def _find_scene_equipment_drop_materials(data: bytes) -> list[int]:
    """Find the weapon/armor material field in enemy rewards."""
    if len(data) < 40:
        return []
    section_offsets = struct.unpack_from("<10I", data)
    if (section_offsets[0] != 40
            or tuple(sorted(section_offsets)) != section_offsets
            or section_offsets[-1] > len(data)):
        return []

    records_start, records_end = section_offsets[4:6]
    section = data[records_start:records_end]
    if len(section) < 4:
        return []
    directory_size = struct.unpack_from("<I", section)[0]
    if (directory_size < 4 or directory_size % 4
            or directory_size > len(section)):
        return []
    resource_offsets = struct.unpack_from(f"<{directory_size // 4}I", section)
    if any(offset < directory_size or offset > len(section) or offset % 4
           for offset in resource_offsets):
        return []

    starts = sorted(set(resource_offsets))
    resources = [
        (start, section[start:end])
        for start, end in zip(starts, starts[1:] + [len(section)])
    ]
    battles = [
        (start, resource) for start, resource in resources
        if len(resource) >= 2
        and struct.unpack_from("<H", resource)[0] == _BATTLE_RESOURCE_ID
    ]
        # Leave the scene unchanged if its resource association is ambiguous.
    if len(battles) != 1:
        return []

    battle_section_offset, battle = battles[0]
    if len(battle) < 12:
        return []
    _, templates_offset, rewards_offset = struct.unpack_from("<3I", battle)
    if (not 12 <= templates_offset <= rewards_offset <= len(battle) - 4
            or templates_offset % 4 or rewards_offset % 4):
        return []

    template_count = struct.unpack_from("<I", battle, templates_offset)[0]
    table_size = 4 + template_count * 4
    if table_size > rewards_offset - templates_offset:
        return []
    relative_offsets = struct.unpack_from(
        f"<{template_count}I", battle, templates_offset + 4
    ) if template_count else ()
    if any(offset < table_size or offset >= rewards_offset - templates_offset
           or offset % 4 for offset in relative_offsets):
        return []

    unique_offsets = sorted(set(relative_offsets))
    ends = dict(zip(
        unique_offsets,
        unique_offsets[1:] + [rewards_offset - templates_offset],
    ))
    reward_keys: set[int] = set()
    for relative in unique_offsets:
        template = battle[templates_offset + relative:
                          templates_offset + ends[relative]]
        if len(template) < _MONSTER_HEADER_SIZE:
            continue
        action_count = struct.unpack_from("<i", template, 0x50)[0]
        if (action_count < 0
                or _MONSTER_HEADER_SIZE + action_count * 8 > len(template)):
            continue
        template_id = template[0x18]
        for slot in range(8):
            handler, value = struct.unpack_from("<BB", template, 0x40 + slot * 2)
            if handler == 3:
                reward_keys.add(template_id * 16 + value)

    if not reward_keys:
        return []

    if rewards_offset + 4 > len(battle):
        return []
    reward_count = struct.unpack_from("<H", battle, rewards_offset + 2)[0]
    reward_table_end = rewards_offset + 4 + reward_count * 0x44
    if reward_table_end > len(battle):
        return []

    battle_absolute = records_start + battle_section_offset
    material_offsets = []
    for index in range(reward_count):
        entry_offset = rewards_offset + 4 + index * 0x44
        reward_key = struct.unpack_from("<I", battle, entry_offset)[0]
        if reward_key not in reward_keys:
            continue
        item_offset = battle_absolute + entry_offset + 4
        if not any(data[item_offset:item_offset + 0x14]):
            continue
        info = struct.unpack_from("<I", data, item_offset + 0x14)[0]
        category = (info >> 8) & 0x3
        # Only armor (1) and weapons (0) have a randomizable material in this field.
        if category in (0, 1):
            material_offsets.append(item_offset + 0x14)
    return material_offsets


def randomize_equipment_drop_materials(
    project_directory: str | Path, seed: int
) -> int:
    """Assign random primary materials to weapons/armor in drops."""
    ana = Path(project_directory).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(_error_message("error_ana_folder_missing", path=ana))

    rng = random.Random(seed)
    changed: dict[Path, bytearray] = {}
    count = 0
    for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG"):
        for path in sorted(ana.glob(pattern)):
            if not path.is_file():
                continue
            original = path.read_bytes()
            offsets = _find_scene_equipment_drop_materials(original)
            if not offsets:
                continue
            mutable = bytearray(original)
            for offset in offsets:
                info = struct.unpack_from("<I", mutable, offset)[0]
                material = rng.randrange(64)  # IDs 0–63 are primary materials.
                info = (info & ~(0x3F << 16)) | (material << 16)
                struct.pack_into("<I", mutable, offset, info)
                count += 1
            changed[path] = mutable

    if not count:
        raise RuntimeError(_error_message("error_no_equipment_drops"))
    for path, data in changed.items():
        path.write_bytes(data)
    return count


def _randomize_item_destinations(
    project_directory: str | Path,
    seed: int,
    include_chests: bool,
    include_item_drops: bool,
) -> tuple[int, int]:
    """Assign IDs from the same catalog to chests and/or drops with replacement."""
    ana = Path(project_directory).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(_error_message("error_ana_folder_missing", path=ana))
    scenes = sorted(
        path for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG")
        for path in ana.glob(pattern) if path.is_file()
    )
    changed: dict[Path, bytearray] = {}
    destinations: list[tuple[Path, int, int, int]] = []

    for path in scenes:
        data = path.read_bytes()
        if include_chests:
            for offset, item_id in _find_scene_chests(data):
                destinations.append((path, offset, item_id, 2))
                changed.setdefault(path, bytearray(data))
        if include_item_drops:
            for offset, item_id in _find_scene_item_drops(data):
                destinations.append((path, offset, item_id, 1))
                changed.setdefault(path, bytearray(data))

    chest_count = sum(width == 2 for _, _, _, width in destinations)
    drop_count = len(destinations) - chest_count
    if not destinations:
        if include_chests and include_item_drops:
            raise RuntimeError(_error_message("error_no_chests_or_item_drops"))
        if include_chests:
            raise RuntimeError(_error_message("error_no_compatible_chests"))
        raise RuntimeError(_error_message("error_no_compatible_item_drops"))

    item_kinds = tuple(range(0xFF))
    rng = random.Random(seed)
    for path, offset, current_item, width in destinations:
        # Choose with replacement across destinations; only avoid a destination
        # keeping its original value by chance.
        replacement_pool = item_kinds[:current_item] + item_kinds[current_item + 1:]
        replacement = rng.choice(replacement_pool)
        if width == 2:
            struct.pack_into("<H", changed[path], offset, replacement)
        else:
            changed[path][offset] = replacement

    for path, data in changed.items():
        path.write_bytes(data)
    return chest_count, drop_count


def randomize_item_drops(project_directory: str | Path, seed: int) -> int:
    """Randomize direct enemy drops; handler 3 is left unchanged."""
    _, drop_count = _randomize_item_destinations(
        project_directory, seed, include_chests=False, include_item_drops=True
    )
    return drop_count


def randomize_chests_and_item_drops(
    project_directory: str | Path, seed: int
) -> tuple[int, int]:
    """Randomize chests and direct drops from the same pool with replacement."""
    return _randomize_item_destinations(
        project_directory, seed, include_chests=True, include_item_drops=True
    )


def _scene_resources(data: bytes) -> tuple[int, list[tuple[int, bytes]]] | None:
    """Return a scene's resources with their absolute offsets in the IMG."""
    if len(data) < 40:
        return None
    offsets = struct.unpack_from("<10I", data)
    if (offsets[0] != 40 or tuple(sorted(offsets)) != offsets
            or offsets[-1] > len(data)):
        return None

    records_start, records_end = offsets[4:6]
    section = data[records_start:records_end]
    if len(section) < 4:
        return None
    directory_size = struct.unpack_from("<I", section)[0]
    if (directory_size < 4 or directory_size % 4
            or directory_size > len(section)):
        return None
    resource_offsets = struct.unpack_from(
        f"<{directory_size // 4}I", section
    )
    if any(offset < directory_size or offset > len(section) or offset % 4
           for offset in resource_offsets):
        return None

    starts = sorted(set(resource_offsets))
    resources = []
    for start, end in zip(starts, starts[1:] + [len(section)]):
        resource = section[start:end]
        if len(resource) >= 2:
            resources.append((records_start + start, resource))
    return records_start, resources


def _shop_entries(
    resource: bytes, absolute_offset: int
) -> list[tuple[int, int]] | None:
    """Return (word offset, word) for each physical shop slot."""
    if len(resource) < 8:
        return None
    directory_size = struct.unpack_from("<I", resource, 4)[0]
    if (directory_size < 8 or directory_size % 4
            or directory_size > len(resource)):
        return None
    pointers = struct.unpack_from(
        f"<{directory_size // 4 - 1}I", resource, 4
    )
    if any(pointer < directory_size or pointer % 4 or pointer + 4 > len(resource)
           for pointer in pointers):
        return None

    entries = []
    for pointer in sorted(set(pointers)):
        count = struct.unpack_from("<I", resource, pointer)[0]
        end = pointer + 4 + count * 4
        if end > len(resource):
            return None
        for index in range(count):
            entry_offset = absolute_offset + pointer + 4 + index * 4
            word = struct.unpack_from("<I", resource, pointer + 4 + index * 4)[0]
            entries.append((entry_offset, word))
    return entries


def randomize_normal_shop_items(
    project_directory: str | Path, seed: int
) -> int:
    """Permute normal items between shop slots while preserving their prices."""
    ana = Path(project_directory).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(_error_message("error_ana_folder_missing", path=ana))

    destinations: list[tuple[Path, int, int]] = []
    for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG"):
        for path in sorted(ana.glob(pattern)):
            if not path.is_file():
                continue
            data = path.read_bytes()
            parsed = _scene_resources(data)
            if parsed is None:
                continue
            _, resources = parsed
            for absolute_offset, resource in resources:
                if struct.unpack_from("<H", resource)[0] != 0x000A:
                    continue
                entries = _shop_entries(resource, absolute_offset)
                if entries is None:
                    continue
                for offset, word in entries:
                    # Bit 8=0: the low byte is a global item kind, not a template.
                    if not (word & 0x100) and (word & 0xFF) != 0xFF:
                        destinations.append((path, offset, word))

    if not destinations:
        raise RuntimeError(_error_message("error_no_normal_shop_slots"))

    items = [word & 0xFF for _, _, word in destinations]
    random.Random(seed).shuffle(items)
    changed_files: dict[Path, bytearray] = {}
    for (path, offset, word), item_id in zip(destinations, items):
        if path not in changed_files:
            changed_files[path] = bytearray(path.read_bytes())
        new_word = (word & ~0xFF) | item_id
        struct.pack_into("<I", changed_files[path], offset, new_word)

    for path, data in changed_files.items():
        path.write_bytes(data)
    return len(destinations)


def _equipment_tables_from_scenes(ana: Path) -> tuple[bytes, bytes]:
    """Load the shared FIELD tables for weapons/armor and instruments."""
    required_sizes = {
        0x0004: 4 + 32 * 0x0C + 64 * 0x14,
        0x000F: 4 + 64 + 64 * 4 * 2,
    }
    found_tables: dict[int, set[bytes]] = {resource_id: set() for resource_id in required_sizes}
    for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG"):
        for path in sorted(ana.glob(pattern)):
            if not path.is_file():
                continue
            parsed = _scene_resources(path.read_bytes())
            if parsed is None:
                continue
            _, resources = parsed
            for _, resource in resources:
                resource_id = struct.unpack_from("<H", resource)[0]
                if resource_id not in required_sizes:
                    continue
                required_size = required_sizes[resource_id]
                if len(resource) >= required_size:
                    found_tables[resource_id].add(resource[:required_size])

    for resource_id, tables in found_tables.items():
        if not tables:
            raise RuntimeError(
                _error_message(
                    "error_field_generation_table_missing",
                    resource_id=f"0x{resource_id:04X}",
                )
            )
        if len(tables) > 1:
            raise RuntimeError(
                _error_message(
                    "error_field_generation_table_conflict",
                    resource_id=f"0x{resource_id:04X}",
                )
            )
    return next(iter(found_tables[0x0004])), next(iter(found_tables[0x000F]))


def _recalculate_equipment_item(
    data: bytearray,
    record_offset: int,
    info: int,
    material: int,
    item_table: bytes,
    instrument_table: bytes,
) -> None:
    """Update material-dependent values according to the FIELD routines."""
    category = (info >> 8) & 0x3
    item_type = (info >> 10) & 0x3F
    if category == 2:
        if item_type >= 4:
            return
        # FieldItemGridTable.pairs[material][instrument_type][1].
        pair_offset = 4 + 64 + (material * 4 + item_type) * 2
        data[record_offset + 0x26] = instrument_table[pair_offset + 1]
        return

    if category not in (0, 1) or item_type >= 16:
        return

    type_table_offset = 4 + (0 if category == 0 else 16 * 0x0C)
    type_offset = type_table_offset + item_type * 0x0C
    material_table_offset = 4 + 32 * 0x0C
    material_offset = material_table_offset + material * 0x14
    type_weights = item_table[type_offset + 4:type_offset + 8]
    type_factors = item_table[type_offset + 8:type_offset + 12]
    divisor = struct.unpack_from("<H", item_table, material_offset + 2)[0]
    material_weights = item_table[material_offset + 4:material_offset + 8]
    multipliers = item_table[material_offset + 8:material_offset + 12]

    if category == 0:
        if divisor == 0:
            return
        weight = sum(a * b for a, b in zip(type_weights, material_weights))
        bonus_levels = struct.unpack_from("<I", data, record_offset + 0x18)[0]
        level_sum = sum((bonus_levels >> shift) & 0xF for shift in range(0, 32, 4))
        power = ((weight * (level_sum + divisor) // divisor) >> 7) & 0xFFFF
        # US FIELD clamps derived weapon power at 999.
        if power >= 1000:
            power = 999
        struct.pack_into("<H", data, record_offset + 0x24, power)
        for index, (factor, multiplier) in enumerate(zip(type_factors, multipliers)):
            data[record_offset + 0x30 + index] = (factor * multiplier) >> 6
        return

    for index, (weight, multiplier, factor) in enumerate(
        zip(type_weights, multipliers, type_factors)
    ):
        value = (weight * multiplier) >> 6
        if value >= 1000:
            value = 999
        struct.pack_into("<H", data, record_offset + 0x24 + index * 2, value)
        data[record_offset + 0x30 + index] = (factor * multiplier) >> 6


def randomize_equipment_shop_materials(
    project_directory: str | Path, seed: int
) -> int:
    """Change materials for weapons, armor, and instruments sold in shops."""
    ana = Path(project_directory).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(_error_message("error_ana_folder_missing", path=ana))

    item_table, instrument_table = _equipment_tables_from_scenes(ana)
    rng = random.Random(seed)
    changed_files: dict[Path, bytearray] = {}
    material_offsets: dict[Path, set[int]] = {}
    for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG"):
        for path in sorted(ana.glob(pattern)):
            if not path.is_file():
                continue
            data = path.read_bytes()
            parsed = _scene_resources(data)
            if parsed is None:
                continue
            _, resources = parsed
            shop_resources = [
                (offset, resource)
                for offset, resource in resources
                if struct.unpack_from("<H", resource)[0] == 0x000A
            ]
            template_resources = [
                (offset, resource) for offset, resource in resources
                if struct.unpack_from("<H", resource)[0] == 0x0005
            ]
            if not shop_resources or len(template_resources) != 1:
                continue

            template_offset, templates = template_resources[0]
            if len(templates) < 4:
                continue
            template_count = struct.unpack_from("<H", templates, 2)[0]
            if 4 + template_count * 0x40 > len(templates):
                continue

            for shop_offset, shop in shop_resources:
                entries = _shop_entries(shop, shop_offset)
                if entries is None:
                    continue
                for _, word in entries:
                    if not (word & 0x100):
                        continue
                    template_index = word & 0xFF
                    if template_index >= template_count:
                        continue
                    record_offset = (
                        template_offset + 4 + template_index * 0x40
                    )
                    if not any(data[record_offset:record_offset + 0x14]):
                        continue
                    info = struct.unpack_from("<I", data, record_offset + 0x14)[0]
                    category = (info >> 8) & 0x3
                    if category in (0, 1, 2):
                        material_offsets.setdefault(path, set()).add(
                            record_offset + 0x14
                        )

            for offset in sorted(material_offsets.get(path, set())):
                if path not in changed_files:
                    changed_files[path] = bytearray(data)
                info = struct.unpack_from("<I", changed_files[path], offset)[0]
                current_material = (info >> 16) & 0x3F
                category = (info >> 8) & 0x3
                if category in (0, 1):
                    material_table_offset = 4 + 32 * 0x0C
                    candidates = [
                        value for value in range(64)
                        if value != current_material
                        and struct.unpack_from(
                            "<H", item_table,
                            material_table_offset + value * 0x14 + 2,
                        )[0] != 0
                    ]
                else:
                    candidates = [
                        value for value in range(64)
                        if value != current_material
                    ]
                if not candidates:
                    continue
                material = rng.choice(candidates)
                info = (info & ~(0x3F << 16)) | (material << 16)
                struct.pack_into("<I", changed_files[path], offset, info)
                _recalculate_equipment_item(
                    changed_files[path], offset - 0x14, info, material,
                    item_table, instrument_table,
                )

    count = sum(len(offsets) for offsets in material_offsets.values())
    if not count:
        raise RuntimeError(_error_message("error_no_equipment_shop_items"))
    for path, data in changed_files.items():
        path.write_bytes(data)
    return count


def _find_scene_enemies(
    data: bytes,
) -> list[tuple[int, tuple[int, int, int]]]:
    """Return (record offset, identity) for each linked enemy.

    The identity contains the template_id, resource selector, and palette.
    """
    if len(data) < 40:
        return []
    offsets = struct.unpack_from("<10I", data)
    if offsets[0] != 40 or tuple(sorted(offsets)) != offsets or any(
        offset > len(data) or offset % 4 for offset in offsets
    ):
        return []

    layout_offset, event_offset = offsets[:2]
    if event_offset - layout_offset < 4:
        return []
    record_count = struct.unpack_from("<I", data, layout_offset)[0]
    if event_offset - layout_offset != 4 + record_count * _FIELD_LAYOUT_RECORD.size:
        return []

    template_ids = _battle_template_ids(data, offsets)
    if not template_ids:
        return []
    event_scripts = data[event_offset:offsets[2]]
    enemies = []
    for index in range(record_count):
        record_offset = layout_offset + 4 + index * _FIELD_LAYOUT_RECORD.size
        record = _FIELD_LAYOUT_RECORD.unpack_from(data, record_offset)
        control, source, scripts = record[0], record[5], record[7:]
        kind = (control >> 4) & 0xF
        if kind not in (0, 7):
            continue
        # Exclude chests, even when their actor type is 0 or 7.
        if (source & 7) == 5 and scripts[15] != 0xFFFF:
            initializer = scripts[15]
            if initializer & 0x8000:
                table_offset = (initializer & 0x7FFF) * 2
                if table_offset + 2 <= len(event_scripts):
                    script_offset = struct.unpack_from("<H", event_scripts, table_offset)[0]
                    if (script_offset >= table_offset + 2
                            and event_scripts[script_offset:].startswith(_CHEST_INITIALIZER)):
                        continue
        template_id = (control >> 8) & 0xFF
        if template_id in template_ids:
            # Keep the battle template and its visual resource together.
            palette = (control >> 24) & 0xF
            enemies.append((record_offset, (template_id, source, palette)))
    return enemies

