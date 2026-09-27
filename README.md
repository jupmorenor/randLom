# RandLom

RandLom es una aplicación de escritorio para preparar una imagen de *Legend of Mana* de PlayStation 1 y generar una nueva imagen a partir de los archivos extraídos. Está construida con Python y PyQt6 y es compatible con Windows, Linux y macOS.

## Flujo de uso

1. Selecciona una imagen de disco de PlayStation 1.
2. Opcionalmente, pulsa **Agregar semilla** para introducir una semilla numérica. Si no indicas una, la aplicación genera una automáticamente y la muestra en la ventana.
3. Pulsa **Generar** y confirma la operación.
4. RandLom extrae los archivos en `legend_of_mana`, dentro de la carpeta de la aplicación, y solicita dónde guardar la imagen resultante.
5. Al terminar, muestra la ruta de la imagen generada (`legend_of_mana.bin` y `legend_of_mana.cue`).

La semilla queda preparada para los procesos de aleatorización que se incorporarán al flujo. Esos procesos todavía no están implementados.

RandLom descarga la versión más reciente de **mkpsxiso** desde sus lanzamientos de GitHub la primera vez que se genera una imagen, y reutiliza los archivos descargados en ejecuciones posteriores.

## Ejecutar desde el código fuente

Se requiere Python 3.10 o posterior. Instala PyQt6 y ejecuta la aplicación desde la raíz del repositorio:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install PyQt6
python main.py
```

En Linux o macOS, activa el entorno virtual con:

```bash
source .venv/bin/activate
```

## Descargas

Las publicaciones de GitHub Actions generan paquetes para:

- Windows x64: `RandLom-windows-x64.zip`
- Linux x64: `RandLom-linux-x64.tar.gz`
- macOS ARM64: `RandLom-macos-arm64.zip`

Para crear una publicación, sube un tag con formato `v*.*.*` (por ejemplo, `v1.0.0`).
