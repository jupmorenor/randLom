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


def aleatorizar_enemigos_local(carpeta_proyecto: str | Path, semilla: int) -> int:
    """Baraja las identidades de enemigos enlazados dentro de cada escena.

    Cada identidad conserva juntos el ID de plantilla, su recurso gráfico/de
    acciones y la paleta. Las identidades no cruzan los límites de su escena,
    que usa sus propios recursos. Los enemigos creados dinámicamente por scripts
    no forman parte de estos registros estáticos y quedan fuera del alcance. Este
    modo se denomina local para distinguirlo de futuras opciones entre escenas.
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
    cambios: dict[
        Path, tuple[bytearray, list[tuple[int, tuple[int, int, int]]]]
    ] = {}
    total = 0
    for escena in escenas:
        data = escena.read_bytes()
        enemigos = _encontrar_enemigos_escena(data)
        if enemigos:
            cambios[escena] = (bytearray(data), enemigos)
            total += len(enemigos)

    if not total:
        raise RuntimeError("No se encontraron enemigos enlazados para aleatorizar.")

    rng = random.Random(semilla)
    for mutable, enemigos in cambios.values():
        identidades = [identidad for _, identidad in enemigos]
        rng.shuffle(identidades)
        for (record_offset, _), (template_id, source, palette) in zip(
            enemigos, identidades
        ):
            control = struct.unpack_from("<I", mutable, record_offset)[0]
            control &= ~((0xFF << 8) | (0xF << 24))
            control |= (template_id << 8) | (palette << 24)
            struct.pack_into("<I", mutable, record_offset, control)
            struct.pack_into("<H", mutable, record_offset + 12, source)

    for escena, (mutable, _) in cambios.items():
        escena.write_bytes(mutable)
    return total
