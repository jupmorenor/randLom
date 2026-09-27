"""Interfaz gráfica de la aplicación."""

import random
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core import construir_imagen, generar as extraer_imagen
from src.mkpsxiso import ensure_mkpsxiso, mkpsxiso_is_installed

PS1_IMAGE_EXTENSIONS = {
    ".cue", ".bin", ".iso", ".img", ".ccd", ".chd", ".mdf", ".mds", ".pbp", ".toc", ".cbn"
}


def application_root() -> Path:
    """Devuelve la carpeta de la aplicación, también en una distribución congelada."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class _ExtractionWorker(QThread):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_path = image_path

    def run(self) -> None:
        try:
            root = application_root()
            ensure_mkpsxiso(root)
            extracted_directory = extraer_imagen(self.image_path, root)
            self.succeeded.emit(str(extracted_directory))
        except Exception as error:
            self.failed.emit(str(error))


class _BuildWorker(QThread):
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        extracted_directory: Path,
        output_directory: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.extracted_directory = extracted_directory
        self.output_directory = output_directory

    def run(self) -> None:
        try:
            output_image = construir_imagen(
                self.extracted_directory,
                self.output_directory,
                application_root(),
            )
            self.succeeded.emit(str(output_image))
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    """Ventana principal con selector de archivos y semilla numérica."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RandLom - A Legend of Mana randomizer")
        self.resize(800, 600)
        self.semilla: int | None = None
        self._extraction_worker: _ExtractionWorker | None = None
        self._build_worker: _BuildWorker | None = None

        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("Selecciona un archivo…")
        self.file_path.setReadOnly(True)

        browse_button = QPushButton("Seleccionar archivo…")
        browse_button.clicked.connect(self._select_file)

        file_layout = QHBoxLayout()
        file_layout.addWidget(self.file_path)
        file_layout.addWidget(browse_button)

        seed_button = QPushButton("Agregar semilla")
        seed_button.clicked.connect(self._add_seed)
        self.seed_label = QLabel("Semilla: automática")
        seed_layout = QHBoxLayout()
        seed_layout.addWidget(seed_button)
        seed_layout.addWidget(self.seed_label)
        seed_layout.addStretch()

        self.generate_button = QPushButton("Generar")
        self.generate_button.clicked.connect(self.generar)

        layout = QVBoxLayout()
        layout.addLayout(file_layout)
        layout.addLayout(seed_layout)
        layout.addWidget(self.generate_button)
        layout.addStretch()

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)
        self.statusBar().showMessage("Listo")

    def _select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo",
            "",
            "Imágenes de PlayStation 1 (*.cue *.bin *.iso *.img *.ccd *.chd *.mdf *.mds *.pbp *.toc *.cbn)",
        )
        if file_path:
            self.file_path.setText(file_path)

    def _add_seed(self) -> None:
        value, accepted = QInputDialog.getInt(
            self,
            "Agregar semilla",
            "Introduce un valor numérico:",
            self.semilla if self.semilla is not None else 0,
        )
        if accepted:
            self.semilla = value
            random.seed(self.semilla)
            self.seed_label.setText(f"Semilla usada: {self.semilla}")

    def generar(self) -> None:
        # 1. Validar que haya una imagen de disco seleccionada.
        selected_file = Path(self.file_path.text())
        if not selected_file.is_file() or selected_file.suffix.lower() not in PS1_IMAGE_EXTENSIONS:
            QMessageBox.warning(
                self,
                "Archivo requerido",
                "Selecciona una imagen de disco de PlayStation 1 válida antes de generar.",
            )
            return

        # 2. Confirmar la descarga si mkpsxiso todavía no está instalado.
        if not mkpsxiso_is_installed(application_root()):
            download_confirmation = QMessageBox.question(
                self,
                "Descargar mkpsxiso",
                "mkpsxiso no está instalado. ¿Deseas descargarlo e instalarlo ahora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if download_confirmation != QMessageBox.StandardButton.Yes:
                return

        # 3. Crear y mostrar una semilla si no se introdujo una.
        if self.semilla is None:
            self.semilla = random.randint(0, 2**32 - 1)
            random.seed(self.semilla)
            self.seed_label.setText(f"Semilla usada: {self.semilla}")

        # 4. Confirmar antes de iniciar la extracción.
        confirmation = QMessageBox.question(
            self,
            "Confirmar generación",
            f"¿Deseas continuar con la generación usando la semilla {self.semilla}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        # 5. Extraer siempre en la carpeta legend_of_mana del proyecto.
        self.generate_button.setEnabled(False)
        self.statusBar().showMessage("Extrayendo los archivos de la imagen…")
        self._extraction_worker = _ExtractionWorker(selected_file, self)
        self._extraction_worker.succeeded.connect(self._extraction_succeeded)
        self._extraction_worker.failed.connect(self._generation_failed)
        self._extraction_worker.start()

    def _extraction_succeeded(self, extracted_directory: str) -> None:
        # 6. Aquí se añadirán los procesos intermedios pendientes.
        # 7. Pedir la carpeta de salida justo antes de construir la imagen.
        output_directory = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta para guardar la imagen",
            str(application_root()),
        )
        if not output_directory:
            self.generate_button.setEnabled(True)
            self.statusBar().showMessage("Construcción cancelada", 10000)
            return

        self.statusBar().showMessage("Construyendo la nueva imagen de disco…")
        self._build_worker = _BuildWorker(
            Path(extracted_directory),
            Path(output_directory),
            self,
        )
        self._build_worker.succeeded.connect(self._generation_succeeded)
        self._build_worker.failed.connect(self._generation_failed)
        self._build_worker.start()

    def _generation_succeeded(self, output_image: str) -> None:
        # 8. Informar que terminó y mostrar dónde se guardó la imagen.
        self.generate_button.setEnabled(True)
        self.statusBar().showMessage("Imagen de disco construida", 10000)
        QMessageBox.information(
            self,
            "Generación completada",
            f"La imagen de disco se creó en:\n{output_image}",
        )

    def _generation_failed(self, message: str) -> None:
        self.generate_button.setEnabled(True)
        self.statusBar().showMessage("No se pudo completar la generación.", 10000)
        QMessageBox.critical(self, "Error al generar", message)
