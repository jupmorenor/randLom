# RandLom

[English](README.md) | [Español](README.es.md)

RandLom es una aplicación de escritorio para modificar imágenes de disco de **Legend of Mana** para PlayStation 1. Extrae la imagen seleccionada, aplica las aleatorizaciones solicitadas a los archivos del juego y construye una nueva imagen BIN/CUE.

La interfaz está disponible en inglés y español. Usa el menú **Idioma** para cambiar el idioma; el cambio se aplica inmediatamente.

## Características

### Semilla

Pulsa **Agregar semilla** para introducir una semilla numérica. Si no indicas una, RandLom genera una al iniciar el proceso y muestra el valor usado. Conserva ese valor para reproducir una ejecución con las mismas opciones.

### Aleatorizar objetos

Activa **Aleatorizar objetos** para mostrar las opciones de objetos:

- **Cofres**: aleatoriza los objetos encontrados en los cofres.
- **Botines de objetos**: aleatoriza los objetos directos que dejan los enemigos.
- **Botines de equipamento**: reemplaza el material de los objetos de equipamento que dejan los enemigos. El material se elige del catálogo de materiales primarios del juego y puede repetirse.

Los cofres y los botines de objetos se pueden activar simultáneamente. En ese caso, sus destinos existentes usan el mismo conjunto de objetos elegibles que no son equipables, con reemplazo; un objeto puede asignarse a varios destinos. Si solo se activa una opción, solo cambia ese tipo de destino. Los materiales de los botines de equipamento se aleatorizan de forma independiente.

### Tiendas de objetos

Activa **Tiendas de objetos** para mostrar:

- **Tiendas de objetos normales**: intercambia los objetos que ya ocupan los espacios de las tiendas normales, conservando los espacios y sus precios.
- **Tiendas de equipamento**: cambia los materiales de las armas, armaduras e instrumentos vendidos en las tiendas de equipamento y recalcula los valores derivados que dependen del material.

### Cambio entre escenas

Activa **Cambio entre escenas** y selecciona uno de los modos excluyentes:

- **Local**: intercambia destinos de habitaciones compatibles dentro de la misma tierra. Agrupa las escenas por el prefijo de su tierra e incluye archivos ubicados tanto en `INFO` como en `MAPINFO`.
- **Global con retorno**: intercambia transiciones compatibles entre tierras, conservando la ruta emparejada para regresar a la escena de origen.
- **Global extremo**: permuta transiciones compatibles de todo el juego, incluidas salidas al mapa del mundo y destinos especiales cuando es posible. No conserva una ruta de retorno.

### Validación

Antes de extraer, RandLom busca el identificador norteamericano `SLUS_010.13` o el japonés `SLPS_021.70`. Rechaza las imágenes que no contengan ninguno de ellos. El identificador japonés se reconoce, pero **el funcionamiento del aleatorizador no se ha verificado con la versión japonesa**.

## Pasos para generar una imagen modificada

1. Inicia RandLom y, si lo necesitas, selecciona el idioma en **Idioma**.
2. Selecciona una imagen de disco de Legend of Mana para PlayStation 1. El selector acepta `.cue`, `.bin`, `.iso`, `.img`, `.ccd`, `.chd`, `.mdf`, `.mds`, `.pbp`, `.toc` y `.cbn`. Para discos con varias pistas, selecciona el archivo CUE para que el extractor pueda acceder a todas.
3. Si quieres, introduce una semilla numérica. Si la dejas vacía, RandLom generará y mostrará una automáticamente.
4. Activa las secciones y opciones de aleatorización que quieras. En cambio entre escenas solo puedes seleccionar un modo.
5. Pulsa **Generar**. RandLom valida el identificador del juego antes de continuar.
6. Si `mkpsxiso` no está instalado junto a la aplicación, acepta su descarga. RandLom descarga el archivo comprimido más reciente de GitHub correspondiente al sistema operativo y, cuando está disponible, a la arquitectura. Se requiere conexión a internet.
7. Si no introdujiste una semilla, RandLom genera una y la muestra. Revisa el valor en el cuadro de confirmación y acepta para continuar.
8. RandLom extrae los archivos del disco y aplica los cambios seleccionados.
9. Selecciona una carpeta de salida. RandLom crea allí `legend_of_mana.bin` y `legend_of_mana.cue`.
10. Si la construcción termina correctamente, ya estás listo para jugar.

Conserva juntos los archivos BIN y CUE al usar la imagen generada. Si cancelas después de la extracción y antes de que termine la construcción, la carpeta temporal podría permanecer en la carpeta de la aplicación.

## Requisitos y compatibilidad

### Ejecución desde el código fuente

- Python **3.10 o posterior**.
- PyQt6 **6.7 o posterior** (`PyQt6>=6.7` en las dependencias del proyecto).
- Conexión a internet la primera vez que RandLom necesite descargar `mkpsxiso`.
- Sistema operativo compatible: Windows, Linux o macOS. La aplicación busca un paquete de `mkpsxiso` para el sistema operativo y arquitectura actuales; su disponibilidad depende de los archivos publicados por el proyecto original.

Crea un entorno virtual e instala la dependencia:

```bash
python -m venv .venv
```

En Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install "PyQt6>=6.7"
python main.py
```

En Linux o macOS:

```bash
source .venv/bin/activate
python -m pip install "PyQt6>=6.7"
python main.py
```

### Versiones precompiladas

GitHub Actions construye la aplicación con Python **3.12** para:

- Windows x64 (`RandLom-windows-x64.zip`)
- Linux x64 (`RandLom-linux-x64.tar.gz`)
- macOS ARM64 (`RandLom-macos-arm64.zip`)

El selector muestra extensiones comunes de imágenes de PlayStation, pero la compatibilidad real depende de que el formato pueda ser leído por la versión de `dumpsxiso` incluida. Se recomiendan archivos CUE y BIN sin comprimir con sectores de 2352 bytes.

## Dependencias

- [Python](https://www.python.org/) 3.10+ para ejecutar desde el código fuente.
- [PyQt6](https://pypi.org/project/PyQt6/) 6.7+ para la interfaz de escritorio.
- [mkpsxiso](https://github.com/Lameguy64/mkpsxiso) para extraer y reconstruir imágenes de PlayStation. RandLom descarga bajo demanda el paquete más reciente compatible; este proyecto no fija una versión concreta.

## Versiones publicadas

Descarga un paquete desde la página de [GitHub Releases](https://github.com/jupmorenor/randLom/releases) del repositorio. El workflow publica los archivos para Windows, Linux y macOS indicados arriba.

## Agradecimientos

Agradecimiento especial a [Celophi](https://github.com/celophi), autor de [lom-decomp](https://github.com/celophi/lom-decomp). Sin este proyecto, el desarrollo de RandLom habría tomado muchísimo más tiempo. Su documentación e investigación han sido invaluables para comprender los archivos de Legend of Mana e implementar las aleatorizaciones.
