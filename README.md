# RandLom

[English](README.md) | [Español](README.es.md)

RandLom is a desktop application for modifying a **Legend of Mana** PlayStation 1 disc image. It extracts the selected image, applies the requested randomizers to the game's files, and builds a new BIN/CUE image.

The interface is available in English and Spanish. Use the **Language** menu to switch languages; the change applies immediately.

## Features

### Seed

Choose **Add seed** to enter a numeric seed. If you leave it unset, RandLom creates a random seed when generation starts and displays the value used. Keep that value to reproduce a run with the same selections.

### Randomize items

Enable **Randomize items** to reveal the item randomization options:

- **Chests**: randomizes the items found in chests.
- **Item drops**: randomizes direct item drops from enemies.
- **Equipment drops**: replaces the material used by equipment items dropped by enemies. The material is selected from the game's primary material catalog and may appear more than once.

Chests and item drops can be enabled together. In that case, their existing destinations draw from the same pool of eligible non-equipment items, with replacement; the same item can be assigned to multiple destinations. If only one of the two options is enabled, only that destination type is changed. Equipment drop materials are randomized independently.

### Item shops

Enable **Item shops** to reveal:

- **Normal item shops**: shuffles the items already present in normal shop slots, preserving the existing slots and their prices.
- **Equipment shops**: changes the materials used by weapons, armor, and instruments sold in equipment shops, and recalculates their material-dependent derived values.

### Scene transitions

Enable **Scene transitions** and choose one of the mutually exclusive modes:

- **Local**: shuffles compatible room destinations within the same land. Scene files are grouped by their land prefix, including scenes stored under both `INFO` and `MAPINFO`.
- **Global with return**: shuffles compatible transitions across lands while keeping the paired route back to the source scene.
- **Global extreme**: permutes compatible transitions across the game, including world-map exits and special destinations where possible. It does not preserve a return route.

### Disc-image validation

Before extraction, RandLom checks for the North American game ID `SLUS_010.13` or Japanese ID `SLPS_021.70`. An image that does not contain either ID is rejected. The Japanese ID is recognized, but randomizer behavior has **not been verified against the Japanese release**.

## Create a modified image

1. Start RandLom and choose the interface language from **Language** if needed.
2. Select a Legend of Mana PlayStation 1 disc image. The file picker accepts `.cue`, `.bin`, `.iso`, `.img`, `.ccd`, `.chd`, `.mdf`, `.mds`, `.pbp`, `.toc`, and `.cbn` files. For multi-track discs, select the CUE sheet so the tracks are available to the extractor.
3. Optionally enter a numeric seed. If omitted, RandLom generates one and displays it.
4. Enable the randomization sections and individual options you want. Select at most one scene-transition mode.
5. Click **Generate**. RandLom validates the game ID before proceeding.
6. If `mkpsxiso` is not installed beside the application, approve its download. RandLom downloads the latest GitHub release archive matching the current operating system and, when available, architecture. This download requires an internet connection.
7. If you did not enter a seed, RandLom creates one and displays it. Review the seed in the generation confirmation dialog and accept to continue.
8. RandLom extracts the disc files and applies the selected changes.
9. Choose an output folder. RandLom builds `legend_of_mana.bin` and `legend_of_mana.cue` in that folder.
10. When the build succeeds, you are ready to play.

Keep both the BIN and CUE files together when using the generated image. If generation is cancelled after extraction but before the build finishes, the temporary extraction may remain in the application directory.

## Requirements and compatibility

### Run from source

- Python **3.10 or newer**.
- PyQt6 **6.7 or newer** (`PyQt6>=6.7` in the project dependencies).
- Internet access the first time `mkpsxiso` must be downloaded.
- A supported operating system: Windows, Linux, or macOS. The application selects an `mkpsxiso` release asset for the current platform and architecture; availability depends on the assets published by the upstream project.

Set up a virtual environment and install the dependency:

```bash
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install "PyQt6>=6.7"
python main.py
```

On Linux or macOS:

```bash
source .venv/bin/activate
python -m pip install "PyQt6>=6.7"
python main.py
```

### Prebuilt releases

GitHub Actions builds the application with Python **3.12** for:

- Windows x64 (`RandLom-windows-x64.zip`)
- Linux x64 (`RandLom-linux-x64.tar.gz`)
- macOS ARM64 (`RandLom-macos-arm64.zip`)

The file picker offers common PlayStation image extensions, but actual support depends on whether the selected format is readable by the bundled `dumpsxiso` version. CUE sheets and raw BIN/2352-sector images are the recommended input formats.

## Dependencies

- [Python](https://www.python.org/) 3.10+ when running from source.
- [PyQt6](https://pypi.org/project/PyQt6/) 6.7+ for the desktop interface.
- [mkpsxiso](https://github.com/Lameguy64/mkpsxiso) for extracting and rebuilding PlayStation images. RandLom downloads the latest compatible upstream release archive on demand; its version is not pinned by this project.

## Releases

Download a package from the repository's [GitHub Releases](https://github.com/jupmorenor/randLom/releases) page. The release workflow publishes the Windows, Linux, and macOS artifacts listed above.

## Acknowledgments

Special thanks to [Celophi](https://github.com/celophi), author of [lom-decomp](https://github.com/celophi/lom-decomp). Without this project, developing RandLom would have taken much longer. Its documentation and research have been invaluable to understanding Legend of Mana's files and implementing the randomizers.
