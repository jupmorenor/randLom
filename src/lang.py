"""Interface translations and the currently selected language."""

LANGUAGES = {
    "en": {
        "window_title": "RandLom - A Legend of Mana randomizer",
        "language_menu": "Language",
        "english": "English",
        "spanish": "Spanish",
        "file_placeholder": "Select a file…",
        "browse_file": "Browse for file…",
        "seed_button": "Add seed",
        "seed_automatic": "Seed: automatic",
        "seed_used": "Seed used: {seed}",
        "randomize_objects": "Randomize items",
        "object_types": "Item types",
        "chests": "Chests",
        "item_drops": "Item drops",
        "equipment_drops": "Equipment drops",
        "randomize_shops": "Item shops",
        "shop_types": "Shop types",
        "normal_shops": "Normal item shops",
        "equipment_shops": "Equipment shops",
        "scene_changes": "Scene transitions",
        "scene_change_mode": "Transition mode",
        "scene_local": "Local",
        "scene_global_return": "Global with return",
        "scene_global_extreme": "Global extreme",
        "generate_button": "Generate",
        "status_ready": "Ready",
        "file_dialog_title": "Select a disc image",
        "disc_image_filter": "PlayStation 1 disc images (*.cue *.bin *.iso *.img *.ccd *.chd *.mdf *.mds *.pbp *.toc *.cbn)",
        "seed_dialog_title": "Add seed",
        "seed_dialog_prompt": "Enter a numeric value:",
        "required_file_title": "Disc image required",
        "required_file_message": "Select a valid PlayStation 1 disc image before generating.",
        "wrong_game_title": "Wrong game",
        "wrong_game_message": "The selected disc image is not a Legend of Mana game.",
        "download_title": "Download mkpsxiso",
        "download_message": "mkpsxiso is not installed. Would you like to download and install it now?",
        "confirm_generation_title": "Confirm generation",
        "confirm_generation_message": "Continue with generation using seed {seed}?",
        "status_extracting": "Extracting disc image files…",
        "output_directory_title": "Select a folder to save the image",
        "status_building": "Building the new disc image…",
        "status_build_cancelled": "Build cancelled",
        "status_image_built": "Disc image built",
        "chests_changed": "Chests changed: {count}.",
        "item_drops_changed": "Item drops changed: {count}.",
        "equipment_drops_changed": "Equipment drop materials changed: {count}.",
        "normal_shop_slots_changed": "Normal item shop slots processed: {count}.",
        "equipment_shop_items_changed": "Equipment shop materials and derived values changed: {count}.",
        "scene_transitions_changed": "Scene transitions reassigned ({mode}): {count}.",
        "scene_no_compatible_transitions": " No compatible transitions were found to permute.",
        "generation_completed_title": "Generation complete",
        "generation_completed_message": "The disc image was created at:\n{output}{summary}",
        "generation_failed_status": "Generation failed.",
        "generation_failed_title": "Generation error",
    },
    "es": {
        "window_title": "RandLom - Aleatorizador de Legend of Mana",
        "language_menu": "Idioma",
        "english": "Inglés",
        "spanish": "Español",
        "file_placeholder": "Selecciona un archivo…",
        "browse_file": "Seleccionar archivo…",
        "seed_button": "Agregar semilla",
        "seed_automatic": "Semilla: automática",
        "seed_used": "Semilla usada: {seed}",
        "randomize_objects": "Aleatorizar objetos",
        "object_types": "Tipos de objetos",
        "chests": "Cofres",
        "item_drops": "Botines de objetos",
        "equipment_drops": "Botines de equipamento",
        "randomize_shops": "Tiendas de objetos",
        "shop_types": "Tipos de tienda",
        "normal_shops": "Tiendas de objetos normales",
        "equipment_shops": "Tiendas de equipamento",
        "scene_changes": "Cambio entre escenas",
        "scene_change_mode": "Modo de cambio",
        "scene_local": "Local",
        "scene_global_return": "Global con retorno",
        "scene_global_extreme": "Global extremo",
        "generate_button": "Generar",
        "status_ready": "Listo",
        "file_dialog_title": "Seleccionar imagen de disco",
        "disc_image_filter": "Imágenes de PlayStation 1 (*.cue *.bin *.iso *.img *.ccd *.chd *.mdf *.mds *.pbp *.toc *.cbn)",
        "seed_dialog_title": "Agregar semilla",
        "seed_dialog_prompt": "Introduce un valor numérico:",
        "required_file_title": "Archivo requerido",
        "required_file_message": "Selecciona una imagen de disco de PlayStation 1 válida antes de generar.",
        "wrong_game_title": "Juego incorrecto",
        "wrong_game_message": "La imagen de disco seleccionada no corresponde a Legend of Mana.",
        "download_title": "Descargar mkpsxiso",
        "download_message": "mkpsxiso no está instalado. ¿Deseas descargarlo e instalarlo ahora?",
        "confirm_generation_title": "Confirmar generación",
        "confirm_generation_message": "¿Deseas continuar con la generación usando la semilla {seed}?",
        "status_extracting": "Extrayendo los archivos de la imagen…",
        "output_directory_title": "Seleccionar carpeta para guardar la imagen",
        "status_building": "Construyendo la nueva imagen de disco…",
        "status_build_cancelled": "Construcción cancelada",
        "status_image_built": "Imagen de disco construida",
        "chests_changed": "Cofres cambiados: {count}.",
        "item_drops_changed": "Botines de objetos cambiados: {count}.",
        "equipment_drops_changed": "Materiales de botines de equipamento cambiados: {count}.",
        "normal_shop_slots_changed": "Slots de tiendas de objetos normales procesados: {count}.",
        "equipment_shop_items_changed": "Materiales y valores derivados de equipamento en tiendas cambiados: {count}.",
        "scene_transitions_changed": "Transiciones reasignadas ({mode}): {count}.",
        "scene_no_compatible_transitions": " No se encontraron transiciones compatibles para permutar.",
        "generation_completed_title": "Generación completada",
        "generation_completed_message": "La imagen de disco se creó en:\n{output}{summary}",
        "generation_failed_status": "No se pudo completar la generación.",
        "generation_failed_title": "Error al generar",
    },
}

_selected_language = "es"


def set_language(language_code: str) -> None:
    """Set the active interface language."""
    global _selected_language
    if language_code not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language_code}")
    _selected_language = language_code


def get_text(field_name: str) -> str:
    """Return a translated interface string for the active language."""
    return LANGUAGES[_selected_language][field_name]


def get_language() -> str:
    """Return the active language code."""
    return _selected_language
