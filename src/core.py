"""Operaciones principales del aleatorizador."""

from __future__ import annotations

import random
import struct
import subprocess
import sys
from pathlib import Path


def _buscar_ejecutable(raiz_proyecto: Path, nombre: str) -> Path:
    for candidato in (raiz_proyecto / nombre, raiz_proyecto / "bin" / nombre):
        if candidato.is_file():
            return candidato

    ignoradas = {".git", ".venv", "venv", "__pycache__"}
    candidatos = sorted(
        (
            ruta
            for ruta in raiz_proyecto.rglob(nombre)
            if not any(parte in ignoradas for parte in ruta.relative_to(raiz_proyecto).parts)
        ),
        key=lambda ruta: (len(ruta.relative_to(raiz_proyecto).parts), str(ruta).lower()),
    )
    if candidatos:
        return candidatos[0]
    raise FileNotFoundError(
        f"No se encontró {nombre}. Comprueba que mkpsxiso esté instalado en la raíz del proyecto."
    )


def _ejecutar(comando: list[str], directorio_trabajo: Path) -> None:
    opciones = {
        "cwd": directorio_trabajo,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "check": False,
    }
    if sys.platform.startswith("win"):
        opciones["creationflags"] = subprocess.CREATE_NO_WINDOW

    resultado = subprocess.run(comando, **opciones)
    if resultado.returncode != 0:
        detalle = (resultado.stderr or resultado.stdout).strip()
        if not detalle:
            detalle = f"El proceso terminó con código {resultado.returncode}."
        raise RuntimeError(detalle)


def generar(imagen_disco: str | Path, raiz_proyecto: str | Path) -> Path:
    """Extrae una imagen de PS1 en legend_of_mana y crea allí el XML de proyecto."""
    imagen = Path(imagen_disco).expanduser().resolve()
    raiz = Path(raiz_proyecto).expanduser().resolve()
    if not imagen.is_file():
        raise FileNotFoundError(f"No se encontró la imagen de disco: {imagen}")

    destino = raiz / "legend_of_mana"
    destino.mkdir(parents=True, exist_ok=True)
    ejecutable = _buscar_ejecutable(
        raiz, "dumpsxiso.exe" if sys.platform.startswith("win") else "dumpsxiso"
    )
    xml_proyecto = destino / "legend_of_mana.xml"

    _ejecutar(
        [str(ejecutable), "-x", str(destino), "-s", str(xml_proyecto), str(imagen)],
        raiz,
    )
    return destino


def construir_imagen(
    carpeta_proyecto: str | Path,
    carpeta_salida: str | Path,
    raiz_proyecto: str | Path,
) -> Path:
    """Construye un BIN/CUE desde legend_of_mana en la carpeta elegida."""
    fuente = Path(carpeta_proyecto).expanduser().resolve()
    salida = Path(carpeta_salida).expanduser().resolve()
    raiz = Path(raiz_proyecto).expanduser().resolve()
    xml_proyecto = fuente / "legend_of_mana.xml"
    if not xml_proyecto.is_file():
        raise FileNotFoundError(f"No se encontró el proyecto XML: {xml_proyecto}")
    if not salida.is_dir():
        raise NotADirectoryError(f"La carpeta de salida no existe: {salida}")

    nombre_base = "legend_of_mana"
    imagen_salida = salida / f"{nombre_base}.bin"
    cue_salida = salida / f"{nombre_base}.cue"
    existentes = [archivo for archivo in (imagen_salida, cue_salida) if archivo.exists()]
    if existentes:
        rutas = ", ".join(str(archivo) for archivo in existentes)
        raise FileExistsError(
            f"Ya existen archivos de salida en la carpeta seleccionada: {rutas}. "
            "Elige otra carpeta para evitar sobrescribirlos."
        )

    ejecutable = _buscar_ejecutable(
        raiz, "mkpsxiso.exe" if sys.platform.startswith("win") else "mkpsxiso"
    )
    _ejecutar(
        [
            str(ejecutable),
            "-o",
            str(imagen_salida),
            "-c",
            str(cue_salida),
            str(xml_proyecto),
        ],
        salida,
    )
    return imagen_salida


