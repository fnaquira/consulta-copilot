# -*- coding: utf-8 -*-
"""
ConfigDialog — Configuración del proveedor de IA y audio.
"""
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTabWidget, QWidget,
    QFormLayout, QVBoxLayout, QHBoxLayout,
    QLineEdit, QComboBox, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from src.utils.config import TranscriberConfig

# Archivo donde se persisten los ajustes de IA (fuera de env vars)
_SETTINGS_PATH = Path.home() / ".consulta_copilot" / "ai_settings.json"


def load_ai_settings() -> dict:
    """Lee ajustes de IA desde el archivo JSON, con defaults."""
    defaults = {
        "ai_provider": "openai",
        "ai_model": "gpt-4o-mini",
        "openai_api_key": "",
        "azure_api_key": "",
        "azure_endpoint": "",
        "azure_deployment": "",
        "azure_api_version": "2024-02-01",
        "ollama_host": "http://localhost:11434",
        # Transcripción
        "transcription_provider": "deepgram",
        "deepgram_api_key": "",
        "deepgram_model": "nova-2",
    }
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            defaults.update(data)
        except Exception:
            pass
    return defaults


def save_ai_settings(settings: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------
# Worker para probar conexión en background
# ------------------------------------------------------------------

class _TestConnectionWorker(QThread):
    result = Signal(bool, str)   # (ok, message)

    def __init__(self, settings: dict):
        super().__init__()
        self._settings = settings

    def run(self):
        try:
            import openai
            s = self._settings
            provider = s.get("ai_provider", "openai")

            if provider == "openai":
                client = openai.OpenAI(api_key=s.get("openai_api_key", ""))
            elif provider == "azure":
                client = openai.AzureOpenAI(
                    api_key=s.get("azure_api_key", ""),
                    azure_endpoint=s.get("azure_endpoint", ""),
                    api_version=s.get("azure_api_version", "2024-02-01"),
                )
            elif provider == "ollama":
                client = openai.OpenAI(
                    base_url=f"{s.get('ollama_host', 'http://localhost:11434')}/v1",
                    api_key="ollama",
                )
            else:
                self.result.emit(False, f"Provider desconocido: {provider}")
                return

            model = s.get("ai_model", "gpt-4o-mini")
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "di hola"}],
                max_tokens=5,
            )
            reply = resp.choices[0].message.content.strip()
            self.result.emit(True, f"Conectado: {reply}")
        except Exception as exc:
            self.result.emit(False, str(exc))


# ------------------------------------------------------------------
# Diálogo principal
# ------------------------------------------------------------------

