"""Application GUI."""

import random
import shutil
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QApplication,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QRadioButton,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core import (
    randomize_item_drops,
    randomize_equipment_drop_materials,
    randomize_chests,
    randomize_chests_and_item_drops,
    randomize_local_scene_transitions,
    randomize_local_scene_transitions_with_return,
    randomize_global_scene_transitions_with_return,
    randomize_extreme_global_scene_transitions,
    randomize_equipment_shop_materials,
    randomize_normal_shop_items,
    randomize_artifact_event_rewards,
    randomize_essence_levels,
    modify_field_overlay,
    build_disc_image,
    extract_disc_image,
    is_legend_of_mana_disc,
)
from src.mkpsxiso import ensure_mkpsxiso, mkpsxiso_is_installed
from src.lang import get_language, get_text, set_language

PS1_IMAGE_EXTENSIONS = {
    ".cue", ".bin", ".img"
}


class _WaitingSpinner(QWidget):
    """Paint a small animated waiting spinner without external dependencies."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    def start(self) -> None:
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt event name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.rect().center())
        painter.rotate(self._angle)
        center_color = self.palette().color(self.foregroundRole())
        for spoke in range(12):
            opacity = 0.18 + 0.82 * (spoke + 1) / 12
            color = QColor(center_color)
            color.setAlphaF(opacity)
            pen = QPen(color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(0, -15, 0, -21)
            painter.rotate(30)


class _GenerationProgressDialog(QDialog):
    """Modal, indeterminate progress dialog for extraction and image building."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(get_text("generation_in_progress"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setFixedSize(300, 140)

        self.spinner = _WaitingSpinner(self)
        self.message = QLabel(self)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addStretch()

    def set_message(self, message: str) -> None:
        self.message.setText(message)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt event name
        super().showEvent(event)
        self.spinner.start()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt event name
        self.spinner.stop()
        super().closeEvent(event)

    def reject(self) -> None:
        """Keep the user from dismissing the dialog while work is running."""


def application_root() -> Path:
    """Return the application directory, including in a frozen distribution."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def application_asset_path(relative_path: str) -> Path:
    """Return an asset path in development and PyInstaller builds."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / relative_path


def application_icon_path() -> Path:
    """Select the native Windows icon or the PNG icon on other platforms."""
    filename = "LoM_Chest_Isolated.ico" if sys.platform == "win32" else "LoM_Chest.png"
    return application_asset_path(f"src/assets/{filename}")