# Formato y firma tomados de lom-decomp/tools/data/scenes/layout.py.
# FieldLayoutRecord tiene 48 bytes; scripts[4] (item_id) comienza en el byte 24.
_FIELD_LAYOUT_RECORD = struct.Struct("<IHBBIHH16H")
_CHEST_INITIALIZER = bytes.fromhex(
    "40 84 20 c0 "
    "0c 01 02 ff 10 00 08 40 40 e0 "
    "0c 01 02 ff 10 00 09 40 50 e0"
)


def _encontrar_cofres_escena(data: bytes) -> list[tuple[int, int]]:
    """Devuelve (offset del item_id dentro del IMG, item_id) para cada cofre confirmado."""
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
                f"El cofre de índice {index} contiene el item_id reservado 0xFF."
            )
        chests.append((record_offset + 24, item_id))
    return chests


def aleatorizar_cofres(carpeta_proyecto: str | Path, semilla: int) -> int:
    """Baraja los item_id de los cofres y los escribe en sus archivos IMG originales.

    La detección y los offsets siguen el formato documentado por lom-decomp. La
    lista de objetos se conserva como multiconjunto, y la semilla hace que la
    permutación pueda reproducirse.
    """
    ana = Path(carpeta_proyecto).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(f"No se encontró la carpeta ANA: {ana}")

    escenas = sorted(
        path
        for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG")
        for path in ana.glob(pattern)
        if path.is_file()
    )
    cambios: dict[Path, tuple[bytearray, list[tuple[int, int]]]] = {}
    ids_originales: list[int] = []
    for escena in escenas:
        data = escena.read_bytes()
        cofres = _encontrar_cofres_escena(data)
        if cofres:
            mutable = bytearray(data)
            cambios[escena] = (mutable, cofres)
            ids_originales.extend(item_id for _, item_id in cofres)

    if not ids_originales:
        raise RuntimeError("No se encontraron cofres compatibles para aleatorizar.")

    ids_aleatorios = ids_originales.copy()
    random.Random(semilla).shuffle(ids_aleatorios)
    cursor = 0
    for mutable, cofres in cambios.values():
        for offset, _ in cofres:
            struct.pack_into("<H", mutable, offset, ids_aleatorios[cursor])
            cursor += 1

    for escena, (mutable, _) in cambios.items():
        escena.write_bytes(mutable)
    return len(ids_originales)


_BATTLE_RESOURCE_ID = 1
_MONSTER_HEADER_SIZE = 0x54


