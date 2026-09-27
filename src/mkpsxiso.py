"""Descarga e instalación local de mkpsxiso desde GitHub Releases."""

from __future__ import annotations

import json
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


RELEASE_API = "https://api.github.com/repos/Lameguy64/mkpsxiso/releases/latest"
MARKER_NAME = ".mkpsxiso-install.json"
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")


def _operating_system() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"Sistema operativo no compatible: {sys.platform}")


def _asset_os(name: str) -> str | None:
    normalized = name.lower().replace("_", "-").replace(" ", "-")
    if any(token in normalized for token in ("windows", "win32", "win64", "win-")):
        return "windows"
    if any(token in normalized for token in ("macos", "mac-os", "osx", "darwin")):
        return "macos"
    if "linux" in normalized:
        return "linux"
    return None


def _asset_arch(name: str) -> str | None:
    normalized = name.lower().replace("-", "_")
    if any(token in normalized for token in ("aarch64", "arm64")):
        return "arm64"
    if any(token in normalized for token in ("x86_64", "amd64", "x64", "win64")):
        return "x64"
    if any(token in normalized for token in ("i386", "i686", "x86", "win32")):
        return "x86"
    return None


def _current_arch() -> str | None:
    arch = platform.machine().lower()
    if arch in {"aarch64", "arm64"}:
        return "arm64"
    if arch in {"x86_64", "amd64", "x64"}:
        return "x64"
    if arch in {"i386", "i686", "x86"}:
        return "x86"
    return None


def _select_asset(assets: list[dict[str, Any]], operating_system: str) -> dict[str, Any]:
    candidates = [
        asset
        for asset in assets
        if _asset_os(asset.get("name", "")) == operating_system
        and asset.get("name", "").lower().endswith(ARCHIVE_SUFFIXES)
    ]
    if not candidates:
        raise RuntimeError(
            f"La última versión de mkpsxiso no ofrece un archivo comprimido para {operating_system}."
        )

    arch = _current_arch()
    exact_arch = [asset for asset in candidates if _asset_arch(asset["name"]) == arch]
    generic = [asset for asset in candidates if _asset_arch(asset["name"]) is None]
    if exact_arch:
        candidates = exact_arch
    elif generic:
        candidates = generic
    elif len(candidates) > 1:
        raise RuntimeError(
            f"No se encontró una descarga compatible con la arquitectura {platform.machine()}."
        )
    return candidates[0]


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "RandLom",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"No se pudo consultar la última versión de mkpsxiso en GitHub: {error}") from error


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "RandLom"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"No se pudo descargar mkpsxiso: {error}") from error


def _safe_archive_path(root: Path, member_name: str) -> Path:
    relative = PurePosixPath(member_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("El archivo descargado contiene una ruta no segura.")
    destination = root.joinpath(*relative.parts).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise RuntimeError("El archivo descargado intenta salir de la carpeta de instalación.")
    return destination


def _extract_archive(archive: Path, destination: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                path = _safe_archive_path(destination, member.filename)
                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise RuntimeError("El archivo descargado contiene un enlace no permitido.")
                if member.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, path.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if unix_mode:
                    path.chmod(unix_mode & 0o777)
        return

    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as tarred:
            for member in tarred.getmembers():
                path = _safe_archive_path(destination, member.name)
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    source = tarred.extractfile(member)
                    if source is None:
                        raise RuntimeError("No se pudo leer un archivo del paquete descargado.")
                    with source, path.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    path.chmod(member.mode & 0o777)
                else:
                    raise RuntimeError("El archivo descargado contiene un enlace o tipo de archivo no permitido.")
        return

    raise RuntimeError("El archivo descargado no es un ZIP ni un TAR compatible.")


def _find_binary(application_root: Path, binary_name: str) -> Path | None:
    for candidate in (application_root / binary_name, application_root / "bin" / binary_name):
        if candidate.is_file():
            return candidate
    return next(application_root.rglob(binary_name), None)


def mkpsxiso_is_installed(application_root: Path) -> bool:
    """Indica si el ejecutable ya está disponible en la carpeta de la aplicación."""
    binary_name = "mkpsxiso.exe" if _operating_system() == "windows" else "mkpsxiso"
    return _find_binary(application_root.resolve(), binary_name) is not None


def ensure_mkpsxiso(application_root: Path) -> str | None:
    """Instala mkpsxiso en la raíz de la aplicación si todavía no está presente."""
    application_root = application_root.resolve()
    application_root.mkdir(parents=True, exist_ok=True)
    binary_name = "mkpsxiso.exe" if _operating_system() == "windows" else "mkpsxiso"
    marker_path = application_root / MARKER_NAME
    binary_path = _find_binary(application_root, binary_name)
    if marker_path.is_file() and binary_path is not None:
        return None
    if binary_path is not None:
        return None

    release = _request_json(RELEASE_API)
    operating_system = _operating_system()
    asset = _select_asset(release.get("assets", []), operating_system)
    with tempfile.TemporaryDirectory(
        prefix=".mkpsxiso-", dir=application_root
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        archive_path = temporary_root / asset["name"]
        extracted_path = temporary_root / "extracted"
        extracted_path.mkdir()
        _download(asset["browser_download_url"], archive_path)
        _extract_archive(archive_path, extracted_path)

        for entry in extracted_path.iterdir():
            destination = application_root / entry.name
            if entry.is_dir():
                shutil.copytree(entry, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, destination)

    binary_path = _find_binary(application_root, binary_name)
    if binary_path is None:
        raise RuntimeError(
            f"La descarga terminó, pero no se encontró {binary_name} en los archivos extraídos."
        )
    if operating_system != "windows":
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    marker_path.write_text(
        json.dumps(
            {"version": release.get("tag_name", "desconocida"), "asset": asset["name"]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"mkpsxiso {release.get('tag_name', '')} se descargó e instaló correctamente."






