"""Operaciones principales del aleatorizador."""

from __future__ import annotations

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