class _ExtractionWorker(QThread):
    succeeded = pyqtSignal(str, int, int, int, int, int, int, int, int, int, bool)
    failed = pyqtSignal(str)

    def __init__(
        self,
        image_path: Path,
        seed: int,
        randomize_chests_enabled: bool,
        randomize_item_drops_enabled: bool,
        randomize_equipment_drops_enabled: bool,
        randomize_normal_shop_items_enabled: bool,
        randomize_equipment_shop_items_enabled: bool,
        randomize_artifacts_enabled: bool,
        randomize_land_levels_enabled: bool,
        randomize_essence_levels_enabled: bool,
        autorun_enabled: bool,
        scene_transition_mode: str | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.image_path = image_path
        self.seed = seed
        self.randomize_chests_enabled = randomize_chests_enabled
        self.randomize_item_drops_enabled = randomize_item_drops_enabled
        self.randomize_equipment_drops_enabled = (
            randomize_equipment_drops_enabled
        )
        self.randomize_normal_shop_items_enabled = (
            randomize_normal_shop_items_enabled
        )
        self.randomize_equipment_shop_items_enabled = (
            randomize_equipment_shop_items_enabled
        )
        self.randomize_artifacts_enabled = randomize_artifacts_enabled
        self.randomize_land_levels_enabled = randomize_land_levels_enabled
        self.randomize_essence_levels_enabled = randomize_essence_levels_enabled
        self.autorun_enabled = autorun_enabled
        self.scene_transition_mode = scene_transition_mode

    def run(self) -> None:
        try:
            root = application_root()
            ensure_mkpsxiso(root)
            extracted_directory = extract_disc_image(self.image_path, root)
            chests_changed = 0
            item_drops_changed = 0
            equipment_drops_changed = 0
            normal_shop_slots_changed = 0
            equipment_shop_items_changed = 0
            scene_transitions_changed = 0
            artifacts_changed = 0
            land_level_entries_changed = 0
            essence_level_entries_changed = 0
            autorun_changed = False
            if self.randomize_chests_enabled and self.randomize_item_drops_enabled:
                chests_changed, item_drops_changed = randomize_chests_and_item_drops(
                    extracted_directory, self.seed
                )
            elif self.randomize_chests_enabled:
                chests_changed = randomize_chests(
                    extracted_directory, self.seed
                )
            elif self.randomize_item_drops_enabled:
                item_drops_changed = randomize_item_drops(
                    extracted_directory, self.seed
                )
            if self.randomize_equipment_drops_enabled:
                equipment_drops_changed = randomize_equipment_drop_materials(
                    extracted_directory, self.seed
                )
            if self.randomize_normal_shop_items_enabled:
                normal_shop_slots_changed = randomize_normal_shop_items(
                    extracted_directory, self.seed
                )
            if self.randomize_equipment_shop_items_enabled:
                equipment_shop_items_changed = randomize_equipment_shop_materials(
                    extracted_directory, self.seed
                )
            if self.scene_transition_mode == "local":
                scene_transitions_changed = randomize_local_scene_transitions(
                    extracted_directory, self.seed
                )
            elif self.scene_transition_mode == "local_return":
                scene_transitions_changed = (
                    randomize_local_scene_transitions_with_return(
                        extracted_directory, self.seed
                    )
                )
            elif self.scene_transition_mode == "global_return":
                scene_transitions_changed = (
                    randomize_global_scene_transitions_with_return(
                        extracted_directory, self.seed
                    )
                )
            elif self.scene_transition_mode == "global_extreme":
                scene_transitions_changed = (
                    randomize_extreme_global_scene_transitions(
                        extracted_directory, self.seed
                    )
                )
            artifact_field_data = None
            if self.randomize_artifacts_enabled:
                artifacts_changed, artifact_field_data = randomize_artifact_event_rewards(
                    extracted_directory, self.seed
                )
            if self.randomize_essence_levels_enabled:
                essence_level_entries_changed = randomize_essence_levels(
                    extracted_directory, self.seed
                )
            if (
                self.randomize_land_levels_enabled
                or self.autorun_enabled
                or artifact_field_data is not None
            ):
                (
                    land_level_entries_changed,
                    autorun_changed,
                ) = modify_field_overlay(
                    extracted_directory,
                    seed=self.seed if self.randomize_land_levels_enabled else None,
                    autorun_enabled=self.autorun_enabled,
                    decompressed_data=artifact_field_data,
                )
            self.succeeded.emit(
                str(extracted_directory), chests_changed, item_drops_changed,
                equipment_drops_changed, normal_shop_slots_changed,
                equipment_shop_items_changed, scene_transitions_changed,
                artifacts_changed,
                land_level_entries_changed,
                essence_level_entries_changed,
                autorun_changed,
            )
        except Exception as error:
            self.failed.emit(str(error))


class _BuildWorker(QThread):
    succeeded = pyqtSignal(str, str)
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
            output_image = build_disc_image(
                self.extracted_directory,
                self.output_directory,
                application_root(),
            )
            cleanup_error = ""
            app_root = application_root().resolve()
            expected_directory = (app_root / "legend_of_mana").resolve()
            extracted_directory = self.extracted_directory.resolve()
            if extracted_directory == expected_directory and expected_directory.is_dir():
                try:
                    pass #shutil.rmtree(expected_directory)
                except OSError:
                    cleanup_error = str(expected_directory)
            elif extracted_directory.exists():
                cleanup_error = str(extracted_directory)
            self.succeeded.emit(str(output_image), cleanup_error)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    """Main window with a file selector and numeric seed input."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(get_text("window_title"))
        self.setWindowIcon(QIcon(str(application_icon_path())))
        QApplication.setWindowIcon(self.windowIcon())
        self.resize(800, 600)
        self.seed: int | None = None
        self._extraction_worker: _ExtractionWorker | None = None
        self._build_worker: _BuildWorker | None = None
        self._progress_dialog: _GenerationProgressDialog | None = None
        self._option_help_buttons: list[tuple[QToolButton, str]] = []
        self.language_toolbar = QToolBar()
        self.language_toolbar.setMovable(False)
        self.addToolBar(self.language_toolbar)
        self.language_button = QToolButton()
        self.language_button.setFixedWidth(100)
        self.language_button.setText(get_text("language_menu"))
        self.language_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.language_menu = QMenu(self.language_button)
        self.language_button.setMenu(self.language_menu)
        self.language_action_group = QActionGroup(self)
        self.language_action_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for language_code, label_key in (("en", "english"), ("es", "spanish")):
            action = QAction(get_text(label_key), self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked=False, code=language_code: self._select_language(code)
            )
            self.language_action_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[language_code] = action
        self.language_actions[get_language()].setChecked(True)
        self.language_toolbar.addWidget(self.language_button)

        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText(get_text("file_placeholder"))
        self.file_path.setReadOnly(True)

        self.browse_button = QPushButton(get_text("browse_file"))
        self.browse_button.clicked.connect(self._select_file)

        file_layout = QHBoxLayout()
        file_layout.addWidget(self.file_path)
        file_layout.addWidget(self.browse_button)

        self.seed_button = QPushButton(get_text("seed_button"))
        self.seed_button.clicked.connect(self._add_seed)
        self.seed_label = QLabel(get_text("seed_automatic"))
        self.new_seed_button = QPushButton(get_text("new_seed_button"))
        self.new_seed_button.setEnabled(False)
        self.new_seed_button.clicked.connect(self._generate_new_seed)
        seed_layout = QHBoxLayout()
        seed_layout.addWidget(self.seed_button)
        seed_layout.addWidget(self.seed_label)
        seed_layout.addStretch()
        seed_layout.addWidget(self.new_seed_button)

        self.autorun_checkbox = QCheckBox(get_text("autorun"))

        self.randomize_objects_checkbox = QCheckBox(get_text("randomize_objects"))
        self.randomize_objects_checkbox.setChecked(False)

        self.object_randomization_group = QGroupBox(get_text("object_types"))
        object_randomization_layout = QVBoxLayout(self.object_randomization_group)
        self.randomize_chests_checkbox = QCheckBox(get_text("chests"))
        self.randomize_item_drops_checkbox = QCheckBox(get_text("item_drops"))
        self.randomize_equipment_drops_checkbox = QCheckBox(
            get_text("equipment_drops")
        )
        object_randomization_layout.addLayout(
            self._help_option_row(self.randomize_chests_checkbox, "help_chests")
        )
        object_randomization_layout.addLayout(
            self._help_option_row(self.randomize_item_drops_checkbox, "help_item_drops")
        )
        object_randomization_layout.addLayout(
            self._help_option_row(
                self.randomize_equipment_drops_checkbox, "help_equipment_drops"
            )
        )
        self.object_randomization_group.setVisible(False)
        self.randomize_objects_checkbox.toggled.connect(
            self.object_randomization_group.setVisible
        )

        self.randomize_shops_checkbox = QCheckBox(get_text("randomize_shops"))
        self.shop_randomization_group = QGroupBox(get_text("shop_types"))
        shop_randomization_layout = QVBoxLayout(self.shop_randomization_group)
        self.randomize_normal_shops_checkbox = QCheckBox(
            get_text("normal_shops")
        )
        self.randomize_equipment_shops_checkbox = QCheckBox(
            get_text("equipment_shops")
        )
        shop_randomization_layout.addLayout(
            self._help_option_row(
                self.randomize_normal_shops_checkbox, "help_normal_shops"
            )
        )
        shop_randomization_layout.addLayout(
            self._help_option_row(
                self.randomize_equipment_shops_checkbox, "help_equipment_shops"
            )
        )
        self.shop_randomization_group.setVisible(False)
        self.randomize_shops_checkbox.toggled.connect(
            self.shop_randomization_group.setVisible
        )

        self.artifacts_and_lands_checkbox = QCheckBox(
            get_text("artifacts_and_lands")
        )
        self.artifacts_and_lands_group = QGroupBox(
            get_text("artifacts_and_lands_options")
        )
        artifacts_and_lands_layout = QVBoxLayout(
            self.artifacts_and_lands_group
        )
        self.randomize_artifacts_checkbox = QCheckBox(
            get_text("randomize_artifacts")
        )
        self.randomize_land_levels_checkbox = QCheckBox(
            get_text("randomize_land_levels")
        )
        self.randomize_essence_levels_checkbox = QCheckBox(
            get_text("randomize_essence_levels")
        )
        artifacts_and_lands_layout.addLayout(
            self._help_option_row(
                self.randomize_artifacts_checkbox, "help_randomize_artifacts"
            )
        )
        artifacts_and_lands_layout.addLayout(
            self._help_option_row(
                self.randomize_land_levels_checkbox, "help_land_levels"
            )
        )
        artifacts_and_lands_layout.addLayout(
            self._help_option_row(
                self.randomize_essence_levels_checkbox, "help_essence_levels"
            )
        )
        self.artifacts_and_lands_group.setVisible(False)
        self.artifacts_and_lands_checkbox.toggled.connect(
            self.artifacts_and_lands_group.setVisible
        )

        self.scene_change_checkbox = QCheckBox(get_text("scene_changes"))
        self.scene_change_group = QGroupBox(get_text("scene_change_mode"))
        scene_change_layout = QVBoxLayout(self.scene_change_group)
        self.scene_change_mode_group = QButtonGroup(self)
        self.scene_change_mode_group.setExclusive(True)
        self.scene_change_local_radio = QRadioButton(get_text("scene_local"))
        self.scene_change_local_return_radio = QRadioButton(
            get_text("scene_local_return")
        )
        self.scene_change_global_return_radio = QRadioButton(
            get_text("scene_global_return")
        )
        self.scene_change_global_extreme_radio = QRadioButton(
            get_text("scene_global_extreme")
        )
        scene_mode_options = (
            (self.scene_change_local_radio, "help_scene_local"),
            (self.scene_change_local_return_radio, "help_scene_local_return"),
            (self.scene_change_global_return_radio, "help_scene_global_return"),
            (self.scene_change_global_extreme_radio, "help_scene_global_extreme"),
        )
        for radio_button, help_key in scene_mode_options:
            self.scene_change_mode_group.addButton(radio_button)
            scene_change_layout.addLayout(
                self._help_option_row(radio_button, help_key)
            )
        self.scene_change_local_radio.setChecked(True)
        self.scene_change_group.setVisible(False)
        self.scene_change_checkbox.toggled.connect(
            self.scene_change_group.setVisible
        )

        self.generate_button = QPushButton(get_text("generate_button"))
        self.generate_button.clicked.connect(self.generate)

        layout = QVBoxLayout()
        layout.addLayout(file_layout)
        layout.addLayout(seed_layout)
        layout.addLayout(self._help_option_row(self.autorun_checkbox, "help_autorun"))
        layout.addWidget(self.randomize_objects_checkbox)
        layout.addWidget(self.object_randomization_group)
        layout.addWidget(self.randomize_shops_checkbox)
        layout.addWidget(self.shop_randomization_group)
        layout.addWidget(self.artifacts_and_lands_checkbox)
        layout.addWidget(self.artifacts_and_lands_group)
        layout.addWidget(self.scene_change_checkbox)
        layout.addWidget(self.scene_change_group)
        layout.addWidget(self.generate_button)
        layout.addStretch()

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)
        self._status_key = "status_ready"
        self.statusBar().showMessage(get_text(self._status_key))

    def _help_option_row(
        self, option: QWidget, tooltip_key: str
    ) -> QHBoxLayout:
        """Place a small question-mark tooltip button beside an option."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(option)

        help_button = QToolButton()
        help_button.setText("?")
        help_button.setFixedSize(18, 18)
        help_button.setAutoRaise(True)
        help_button.setCursor(Qt.CursorShape.WhatsThisCursor)
        help_button.setToolTip(get_text(tooltip_key))
        help_button.setStyleSheet(
            "QToolButton { border: 1px solid palette(mid); border-radius: 9px; "
            "font-weight: bold; padding: 0px; }"
        )
        row.addWidget(help_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self._option_help_buttons.append((help_button, tooltip_key))
        return row

    def _select_language(self, language_code: str) -> None:
        set_language(language_code)
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """Refresh visible interface text after a language change."""
        self.setWindowTitle(get_text("window_title"))
        self.language_button.setText(get_text("language_menu"))
        self.language_actions["en"].setText(get_text("english"))
        self.language_actions["es"].setText(get_text("spanish"))
        self.language_actions[get_language()].setChecked(True)

        self.file_path.setPlaceholderText(get_text("file_placeholder"))
        self.browse_button.setText(get_text("browse_file"))
        self.seed_button.setText(get_text("seed_button"))
        self.new_seed_button.setText(get_text("new_seed_button"))
        self.seed_label.setText(
            get_text("seed_automatic")
            if self.seed is None
            else get_text("seed_used").format(seed=self.seed)
        )
        self.autorun_checkbox.setText(get_text("autorun"))
        self.randomize_objects_checkbox.setText(get_text("randomize_objects"))
        self.object_randomization_group.setTitle(get_text("object_types"))
        self.randomize_chests_checkbox.setText(get_text("chests"))
        self.randomize_item_drops_checkbox.setText(get_text("item_drops"))
        self.randomize_equipment_drops_checkbox.setText(get_text("equipment_drops"))
        self.randomize_shops_checkbox.setText(get_text("randomize_shops"))
        self.shop_randomization_group.setTitle(get_text("shop_types"))
        self.randomize_normal_shops_checkbox.setText(get_text("normal_shops"))
        self.randomize_equipment_shops_checkbox.setText(get_text("equipment_shops"))
        self.artifacts_and_lands_checkbox.setText(get_text("artifacts_and_lands"))
        self.artifacts_and_lands_group.setTitle(
            get_text("artifacts_and_lands_options")
        )
        self.randomize_artifacts_checkbox.setText(get_text("randomize_artifacts"))
        self.randomize_land_levels_checkbox.setText(get_text("randomize_land_levels"))
        self.randomize_essence_levels_checkbox.setText(
            get_text("randomize_essence_levels")
        )
        self.scene_change_checkbox.setText(get_text("scene_changes"))
        self.scene_change_group.setTitle(get_text("scene_change_mode"))
        self.scene_change_local_radio.setText(get_text("scene_local"))
        self.scene_change_local_return_radio.setText(get_text("scene_local_return"))
        self.scene_change_global_return_radio.setText(
            get_text("scene_global_return")
        )
        self.scene_change_global_extreme_radio.setText(
            get_text("scene_global_extreme")
        )
        for help_button, tooltip_key in self._option_help_buttons:
            help_button.setToolTip(get_text(tooltip_key))
        self.generate_button.setText(get_text("generate_button"))
        self.statusBar().showMessage(get_text(self._status_key))

    def _show_status(self, field_name: str, timeout: int = 0) -> None:
        self._status_key = field_name
        self.statusBar().showMessage(get_text(field_name), timeout)

    def _show_generation_progress(self, message_key: str) -> None:
        if self._progress_dialog is None:
            self._progress_dialog = _GenerationProgressDialog(self)
        self._progress_dialog.setWindowTitle(get_text("generation_in_progress"))
        self._progress_dialog.set_message(get_text(message_key))
        self._progress_dialog.open()
        self._progress_dialog.raise_()

    def _close_generation_progress(self) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    def _select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            get_text("file_dialog_title"),
            "",
            get_text("disc_image_filter"),
        )
        if file_path:
            self.file_path.setText(file_path)

    def _add_seed(self) -> None:
        value, accepted = QInputDialog.getInt(
            self,
            get_text("seed_dialog_title"),
            get_text("seed_dialog_prompt"),
            self.seed if self.seed is not None else 0,
        )
        if accepted:
            self.seed = value
            random.seed(self.seed)
            self._update_seed_display()

    def _update_seed_display(self) -> None:
        self.seed_label.setText(
            get_text("seed_automatic")
            if self.seed is None
            else get_text("seed_used").format(seed=self.seed)
        )
        self.new_seed_button.setEnabled(self.seed is not None)

    def _generate_new_seed(self) -> None:
        self.seed = random.randint(0, 2**32 - 1)
        random.seed(self.seed)
        self._update_seed_display()

    def generate(self) -> None:
        # 1. Check that a disc image has been selected.
        selected_file = Path(self.file_path.text())
        if not selected_file.is_file() or selected_file.suffix.lower() not in PS1_IMAGE_EXTENSIONS:
            QMessageBox.warning(
                self,
                get_text("required_file_title"),
                get_text("required_file_message"),
            )
            return

        # Validate the game's boot identifier before downloading tools or extracting files.
        if not is_legend_of_mana_disc(selected_file):
            QMessageBox.warning(
                self,
                get_text("wrong_game_title"),
                get_text("wrong_game_message"),
            )
            return

        # 2. Confirm the download if mkpsxiso is not installed yet.
        if not mkpsxiso_is_installed(application_root()):
            download_confirmation = QMessageBox.question(
                self,
                get_text("download_title"),
                get_text("download_message"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if download_confirmation != QMessageBox.StandardButton.Yes:
                return

        # 3. Generate and display a seed if none was entered.
        if self.seed is None:
            self.seed = random.randint(0, 2**32 - 1)
            random.seed(self.seed)
            self._update_seed_display()

        # 4. Confirm before starting extraction.
        confirmation = QMessageBox.question(
            self,
            get_text("confirm_generation_title"),
            get_text("confirm_generation_message").format(seed=self.seed),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        # 5. Always extract to the project's legend_of_mana directory.
        self._scene_transition_mode_requested = None
        if self.scene_change_checkbox.isChecked():
            if self.scene_change_local_radio.isChecked():
                self._scene_transition_mode_requested = "local"
            elif self.scene_change_local_return_radio.isChecked():
                self._scene_transition_mode_requested = "local_return"
            elif self.scene_change_global_return_radio.isChecked():
                self._scene_transition_mode_requested = "global_return"
            elif self.scene_change_global_extreme_radio.isChecked():
                self._scene_transition_mode_requested = "global_extreme"
        self.generate_button.setEnabled(False)
        self._show_status("status_extracting")
        self._show_generation_progress("status_extracting")
        self._extraction_worker = _ExtractionWorker(
            selected_file,
            self.seed,
            self.randomize_objects_checkbox.isChecked()
            and self.randomize_chests_checkbox.isChecked(),
            self.randomize_objects_checkbox.isChecked()
            and self.randomize_item_drops_checkbox.isChecked(),
            self.randomize_objects_checkbox.isChecked()
            and self.randomize_equipment_drops_checkbox.isChecked(),
            self.randomize_shops_checkbox.isChecked()
            and self.randomize_normal_shops_checkbox.isChecked(),
            self.randomize_shops_checkbox.isChecked()
            and self.randomize_equipment_shops_checkbox.isChecked(),
            self.artifacts_and_lands_checkbox.isChecked()
            and self.randomize_artifacts_checkbox.isChecked(),
            self.artifacts_and_lands_checkbox.isChecked()
            and self.randomize_land_levels_checkbox.isChecked(),
            self.artifacts_and_lands_checkbox.isChecked()
            and self.randomize_essence_levels_checkbox.isChecked(),
            self.autorun_checkbox.isChecked(),
            self._scene_transition_mode_requested,
            self,
        )
        self._extraction_worker.succeeded.connect(self._extraction_succeeded)
        self._extraction_worker.failed.connect(self._generation_failed)
        self._extraction_worker.start()

    def _extraction_succeeded(
        self,
        extracted_directory: str,
        chests_changed: int,
        item_drops_changed: int,
        equipment_drops_changed: int,
        normal_shop_slots_changed: int,
        equipment_shop_items_changed: int,
        scene_transitions_changed: int,
        artifacts_changed: int,
        land_level_entries_changed: int,
        essence_level_entries_changed: int,
        autorun_changed: bool,
    ) -> None:
        self._close_generation_progress()
        self._chests_changed = chests_changed
        self._item_drops_changed = item_drops_changed
        self._equipment_drops_changed = equipment_drops_changed
        self._normal_shop_slots_changed = normal_shop_slots_changed
        self._equipment_shop_items_changed = equipment_shop_items_changed
        self._scene_transitions_changed = scene_transitions_changed
        self._artifacts_changed = artifacts_changed
        self._land_level_entries_changed = land_level_entries_changed
        self._essence_level_entries_changed = essence_level_entries_changed
        self._autorun_changed = autorun_changed
        # 6. Ask for the output directory immediately before building the image.
        output_directory = QFileDialog.getExistingDirectory(
            self,
            get_text("output_directory_title"),
            str(application_root()),
        )
        if not output_directory:
            self.generate_button.setEnabled(True)
            self._show_status("status_build_cancelled", 10000)
            return

        extracted_path = Path(extracted_directory).resolve()
        output_path = Path(output_directory).resolve()
        if output_path == extracted_path or extracted_path in output_path.parents:
            self.generate_button.setEnabled(True)
            QMessageBox.warning(
                self,
                get_text("output_directory_title"),
                get_text("output_inside_extracted_directory"),
            )
            return

        self._show_status("status_building")
        self._show_generation_progress("status_building")
        self._build_worker = _BuildWorker(
            Path(extracted_directory),
            Path(output_directory),
            self,
        )
        self._build_worker.succeeded.connect(self._generation_succeeded)
        self._build_worker.failed.connect(self._generation_failed)
        self._build_worker.start()

    def _generation_succeeded(
        self, output_image: str, cleanup_error: str
    ) -> None:
        self._close_generation_progress()
        # Report completion and show where the image was saved.
        self.generate_button.setEnabled(True)
        self._show_status("status_image_built", 10000)
        object_summary = ""
        if getattr(self, "_chests_changed", 0):
            object_summary += "\n" + get_text("chests_changed").format(
                count=self._chests_changed
            )
        if getattr(self, "_item_drops_changed", 0):
            object_summary += "\n" + get_text("item_drops_changed").format(
                count=self._item_drops_changed
            )
        if getattr(self, "_equipment_drops_changed", 0):
            object_summary += "\n" + get_text("equipment_drops_changed").format(
                count=self._equipment_drops_changed
            )
        if getattr(self, "_normal_shop_slots_changed", 0):
            object_summary += "\n" + get_text("normal_shop_slots_changed").format(
                count=self._normal_shop_slots_changed
            )
        if getattr(self, "_equipment_shop_items_changed", 0):
            object_summary += "\n" + get_text(
                "equipment_shop_items_changed"
            ).format(
                count=self._equipment_shop_items_changed
            )
        if getattr(self, "_artifacts_changed", 0):
            object_summary += "\n" + get_text("artifacts_changed").format(
                count=self._artifacts_changed
            )
        if getattr(self, "_land_level_entries_changed", 0):
            object_summary += "\n" + get_text("land_level_entries_changed").format(
                count=self._land_level_entries_changed
            )
        if getattr(self, "_essence_level_entries_changed", 0):
            object_summary += "\n" + get_text("essence_level_entries_changed").format(
                count=self._essence_level_entries_changed
            )
        if getattr(self, "_autorun_changed", False):
            object_summary += "\n" + get_text("autorun_enabled")
        if getattr(self, "_scene_transition_mode_requested", None):
            mode_label = {
                "local": get_text("scene_local"),
                "local_return": get_text("scene_local_return"),
                "global_return": get_text("scene_global_return"),
                "global_extreme": get_text("scene_global_extreme"),
            }.get(self._scene_transition_mode_requested, self._scene_transition_mode_requested)
            object_summary += "\n" + get_text("scene_transitions_changed").format(
                mode=mode_label,
                count=self._scene_transitions_changed,
            )
            if not self._scene_transitions_changed:
                object_summary += get_text("scene_no_compatible_transitions")
        QMessageBox.information(
            self,
            get_text("generation_completed_title"),
            get_text("generation_completed_message").format(
                output=output_image,
                summary=object_summary,
            ),
        )
        if cleanup_error:
            QMessageBox.warning(
                self,
                get_text("cleanup_failed_title"),
                get_text("cleanup_failed_message").format(
                    directory=cleanup_error
                ),
            )

    def _generation_failed(self, message: str) -> None:
        self._close_generation_progress()
        self.generate_button.setEnabled(True)
        self._show_status("generation_failed_status", 10000)
        QMessageBox.critical(self, get_text("generation_failed_title"), message)
