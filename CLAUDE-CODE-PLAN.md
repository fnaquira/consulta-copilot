# CLAUDE.md — Copiloto Psicológico: Plan de Desarrollo para Claude Code

> **REGLA FUNDAMENTAL:** Este plan se ejecuta en fases secuenciales. Al terminar CADA fase, DETENTE completamente. Muestra las instrucciones de verificación al usuario y espera su confirmación explícita ("listo", "ok", "continúa") antes de avanzar a la siguiente fase. **No avances sin aprobación.**

---

## Contexto del Proyecto Existente

El repositorio `fnaquira/consulta-copilot` es una aplicación de escritorio de transcripción en tiempo real. Antes de cualquier cambio, lee y comprende estos archivos:

### Stack actual (NO CAMBIAR sin motivo)
- **UI:** PySide6 (LGPL) — NO customtkinter
- **Transcripción:** faster-whisper (CTranslate2) + silero-vad + sounddevice
- **Config:** pydantic-settings (`TranscriberConfig` en `src/utils/config.py`)
- **Entorno:** uv + Python 3.11
- **Tests:** pytest en `tests/`

### Estructura actual
```
├── main.py                        # Entrada principal
├── requirements.txt
├── CLAUDE.md / PLAN.md / BUILD.md
├── src/
│   ├── audio/
│   │   ├── capture.py             # AudioCapture (sounddevice)
│   │   ├── vad.py                 # VoiceActivityDetector (silero-vad)
│   │   └── vad_worker.py          # VADWorker QThread
│   ├── transcription/
│   │   ├── engine.py              # TranscriptionEngine (faster-whisper)
│   │   └── worker.py              # SlidingWindowWorker QThread
│   ├── ui/
│   │   ├── main_window.py         # Ventana principal actual
│   │   ├── transcript_view.py     # Widget de transcripción
│   │   └── settings_dialog.py     # Diálogo de preferencias
│   └── utils/
│       ├── config.py              # TranscriberConfig (pydantic-settings)
│       └── export.py              # export_to_txt, export_to_srt
└── tests/
    ├── test_audio.py
    ├── test_engine.py
    ├── test_vad.py
    └── test_sliding_window.py
```

### Objetivo de la transformación
Convertir esta app de transcripción en un **copiloto para psicólogos** durante teleconsultas, agregando:
1. Gestión de pacientes y sesiones (SQLite)
2. Configuración de proveedores de IA (OpenAI, Azure, Ollama) para análisis
3. Transcripción dual: micrófono del psicólogo + audio del sistema (loopback del paciente)
4. Panel "Copiloto" con análisis en tiempo real del discurso del paciente
5. Historial y búsqueda de sesiones pasadas

### Principios de desarrollo
- **Incremental:** cada fase produce código que compila y se puede probar
- **Respetar lo existente:** no reescribir lo que ya funciona; extender
- **PySide6 siempre:** toda UI nueva usa PySide6 (QMainWindow, QDialog, etc.)
- **pydantic-settings:** extender `TranscriberConfig`, no crear un sistema de config paralelo
- **Tests:** cada fase incluye tests para lo nuevo

---

## Fase 0: Reconocimiento (NO escribir código)

**Meta:** Entender completamente el código actual antes de tocar nada.