def _ids_plantillas_batalla(data: bytes, offsets: tuple[int, ...]) -> set[int] | None:
    """Lee IDs de plantillas de batalla si la escena tiene un único recurso de batalla.

    Sigue read_resource_directory() y read_battle_resource() de
    lom-decomp/tools/data/scenes/scene_resources.py. None indica que el vínculo
    es ambiguo o que la estructura no se puede validar con seguridad.
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


def _encontrar_botines_objetos_escena(data: bytes) -> list[tuple[int, int]]:
    """Devuelve (offset del valor, item kind actual) de botines directos."""
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


def _encontrar_materiales_botines_equipamento_escena(data: bytes) -> list[int]:
    """Encuentra el campo material de armas/armaduras en recompensas de enemigos."""
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
    # Si no se puede establecer una asociación inequívoca de recursos, no modificar.
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
        # En este campo solo armaduras (1) y armas (0) tienen material aleatorizable.
        if category in (0, 1):
            material_offsets.append(item_offset + 0x14)
    return material_offsets


def aleatorizar_materiales_botines_equipamento(
    carpeta_proyecto: str | Path, semilla: int
) -> int:
    """Asigna materiales primarios aleatorios a armas/armaduras de botines."""
    ana = Path(carpeta_proyecto).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(f"No se encontró la carpeta ANA: {ana}")

    rng = random.Random(semilla)
    changed: dict[Path, bytearray] = {}
    count = 0
    for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG"):
        for path in sorted(ana.glob(pattern)):
            if not path.is_file():
                continue
            original = path.read_bytes()
            offsets = _encontrar_materiales_botines_equipamento_escena(original)
            if not offsets:
                continue
            mutable = bytearray(original)
            for offset in offsets:
                info = struct.unpack_from("<I", mutable, offset)[0]
                material = rng.randrange(64)  # Los IDs 0–63 son materiales primarios.
                info = (info & ~(0x3F << 16)) | (material << 16)
                struct.pack_into("<I", mutable, offset, info)
                count += 1
            changed[path] = mutable

    if not count:
        raise RuntimeError(
            "No se encontraron botines de armas o armaduras compatibles para aleatorizar."
        )
    for path, data in changed.items():
        path.write_bytes(data)
    return count


def _aleatorizar_destinos_objeto(
    carpeta_proyecto: str | Path,
    semilla: int,
    incluir_cofres: bool,
    incluir_botines: bool,
) -> tuple[int, int]:
    """Asigna IDs del mismo catálogo a cofres y/o botines con reemplazo."""
    ana = Path(carpeta_proyecto).expanduser().resolve() / "ANA"
    if not ana.is_dir():
        raise FileNotFoundError(f"No se encontró la carpeta ANA: {ana}")
    scenes = sorted(
        path for pattern in ("INFO_*/*.IMG", "MAPINFO/*.IMG")
        for path in ana.glob(pattern) if path.is_file()
    )
    changed: dict[Path, bytearray] = {}
    destinations: list[tuple[Path, int, int, int]] = []

    for path in scenes:
        data = path.read_bytes()
        if incluir_cofres:
            for offset, item_id in _encontrar_cofres_escena(data):
                destinations.append((path, offset, item_id, 2))
                changed.setdefault(path, bytearray(data))
        if incluir_botines:
            for offset, item_id in _encontrar_botines_objetos_escena(data):
                destinations.append((path, offset, item_id, 1))
                changed.setdefault(path, bytearray(data))

    chest_count = sum(width == 2 for _, _, _, width in destinations)
    drop_count = len(destinations) - chest_count
    if not destinations:
        if incluir_cofres and incluir_botines:
            raise RuntimeError(
                "No se encontraron cofres ni botines de objetos compatibles."
            )
        if incluir_cofres:
            raise RuntimeError("No se encontraron cofres compatibles para aleatorizar.")
        raise RuntimeError("No se encontraron botines de objetos compatibles.")

    item_kinds = tuple(range(0xFF))
    rng = random.Random(semilla)
    for path, offset, current_item, width in destinations:
        # Elegimos con reemplazo entre destinos; solo evitamos que un destino
        # conserve su valor original por azar.
        replacement_pool = item_kinds[:current_item] + item_kinds[current_item + 1:]
        replacement = rng.choice(replacement_pool)
        if width == 2:
            struct.pack_into("<H", changed[path], offset, replacement)
        else:
            changed[path][offset] = replacement

    for path, data in changed.items():
        path.write_bytes(data)
    return chest_count, drop_count


def aleatorizar_botines_objetos(carpeta_proyecto: str | Path, semilla: int) -> int:
    """Aleatoriza botines directos de enemigos; el manejador 3 no se altera."""
    _, drop_count = _aleatorizar_destinos_objeto(
        carpeta_proyecto, semilla, incluir_cofres=False, incluir_botines=True
    )
    return drop_count


def aleatorizar_cofres_y_botines_objetos(
    carpeta_proyecto: str | Path, semilla: int
) -> tuple[int, int]:
    """Aleatoriza cofres y botines directos desde un mismo pool con reemplazo."""
    return _aleatorizar_destinos_objeto(
        carpeta_proyecto, semilla, incluir_cofres=True, incluir_botines=True
    )


def _encontrar_enemigos_escena(
    data: bytes,
) -> list[tuple[int, tuple[int, int, int]]]:
    """Devuelve (offset del registro, identidad) de cada enemigo enlazado.

    La identidad contiene template_id, selector de recursos y paleta.
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

    template_ids = _ids_plantillas_batalla(data, offsets)
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
        # No incluir los cofres, aunque su tipo de actor sea 0 o 7.
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
            # Conservar juntos la plantilla de batalla y su recurso visual.
            palette = (control >> 24) & 0xF
            enemies.append((record_offset, (template_id, source, palette)))
    return enemies