class ConfigDialog(QDialog):
    def __init__(self, config: TranscriberConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._test_worker: _TestConnectionWorker | None = None
        self.setWindowTitle("Configuración")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_transcription_tab(), "Transcripción")
        tabs.addTab(self._build_ai_tab(), "Proveedor IA")
        tabs.addTab(self._build_audio_tab(), "Audio")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- Pestaña Transcripción ---
    def _build_transcription_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        self._trans_provider_combo = QComboBox()
        self._trans_provider_combo.addItems(["Deepgram (streaming, recomendado)", "Local (offline)"])
        self._trans_provider_combo.currentIndexChanged.connect(self._on_trans_provider_changed)
        form.addRow("Motor:", self._trans_provider_combo)

        # Deepgram fields
        self._dg_widget = QWidget()
        dg_form = QFormLayout(self._dg_widget)

        self._dg_api_key = QLineEdit()
        self._dg_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._dg_api_key.setPlaceholderText("Tu API key de Deepgram")
        dg_form.addRow("Deepgram API Key:", self._dg_api_key)

        self._dg_model = QComboBox()
        self._dg_model.addItems(["nova-2", "nova-3", "enhanced", "base"])
        dg_form.addRow("Modelo Deepgram:", self._dg_model)

        layout.addLayout(form)
        layout.addWidget(self._dg_widget)

        # Info label
        info = QLabel(
            "Deepgram ofrece transcripción streaming en tiempo real con ~300ms de latencia.\n"
            "Costo: ~$0.0043/minuto (~$0.26/hora).\n"
            "Regístrate en console.deepgram.com para obtener tu API key."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; padding: 8px; font-size: 11px;")
        layout.addWidget(info)

        layout.addStretch()
        return widget

    def _on_trans_provider_changed(self, index: int):
        self._dg_widget.setVisible(index == 0)

    # --- Pestaña IA ---
    def _build_ai_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["OpenAI", "Azure", "Ollama"])
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Proveedor:", self._provider_combo)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("gpt-4o-mini")
        form.addRow("Modelo:", self._model_edit)

        layout.addLayout(form)

        # --- Campos dinámicos por proveedor ---
        self._openai_widget = self._build_openai_fields()
        self._azure_widget = self._build_azure_fields()
        self._ollama_widget = self._build_ollama_fields()

        layout.addWidget(self._openai_widget)
        layout.addWidget(self._azure_widget)
        layout.addWidget(self._ollama_widget)

        # --- Botón probar ---
        test_row = QHBoxLayout()
        self._btn_test = QPushButton("Probar conexión")
        self._btn_test.clicked.connect(self._on_test_connection)
        self._lbl_test = QLabel("")
        self._lbl_test.setWordWrap(True)
        test_row.addWidget(self._btn_test)
        test_row.addWidget(self._lbl_test, 1)
        layout.addLayout(test_row)

        layout.addStretch()
        return widget

    def _build_openai_fields(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._openai_key = QLineEdit()
        self._openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._openai_key.setPlaceholderText("sk-...")
        form.addRow("API Key:", self._openai_key)
        return w

    def _build_azure_fields(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._azure_key = QLineEdit()
        self._azure_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self._azure_key)
        self._azure_endpoint = QLineEdit()
        self._azure_endpoint.setPlaceholderText("https://....openai.azure.com/")
        form.addRow("Endpoint:", self._azure_endpoint)
        self._azure_deployment = QLineEdit()
        self._azure_deployment.setPlaceholderText("nombre del deployment")
        form.addRow("Deployment:", self._azure_deployment)
        self._azure_api_version = QLineEdit()
        self._azure_api_version.setPlaceholderText("2024-02-01")
        form.addRow("API Version:", self._azure_api_version)
        return w

    def _build_ollama_fields(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._ollama_host = QLineEdit()
        self._ollama_host.setPlaceholderText("http://localhost:11434")
        form.addRow("Host:", self._ollama_host)
        return w

    # --- Pestaña Audio ---
    def _build_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()

        # Micrófono
        mic_row = QHBoxLayout()
        self._mic_combo = QComboBox()
        self._mic_combo.setMinimumWidth(300)
        mic_row.addWidget(self._mic_combo, 1)
        btn_refresh = QPushButton("Refrescar")
        btn_refresh.clicked.connect(self._refresh_devices)
        mic_row.addWidget(btn_refresh)
        form.addRow("Micrófono (Psicólogo):", mic_row)

        # Loopback
        self._loopback_combo = QComboBox()
        self._loopback_combo.setMinimumWidth(300)
        form.addRow("Audio Sistema (Paciente):", self._loopback_combo)

        layout.addLayout(form)

        self._lbl_audio_warn = QLabel("")
        self._lbl_audio_warn.setWordWrap(True)
        self._lbl_audio_warn.setStyleSheet("color: #FF9800; padding: 8px;")
        layout.addWidget(self._lbl_audio_warn)

        layout.addStretch()

        self._refresh_devices()
        return widget

    def _refresh_devices(self):
        import queue as _queue
        from src.audio.capture import AudioCapture, AudioConfig
        from src.audio.system_capture import SystemAudioCapture, SystemAudioConfig

        # Micrófono
        self._mic_combo.clear()
        self._mic_combo.addItem("Predeterminado", None)
        try:
            cap = AudioCapture(AudioConfig(), _queue.Queue())
            for d in cap.list_devices():
                self._mic_combo.addItem(f"[{d['index']}] {d['name']}", d["index"])
        except Exception:
            pass

        # Loopback
        self._loopback_combo.clear()
        self._loopback_combo.addItem("Auto-detectar", None)
        try:
            cap = SystemAudioCapture(SystemAudioConfig(), _queue.Queue())
            devs = cap.list_loopback_devices()
            if not devs:
                self._lbl_audio_warn.setText(
                    "No se detectan dispositivos loopback. En macOS instala BlackHole. "
                    "En Windows, activa 'Mezcla estéreo' en configuración de sonido."
                )
            else:
                self._lbl_audio_warn.setText("")
                for d in devs:
                    self._loopback_combo.addItem(f"[{d['index']}] {d['name']}", d["index"])
        except Exception:
            self._lbl_audio_warn.setText("Error al listar dispositivos de sistema.")

    # ------------------------------------------------------------------
    # Lógica
    # ------------------------------------------------------------------

    def _on_provider_changed(self, index: int):
        self._openai_widget.setVisible(index == 0)
        self._azure_widget.setVisible(index == 1)
        self._ollama_widget.setVisible(index == 2)

    def _load_settings(self):
        s = load_ai_settings()

        # Transcripción
        trans_map = {"deepgram": 0, "local": 1}
        trans_idx = trans_map.get(s.get("transcription_provider", "deepgram"), 0)
        self._trans_provider_combo.setCurrentIndex(trans_idx)
        self._dg_api_key.setText(s.get("deepgram_api_key", ""))
        dg_model = s.get("deepgram_model", "nova-2")
        idx_model = self._dg_model.findText(dg_model)
        if idx_model >= 0:
            self._dg_model.setCurrentIndex(idx_model)
        self._on_trans_provider_changed(trans_idx)

        # IA
        provider_map = {"openai": 0, "azure": 1, "ollama": 2}
        idx = provider_map.get(s.get("ai_provider", "openai"), 0)
        self._provider_combo.setCurrentIndex(idx)
        self._model_edit.setText(s.get("ai_model", ""))
        self._openai_key.setText(s.get("openai_api_key", ""))
        self._azure_key.setText(s.get("azure_api_key", ""))
        self._azure_endpoint.setText(s.get("azure_endpoint", ""))
        self._azure_deployment.setText(s.get("azure_deployment", ""))
        self._azure_api_version.setText(s.get("azure_api_version", ""))
        self._ollama_host.setText(s.get("ollama_host", ""))
        self._on_provider_changed(idx)

    def _collect_settings(self) -> dict:
        provider_names = ["openai", "azure", "ollama"]
        provider = provider_names[self._provider_combo.currentIndex()]
        trans_names = ["deepgram", "local"]
        trans_provider = trans_names[self._trans_provider_combo.currentIndex()]
        return {
            # Transcripción
            "transcription_provider": trans_provider,
            "deepgram_api_key": self._dg_api_key.text().strip(),
            "deepgram_model": self._dg_model.currentText(),
            # IA
            "ai_provider": provider,
            "ai_model": self._model_edit.text().strip() or "gpt-4o-mini",
            "openai_api_key": self._openai_key.text().strip(),
            "azure_api_key": self._azure_key.text().strip(),
            "azure_endpoint": self._azure_endpoint.text().strip(),
            "azure_deployment": self._azure_deployment.text().strip(),
            "azure_api_version": self._azure_api_version.text().strip() or "2024-02-01",
            "ollama_host": self._ollama_host.text().strip() or "http://localhost:11434",
        }

    def _on_test_connection(self):
        self._lbl_test.setText("Probando...")
        self._btn_test.setEnabled(False)
        settings = self._collect_settings()
        self._test_worker = _TestConnectionWorker(settings)
        self._test_worker.result.connect(self._on_test_result)
        self._test_worker.start()

    def _on_test_result(self, ok: bool, message: str):
        self._btn_test.setEnabled(True)
        if ok:
            self._lbl_test.setText(f"✅ {message}")
            self._lbl_test.setStyleSheet("color: green;")
        else:
            self._lbl_test.setText(f"❌ {message}")
            self._lbl_test.setStyleSheet("color: red;")

    def _on_accept(self):
        settings = self._collect_settings()
        save_ai_settings(settings)
        # Aplicar transcription settings al config si existe
        if self._config:
            self._config.transcription_provider = settings["transcription_provider"]
            self._config.deepgram_api_key = settings["deepgram_api_key"]
            self._config.deepgram_model = settings["deepgram_model"]
        self.accept()
