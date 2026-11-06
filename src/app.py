"""Application GUI."""

import random
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
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
    modify_field_overlay,
    build_disc_image,
    extract_disc_image,
    is_legend_of_mana_disc,
)
from src.mkpsxiso import ensure_mkpsxiso, mkpsxiso_is_installed
from src.lang import get_language, get_text, set_language

PS1_IMAGE_EXTENSIONS = {
    ".cue", ".bin", ".iso", ".img", ".ccd", ".chd", ".mdf", ".mds", ".pbp", ".toc", ".cbn"
}


def application_root() -> Path:
    """Return the application directory, including in a frozen distribution."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class _ExtractionWorker(QThread):
    succeeded = pyqtSignal(str, int, int, int, int, int, int, int, int, bool)
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
            if self.randomize_artifacts_enabled:
                artifacts_changed = randomize_artifact_event_rewards(
                    extracted_directory, self.seed
                )
            if (
                self.randomize_land_levels_enabled
                or self.autorun_enabled
            ):
                (
                    land_level_entries_changed,
                    autorun_changed,
                ) = modify_field_overlay(
                    extracted_directory,
                    seed=self.seed if self.randomize_land_levels_enabled else None,
                    autorun_enabled=self.autorun_enabled,
                )
            self.succeeded.emit(
                str(extracted_directory), chests_changed, item_drops_changed,
                equipment_drops_changed, normal_shop_slots_changed,
                equipment_shop_items_changed, scene_transitions_changed,
                artifacts_changed,
                land_level_entries_changed,
                autorun_changed,
            )
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
            output_image = build_disc_image(
                self.extracted_directory,
                self.output_directory,
                application_root(),
            )
            self.succeeded.emit(str(output_image))
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    """Main window with a file selector and numeric seed input."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(get_text("window_title"))
        self.resize(800, 600)
        self.seed: int | None = None
        self._extraction_worker: _ExtractionWorker | None = None
        self._build_worker: _BuildWorker | None = None
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
        seed_layout = QHBoxLayout()
        seed_layout.addWidget(self.seed_button)
        seed_layout.addWidget(self.seed_label)
        seed_layout.addStretch()

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
        object_randomization_layout.addWidget(self.randomize_chests_checkbox)
        object_randomization_layout.addWidget(self.randomize_item_drops_checkbox)
        object_randomization_layout.addWidget(self.randomize_equipment_drops_checkbox)
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
        shop_randomization_layout.addWidget(self.randomize_normal_shops_checkbox)
        shop_randomization_layout.addWidget(self.randomize_equipment_shops_checkbox)
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
        artifacts_and_lands_layout.addWidget(self.randomize_artifacts_checkbox)
        artifacts_and_lands_layout.addWidget(self.randomize_land_levels_checkbox)
        artifacts_and_lands_layout.addWidget(self.randomize_essence_levels_checkbox)
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
        for radio_button in (
            self.scene_change_local_radio,
            self.scene_change_local_return_radio,
            self.scene_change_global_return_radio,
            self.scene_change_global_extreme_radio,
        ):
            self.scene_change_mode_group.addButton(radio_button)
            scene_change_layout.addWidget(radio_button)
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
        layout.addWidget(self.autorun_checkbox)
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
        self.generate_button.setText(get_text("generate_button"))
        self.statusBar().showMessage(get_text(self._status_key))

    def _show_status(self, field_name: str, timeout: int = 0) -> None:
        self._status_key = field_name
        self.statusBar().showMessage(get_text(field_name), timeout)

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
            self.seed_label.setText(
                get_text("seed_used").format(seed=self.seed)
            )

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
            self.seed_label.setText(
                get_text("seed_used").format(seed=self.seed)
            )

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
        autorun_changed: bool,
    ) -> None:
        self._chests_changed = chests_changed
        self._item_drops_changed = item_drops_changed
        self._equipment_drops_changed = equipment_drops_changed
        self._normal_shop_slots_changed = normal_shop_slots_changed
        self._equipment_shop_items_changed = equipment_shop_items_changed
        self._scene_transitions_changed = scene_transitions_changed
        self._artifacts_changed = artifacts_changed
        self._land_level_entries_changed = land_level_entries_changed
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
        self._build_worker = _BuildWorker(
            Path(extracted_directory),
            Path(output_directory),
            self,
        )
        self._build_worker.succeeded.connect(self._generation_succeeded)
        self._build_worker.failed.connect(self._generation_failed)
        self._build_worker.start()

    def _generation_succeeded(self, output_image: str) -> None:
        # Keep extracted files temporarily so FIELD.BIN can be inspected.
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

    def _generation_failed(self, message: str) -> None:
        self.generate_button.setEnabled(True)
        self._show_status("generation_failed_status", 10000)
        QMessageBox.critical(self, get_text("generation_failed_title"), message)