### Tareas
1. Lee TODOS los archivos `.py` del proyecto (main.py, src/**, tests/**)
2. Lee CLAUDE.md, PLAN.md, BUILD.md, BUILD-macos.md, requirements.txt
3. Identifica:
   - Cómo se inicializa la app en `main.py`
   - Qué señales/slots usa `main_window.py`
   - Cómo funciona `TranscriberConfig` (campos, env vars, validación)
   - Cómo `SlidingWindowWorker` emite transcripciones
   - Qué exporta `export.py`
4. Documenta cualquier conflicto con el plan

### CHECKPOINT — Muestra al usuario:
```
DETENTE. Presenta:
1. Resumen de cada módulo existente y su responsabilidad
2. Diagrama de flujo actual: main.py → cómo llega el audio a texto en pantalla
3. Lista de señales Qt existentes relevantes
4. Campos actuales de TranscriberConfig
5. Conflictos o ajustes necesarios al plan original

Pregunta: "He analizado el código. ¿Confirmas que proceda con la Fase 1?
¿Hay algo del código actual que NO deba modificar?"
```

---

## Fase 1: Base de Datos + Extensión de Configuración

**Meta:** Agregar SQLite para pacientes/sesiones y extender la config para soportar proveedores de IA, sin romper nada existente.

### Paso 1.1 — `src/db/manager.py` (NUEVO módulo)

Crea `src/db/__init__.py` y `src/db/manager.py`.

**Esquema SQLite** (archivo en `~/.consulta_copilot/copilot.db`):

```sql
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    diagnosis TEXT,
    general_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    session_date TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    session_number INTEGER NOT NULL,
    manual_notes TEXT DEFAULT '',
    transcript_patient TEXT DEFAULT '',
    transcript_psychologist TEXT DEFAULT '',
    ai_suggestions TEXT DEFAULT '',
    duration_seconds INTEGER DEFAULT 0,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_patient ON sessions(patient_id);
```

**Clase `DBManager`:**
```python
class DBManager:
    """Singleton. Todas las operaciones son síncronas (SQLite es local y rápido)."""

    def __init__(self, db_path: str | None = None):
        # Si db_path es None, usa ~/.consulta_copilot/copilot.db
        # Habilita WAL mode y foreign_keys
        pass

    def init_db(self) -> None: ...
    def add_patient(self, name: str, **kwargs) -> int: ...  # retorna id
    def update_patient(self, patient_id: int, **kwargs) -> None: ...
    def delete_patient(self, patient_id: int) -> None: ...
    def get_patient(self, patient_id: int) -> dict | None: ...
    def get_all_patients(self) -> list[dict]: ...
    def add_session(self, patient_id: int, **kwargs) -> int: ...
    def get_sessions_by_patient(self, patient_id: int) -> list[dict]: ...
    def get_session(self, session_id: int) -> dict | None: ...
    def get_next_session_number(self, patient_id: int) -> int: ...
    def search_all(self, keyword: str) -> list[dict]: ...
        # Busca en patients.name, patients.diagnosis, patients.general_notes,
        # sessions.manual_notes, sessions.transcript_patient, sessions.transcript_psychologist
        # Retorna: [{"type": "patient"|"session", "patient_id": int,
        #            "session_id": int|None, "match_field": str, "snippet": str}]
```

**Detalles clave:**
- Usa `sqlite3.Row` como row_factory, convierte a dict antes de retornar
- `updated_at` se actualiza con trigger o manualmente en cada UPDATE
- `search_all` usa `LIKE '%keyword%'` y retorna snippets de ~100 chars alrededor del match
- Constructor acepta `db_path` para testing (`:memory:`)
- Habilitar `PRAGMA foreign_keys = ON` y `PRAGMA journal_mode = WAL`

### Paso 1.2 — Extender configuración en `src/utils/config.py`

**NO reemplazar** `TranscriberConfig`. Agregar campos nuevos a la misma clase o crear una clase `CopilotConfig` que la extienda/complemente.

Nuevos campos a agregar (con defaults razonables):
```python
# --- AI Provider ---
ai_provider: str = "openai"          # "openai" | "azure" | "ollama"
ai_model: str = "gpt-4o-mini"        # modelo por defecto
openai_api_key: str = ""
azure_api_key: str = ""
azure_endpoint: str = ""
azure_deployment: str = ""
azure_api_version: str = "2024-02-01"
ollama_host: str = "http://localhost:11434"

# --- Audio dual ---
loopback_device: str = ""            # dispositivo para capturar audio del paciente (sistema)

# --- DB ---
db_path: str = ""                    # vacío = default (~/.consulta_copilot/copilot.db)
```

**Env vars:** seguir el patrón existente con prefijo `TRANSCRIBER_` o agregar `COPILOT_` si TranscriberConfig usa ese prefijo.

**Agregar método** `get_ai_client()`:
```python
def get_ai_client(self):
    """Retorna un cliente openai compatible según el provider configurado."""
    import openai
    if self.ai_provider == "openai":
        return openai.OpenAI(api_key=self.openai_api_key)
    elif self.ai_provider == "azure":
        return openai.AzureOpenAI(
            api_key=self.azure_api_key,
            azure_endpoint=self.azure_endpoint,
            api_version=self.azure_api_version,
        )
    elif self.ai_provider == "ollama":
        return openai.OpenAI(base_url=f"{self.ollama_host}/v1", api_key="ollama")
    raise ValueError(f"Provider desconocido: {self.ai_provider}")
```

### Paso 1.3 — Agregar `openai` a `requirements.txt`

Agregar al final de requirements.txt:
```
openai>=1.0.0
```

### Paso 1.4 — Tests para la BD

Crear `tests/test_db_manager.py`:
```python
"""
Tests para DBManager usando base de datos en memoria.

Tests requeridos:
- test_init_creates_tables: verifica que patients y sessions existen
- test_add_get_patient: crea paciente, lo recupera, verifica campos
- test_update_patient: modifica campos, verifica updated_at cambia
- test_delete_patient_cascades: al borrar paciente, sus sesiones se borran
- test_add_get_session: crea sesión, verifica session_number auto-incrementa
- test_get_next_session_number: sin sesiones=1, con 3 sesiones=4
- test_search_all_by_name: busca por nombre de paciente
- test_search_all_by_transcript: busca en transcripción de sesión
- test_search_all_no_results: keyword inexistente retorna lista vacía
"""
```

### CHECKPOINT — Muestra al usuario:
```
DETENTE. Instrucciones de verificación:

1. Ejecutar tests:
   uv run pytest tests/test_db_manager.py -v

2. Verificar que los tests EXISTENTES siguen pasando:
   uv run pytest tests/ -v

3. Verificar que main.py sigue arrancando sin errores:
   uv run python main.py
   (cerrar la ventana manualmente)

4. Verificar que se puede importar el nuevo config:
   uv run python -c "from src.utils.config import TranscriberConfig; c = TranscriberConfig(); print(c.ai_provider, c.ai_model)"

Pregunta: "¿Tests pasan? ¿La app sigue funcionando? ¿Puedo continuar con la Fase 2 (UI)?"
```

---

## Fase 2: UI de Gestión de Pacientes y Configuración IA

**Meta:** Crear las ventanas de gestión sin alterar la ventana de transcripción existente. El flujo será: pantalla de inicio (lista de pacientes) → seleccionar paciente → iniciar sesión (ventana de transcripción mejorada).

### Paso 2.1 — `src/ui/home_window.py` (NUEVO — Ventana de Inicio)

Esta será la NUEVA ventana principal de la aplicación. La ventana actual (`main_window.py`) se convertirá en la ventana de sesión.

```python
"""
Clase HomeWindow(QMainWindow) — Pantalla de inicio del Copiloto Psicológico.

Layout (usa QVBoxLayout + QHBoxLayout, NO QML):
┌─────────────────────────────────────────────────────┐
│  Copiloto Psicológico                    [⚙ Config] │
│  ┌───────────────────────────────────────────────┐  │
│  │ 🔍 Buscar paciente...                        │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │ ┌─────────────────────────────────────┬─────┐ │  │
│  │ │ Juan Pérez — Ansiedad GAD          │▶ 📝│ │  │
│  │ ├─────────────────────────────────────┼─────┤ │  │
│  │ │ María López — TDM                  │▶ 📝│ │  │
│  │ ├─────────────────────────────────────┼─────┤ │  │
│  │ │ ...                                │     │ │  │
│  │ └─────────────────────────────────────┴─────┘ │  │
│  └───────────────────────────────────────────────┘  │
│  [+ Nuevo Paciente]                                 │
└─────────────────────────────────────────────────────┘

▶ = Botón "Nueva Sesión" → abre SessionWindow (Fase 3)
📝 = Botón "Editar" → abre PatientDialog

Funcionalidad:
- Usa QTableWidget o QListWidget para la lista de pacientes
- QLineEdit para búsqueda con filtrado en tiempo real (textChanged signal)
- QPushButton "Nuevo Paciente" → abre PatientDialog(mode="create")
- QPushButton "Config" → abre ConfigDialog
- Al cerrar PatientDialog, recargar la lista (usar signal accepted/finished)
- Doble-click en paciente → abre PatientDetailDialog con historial de sesiones
- Tamaño: 800x600, centrada
"""
```

### Paso 2.2 — `src/ui/patient_dialog.py` (NUEVO)

```python
"""
Clase PatientDialog(QDialog) — Crear o editar paciente.

Campos del formulario (QFormLayout):
- Nombre (QLineEdit, requerido)
- Edad (QSpinBox, rango 0-120, opcional)
- Género (QComboBox: ["", "Masculino", "Femenino", "Otro"])
- Diagnóstico (QLineEdit, opcional)
- Notas generales (QTextEdit, multilínea, opcional)

Modos:
- mode="create": título "Nuevo Paciente", campos vacíos, botón "Crear"
- mode="edit": título "Editar Paciente", carga datos del patient_id, botón "Guardar"

Al guardar:
- Validar que nombre no esté vacío
- Llamar db_manager.add_patient() o db_manager.update_patient()
- Emitir self.accept() para que HomeWindow recargue la lista
"""
```

### Paso 2.3 — `src/ui/config_dialog.py` (NUEVO — Configuración IA)

**NO confundir** con `settings_dialog.py` existente (que es de configuración de transcripción).

```python
"""
Clase ConfigDialog(QDialog) — Configuración del proveedor de IA.

Usa QTabWidget con 2 pestañas:

Pestaña "Proveedor IA":
- QComboBox para provider: ["OpenAI", "Azure", "Ollama"]
- QLineEdit para model (con placeholder del default)
- Campos dinámicos según provider seleccionado:
  - OpenAI: api_key (QLineEdit, echoMode=Password)
  - Azure: api_key, endpoint, deployment, api_version
  - Ollama: host (con default http://localhost:11434)
- QPushButton "Probar conexión" → hace una llamada simple a la API
  (ej: completions con prompt "di hola" max_tokens=5)
  y muestra resultado en QLabel (✅ Conectado / ❌ Error: ...)
- Mostrar/ocultar campos según provider (usar currentIndexChanged signal)

Pestaña "Audio" (para Fase 3, crear placeholder vacío por ahora):
- QLabel: "Configuración de audio disponible en próxima versión"

Al guardar:
- Escribir valores en TranscriberConfig / archivo de configuración
- Nota: si pydantic-settings no soporta escritura fácil,
  usar un .env file o un json/ini separado para los campos de IA
"""
```

### Paso 2.4 — `src/ui/patient_detail_dialog.py` (NUEVO)

```python
"""
Clase PatientDetailDialog(QDialog) — Detalle de paciente + historial de sesiones.

Layout:
┌─────────────────────────────────────────────────┐
│ Juan Pérez                        [Editar] [🗑] │
│ Edad: 35 | Género: M | Dx: Ansiedad GAD        │
│ ─────────────────────────────────────────────── │
│ Notas generales:                                │
│ ┌─────────────────────────────────────────────┐ │
│ │ Paciente derivado por médico general...     │ │
│ └─────────────────────────────────────────────┘ │
│ ─────────────────────────────────────────────── │
│ Historial de sesiones:                          │
│ ┌──────┬────────────┬──────────────────┬──────┐ │
│ │ #    │ Fecha      │ Duración         │  👁  │ │
│ │ 1    │ 2025-06-01 │ 45 min           │  👁  │ │
│ │ 2    │ 2025-06-08 │ 50 min           │  👁  │ │
│ └──────┴────────────┴──────────────────┴──────┘ │
│                                                 │
│ [+ Nueva Sesión]                                │
└─────────────────────────────────────────────────┘

- 👁 = Ver sesión pasada → abre SessionReviewDialog (solo lectura)
- 🗑 = Eliminar paciente (con QMessageBox.question de confirmación)
- "Nueva Sesión" → abre la ventana de sesión en vivo (Fase 3)
"""
```

### Paso 2.5 — Modificar `main.py`

Cambiar el punto de entrada para que abra `HomeWindow` en lugar de la ventana de transcripción directa:

```python
# Antes: app arrancaba directo a transcripción
# Después: app arranca en HomeWindow, desde ahí se navega

def main():
    app = QApplication(sys.argv)
    # Inicializar BD
    from src.db.manager import DBManager
    db = DBManager()
    db.init_db()
    # Mostrar ventana de inicio
    window = HomeWindow(db=db)
    window.show()
    sys.exit(app.exec())
```

**IMPORTANTE:** La ventana actual de transcripción (`main_window.py`) debe seguir siendo accesible. En esta fase, el botón "Nueva Sesión" puede abrir la ventana de transcripción existente como está (sin modificaciones aún).

### CHECKPOINT — Muestra al usuario:
```
DETENTE. Instrucciones de verificación:

1. Ejecutar la app:
   uv run python main.py

2. Verificar flujo completo:
   a. Se abre HomeWindow (lista vacía de pacientes)
   b. Click "Nuevo Paciente" → se abre formulario → llenar → guardar
   c. El paciente aparece en la lista
   d. Click "Editar" → se carga la info → modificar → guardar
   e. Click en paciente → se abre detalle (historial vacío)
   f. Click "Config" → se abre diálogo de IA → seleccionar provider → llenar key
   g. Click "Probar conexión" → muestra resultado
   h. Buscar en el campo de búsqueda → filtra pacientes

3. Verificar que la transcripción sigue funcionando:
   Desde el detalle del paciente, "Nueva Sesión" debe abrir
   la ventana de transcripción original sin errores.

4. Tests:
   uv run pytest tests/ -v

Pregunta: "¿El flujo de gestión de pacientes funciona correctamente?
¿La transcripción original sigue operativa? ¿Puedo continuar con la Fase 3?"
```

---

## Fase 3: Transcripción Dual + Panel Copiloto

**Meta:** Esta es la fase más compleja. Se modifica la ventana de transcripción para soportar audio dual y se agrega el panel de análisis IA.

### Paso 3.1 — Captura de audio dual (`src/audio/dual_capture.py`, NUEVO)

```python
"""
Clase DualAudioCapture — Captura simultánea de micrófono + loopback del sistema.

Investigar primero:
- ¿sounddevice soporta loopback/WASAPI en Windows?
  Si no, usar la librería `soundcard` que sí soporta include_loopback=True.
- En macOS, el loopback requiere software externo (BlackHole, Soundflower).
  Documentar esto como prerequisito.

Diseño:
- Dos hilos (QThread) de captura, uno por cada fuente de audio
- Cada hilo alimenta su propia cola (queue.Queue)
- Señales Qt para notificar fragmentos listos:
  - psychologist_audio_ready(np.ndarray)
  - patient_audio_ready(np.ndarray)

Si sounddevice no soporta loopback:
- Agregar `soundcard` a requirements.txt
- Usar soundcard SOLO para el loopback, mantener sounddevice para el micrófono
  (así se minimiza el impacto en el código existente)

Fallback: si no hay dispositivo loopback configurado, capturar solo micrófono
(comportamiento actual, no romper nada).
"""
```

### Paso 3.2 — `src/transcription/dual_worker.py` (NUEVO)

```python
"""
Clase DualTranscriptionWorker(QThread) — Procesa dos streams de audio.

Extiende o complementa SlidingWindowWorker existente.

Señales:
- psychologist_text(str)     # texto del psicólogo
- patient_text(str)          # texto del paciente
- psychologist_partial(str)  # parcial del psicólogo
- patient_partial(str)       # parcial del paciente

Internamente:
- Reutiliza TranscriptionEngine existente (faster-whisper)
- Procesa ambas colas alternadamente o con prioridad al paciente
- Usa el mismo VAD (silero) para ambos streams

NOTA: Si un solo TranscriptionEngine no puede procesar dos streams
en paralelo, crear dos instancias con modelos más pequeños
o serializar las transcripciones (round-robin).
"""
```

### Paso 3.3 — `src/ai/copilot.py` (NUEVO módulo)

```python
"""
Clase CopilotAnalyzer — Análisis en tiempo real del discurso del paciente.

Método principal:
async def analyze(self, patient_text: str, context: dict) -> str

Donde context incluye:
- patient_name: str
- diagnosis: str
- general_notes: str
- session_history: list[str]  # resúmenes de sesiones anteriores
- previous_analysis: str      # análisis previo en esta sesión (para continuidad)

System prompt (ajustar según feedback del usuario):
'''
Eres un asistente clínico para un psicólogo durante una teleconsulta.
Tu rol es DISCRETO: proporcionas observaciones breves y relevantes.
NO diagnosticas. NO das consejos directos al paciente.
Solo asistes al psicólogo con:
1. Temas emocionales detectados en el discurso
2. Posibles distorsiones cognitivas
3. Patrones recurrentes comparados con sesiones anteriores
4. Preguntas sugeridas que el psicólogo podría hacer
5. Alertas sobre indicadores de riesgo (ideación suicida, autolesión)

Responde en español. Sé conciso (máx 3-4 líneas por análisis).
Si no hay nada relevante que señalar, responde "—".
'''

Implementación:
- Usa config.get_ai_client() para obtener el cliente
- Usa config.ai_model para el modelo
- Streaming response para mostrar progresivamente
- Throttle: no analizar cada fragmento, sino acumular ~30 segundos
  de texto del paciente antes de enviar (evitar spam a la API)
- Manejar errores de API graciosamente (mostrar en UI, no crashear)
"""
```

### Paso 3.4 — `src/ui/session_window.py` (NUEVO, reemplaza/envuelve main_window.py)

```python
"""
Clase SessionWindow(QMainWindow) — Ventana de sesión en vivo con copiloto.

Recibe: patient_id, db_manager instance

Layout:
┌─────────────────────────────────────────────────────────────┐
│ Sesión #3 — Juan Pérez                    [⏸ Pausar] [⏹ Fin] │
├───────────────────────────────────┬─────────────────────────┤
│                                   │                         │
│ Transcripción                     │ 🤖 Copiloto             │
│ ┌───────────────────────────────┐ │ ┌─────────────────────┐ │
│ │ [PSI] Buenos días Juan...     │ │ │ Tema: ansiedad      │ │
│ │ [PAC] Hola doctor, esta      │ │ │ anticipatoria.       │ │
│ │       semana me sentí...      │ │ │                     │ │
│ │ [PSI] ¿Qué situaciones...    │ │ │ Sugerencia: explorar │ │
│ │ [PAC] Sobre todo en el       │ │ │ trigger laboral.     │ │
│ │       trabajo cuando...       │ │ │                     │ │
│ └───────────────────────────────┘ │ └─────────────────────┘ │
├───────────────────────────────────┴─────────────────────────┤
│ Notas del psicólogo:                                        │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Paciente reporta mejora parcial con técnicas de resp... │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ ⏱ 00:32:15 | 🎙 Mic: Activo | 🔊 Sistema: Activo          │
└─────────────────────────────────────────────────────────────┘

Componentes:
- QSplitter horizontal: transcripción (70%) | copiloto (30%)
- QTextEdit read-only para transcripción (con colores: PSI=azul, PAC=verde)
- QTextEdit read-only para copiloto (scroll automático)
- QTextEdit editable para notas manuales
- QStatusBar: timer, estado mic, estado loopback
- Botón Pausar: pausa/reanuda transcripción (no cierra streams)
- Botón Finalizar: guarda todo en BD y cierra ventana

Flujo al "Finalizar":
1. Detener transcripción y captura de audio
2. Calcular duración
3. Concatenar todas las sugerencias del copiloto
4. Llamar db_manager.add_session(patient_id, ...)
5. Mostrar QMessageBox de confirmación
6. Cerrar ventana y volver a HomeWindow/PatientDetailDialog

Integración con transcripción existente:
- Reutilizar la lógica de SlidingWindowWorker / transcript_view
- El panel de transcripción puede embeber TranscriptView existente
  o crear uno nuevo con formato dual (PSI/PAC)
"""
```

### Paso 3.5 — Actualizar pestaña Audio en ConfigDialog

```python
"""
Completar la pestaña "Audio" en config_dialog.py:
- QComboBox para "Micrófono (Psicólogo)": listar dispositivos de entrada
- QComboBox para "Audio del Sistema (Paciente)": listar dispositivos loopback
- Usar sounddevice.query_devices() para popular las listas
- QPushButton "Refrescar dispositivos"
- QLabel de advertencia si no hay dispositivos loopback:
  "No se detectan dispositivos loopback. En macOS instala BlackHole.
   En Windows, activa 'Mezcla estéreo' en configuración de sonido."
- Guardar selección en config
"""
```

### CHECKPOINT — Muestra al usuario:
```
DETENTE. Instrucciones de verificación:

1. Ejecutar la app:
   uv run python main.py

2. Verificar flujo completo de sesión:
   a. Crear paciente (si no existe)
   b. Ir a detalle del paciente → "Nueva Sesión"
   c. Se abre SessionWindow con el nombre del paciente
   d. Verificar que el timer arranca
   e. Hablar por micrófono → texto aparece como [PSI]
   f. Si hay loopback configurado, reproducir audio → texto como [PAC]
   g. Si hay API key configurada, el panel Copiloto muestra análisis
   h. Escribir notas manuales
   i. Click "Finalizar" → se guarda en BD
   j. Volver al detalle → la sesión aparece en el historial

3. Verificar fallbacks:
   a. Sin API key → copiloto muestra "Configure un proveedor de IA"
   b. Sin loopback → solo transcribe micrófono (modo single como antes)
   c. Error de API → muestra error en panel copiloto, no crashea

4. Tests:
   uv run pytest tests/ -v

Pregunta: "¿La sesión en vivo funciona? ¿La transcripción dual opera?
¿El copiloto responde? ¿Puedo continuar con la Fase 4 (pulido)?"
```

---

## Fase 4: Revisión de Sesiones, Búsqueda y Pulido

**Meta:** Completar funcionalidades secundarias y pulir la experiencia.

### Paso 4.1 — `src/ui/session_review_dialog.py` (NUEVO)

```python
"""
Clase SessionReviewDialog(QDialog) — Vista de solo lectura de una sesión pasada.

Recibe: session_id, db_manager

Layout similar a SessionWindow pero:
- Todo es read-only
- No hay botones de grabación
- Muestra transcripción completa (PSI/PAC con colores)
- Muestra notas manuales
- Muestra sugerencias del copiloto
- Muestra metadata: fecha, duración, número de sesión
- Botones: "Exportar TXT" | "Exportar SRT" | "Cerrar"

Exportar: reutilizar src/utils/export.py adaptándolo para el formato dual.
"""
```

### Paso 4.2 — Búsqueda global en HomeWindow

```python
"""
Mejorar el buscador de HomeWindow:
- Al escribir, si el texto tiene ≥2 caracteres, llamar db_manager.search_all()
- Mostrar resultados agrupados: primero pacientes, luego sesiones
- Cada resultado de sesión muestra: "Sesión #N de [Paciente] — encontrado en [campo]"
- Click en resultado de paciente → abre PatientDetailDialog
- Click en resultado de sesión → abre SessionReviewDialog
- Debounce de 300ms para no buscar en cada keystroke (usar QTimer.singleShot)
"""
```

### Paso 4.3 — Exportación mejorada

```python
"""
Extender src/utils/export.py:
- export_session_txt(session: dict) -> str
  Formato:
  === Sesión #N — [Paciente] — [Fecha] ===
  Duración: XX minutos

  --- TRANSCRIPCIÓN ---
  [PSI] ...
  [PAC] ...

  --- NOTAS DEL PSICÓLOGO ---
  ...

  --- SUGERENCIAS DEL COPILOTO ---
  ...

- export_session_pdf(session: dict, patient: dict) -> bytes
  (Opcional, solo si el usuario lo pide. Usar reportlab o weasyprint.)
"""
```

### Paso 4.4 — Mejoras UX

```python
"""
1. Advertencia de auriculares:
   - En ConfigDialog pestaña Audio, si el dispositivo de salida
     seleccionado contiene "Speaker" o "Altavoz", mostrar QLabel:
     "⚠️ Se recomienda usar auriculares para evitar eco en la grabación."

2. Confirmación al cerrar sesión:
   - Si SessionWindow se cierra con la X (no con "Finalizar"),
     mostrar QMessageBox.question: "¿Deseas guardar la sesión antes de cerrar?"
     Opciones: Guardar / Descartar / Cancelar

3. Atajos de teclado en SessionWindow:
   - Espacio: Pausar/Reanudar (si el foco no está en notas)
   - Ctrl+S: Guardar notas parciales
   - Ctrl+Q: Finalizar sesión

4. Indicadores visuales en StatusBar:
   - LED verde/rojo para estado del micrófono
   - LED para estado del loopback
   - LED para estado de la API de IA
"""
```

### CHECKPOINT FINAL — Muestra al usuario:
```
DETENTE. Verificación final:

1. Flujo completo end-to-end:
   a. Abrir app → HomeWindow vacía
   b. Configurar proveedor IA y audio
   c. Crear paciente con todos los campos
   d. Iniciar sesión → transcribir → recibir sugerencias IA
   e. Finalizar sesión → se guarda
   f. Ver historial → abrir sesión pasada → exportar TXT
   g. Buscar por keyword → encontrar en transcripciones
   h. Editar paciente → cambiar diagnóstico
   i. Crear segunda sesión → verificar que session_number = 2

2. Tests completos:
   uv run pytest tests/ -v --tb=short

3. Verificar que no hay warnings ni errores en consola

Pregunta: "¿Todo funciona correctamente? ¿Hay algo que ajustar o mejorar?"
```

---

## Notas Técnicas Importantes

### Lo que NO se debe hacer
- **No migrar de PySide6 a otro framework** — el proyecto ya usa PySide6, mantenerlo
- **No crear un sistema de config paralelo** — extender el existente con pydantic-settings
- **No reescribir la transcripción** — reutilizar TranscriptionEngine y SlidingWindowWorker
- **No usar customtkinter** — el plan original lo mencionaba pero el proyecto usa PySide6
- **No instalar librerías innecesarias** — verificar si sounddevice ya soporta loopback antes de agregar soundcard

### Decisiones de arquitectura
- `DBManager` es singleton con inyección de path para testing
- Toda UI nueva sigue patrones PySide6 (QMainWindow, QDialog, signals/slots)
- El copiloto IA usa la misma API de OpenAI para todos los providers (compatible con Azure y Ollama)
- La transcripción dual es opt-in: sin configurar loopback, funciona como antes (solo mic)
- Los datos se guardan en `~/.consulta_copilot/` para persistencia entre actualizaciones

### Orden de prioridad si hay limitaciones de tiempo
1. **Fase 1 + 2:** BD + gestión de pacientes (mínimo viable)
2. **Fase 3.3 + 3.4:** Panel copiloto con transcripción single (sin dual)
3. **Fase 3.1 + 3.2:** Transcripción dual (mejora significativa)
4. **Fase 4:** Pulido (nice to have)