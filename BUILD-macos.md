# Build — macOS

Guía para empaquetar **Consulta Copilot** en un `.app` distribuible para macOS.

---

## Requisitos previos

| Herramienta | Versión mínima | Cómo obtenerla |
|---|---|---|
| Python 3.11 (via uv) | 3.11 | ya instalado en `.venv/` |
| uv | latest | https://github.com/astral-sh/uv |
| PyInstaller | 6.x | ver paso 1 |

---

## Paso 1 — Setup del entorno (primera vez)

```bash
uv venv .venv --python 3.11
uv pip install -r requirements.txt --python .venv/bin/python
uv pip install torchaudio --python .venv/bin/python
uv pip install pyinstaller --python .venv/bin/python
```

---

## Paso 2 — Construir el .app con PyInstaller

Desde la raíz del proyecto:

```bash
.venv/bin/pyinstaller main.py \
  --name "ConsultaCopilot" \
  --windowed \
  --onedir \
  --noconfirm \
  --collect-all faster_whisper \
  --collect-all sounddevice \
  --hidden-import torchaudio \
  --hidden-import scipy
```

Esto genera:
```
dist/
  ConsultaCopilot.app/    ← app bundle macOS
build/                    ← archivos temporales (se puede borrar)
ConsultaCopilot.spec      ← spec reutilizable para rebuilds
```

> **Nota:** En macOS, `--onefile` no es compatible con apps gráficas (`.app` bundle).
> El estándar es distribuir el `.app` comprimido en un `.zip`.

---

## Paso 3 — Verificar la app

```bash
open dist/ConsultaCopilot.app
```

Comprueba que la ventana abre correctamente y que el VAD se carga.

---

## Paso 4 — Empaquetar para distribución

```bash
cd dist && zip -r ConsultaCopilot-macOS.zip ConsultaCopilot.app
```

Distribuye el archivo `dist/ConsultaCopilot-macOS.zip`.
El usuario lo descomprime y arrastra `ConsultaCopilot.app` a su carpeta Aplicaciones.

---

## Rebuilds rápidos

Una vez generado el `.spec`, puedes reconstruir sin repetir todos los flags:

```bash
.venv/bin/pyinstaller ConsultaCopilot.spec --clean --noconfirm
```

---

## Solución de problemas frecuentes

### `ModuleNotFoundError: No module named 'torchaudio'`
```bash
uv pip install torchaudio --python .venv/bin/python
```

### `ModuleNotFoundError: No module named 'PySide6'`
```bash
uv pip install PySide6 --python .venv/bin/python
```

### La app abre y cierra inmediatamente
Ejecuta desde terminal para ver el traceback:
```bash
dist/ConsultaCopilot.app/Contents/MacOS/ConsultaCopilot
```

### Error al cargar silero-vad (primera ejecución)
El modelo se descarga automáticamente de internet la primera vez.
Requiere conexión a internet. Se cachea en `~/.cache/torch/hub/`.

### macOS bloquea la app ("desarrollador no verificado")
La app no está firmada con un certificado Apple. Para abrirla:
1. Clic derecho → Abrir → Abrir igualmente.
2. O desde Terminal: `xattr -dr com.apple.quarantine dist/ConsultaCopilot.app`

---

## Estructura de archivos de empaquetado

```
ConsultaCopilot.spec       ← configuración de PyInstaller (generado automáticamente)
BUILD-macos.md             ← esta guía
dist/
  ConsultaCopilot.app          ← app bundle
  ConsultaCopilot-macOS.zip    ← distribución comprimida
```

---

## Modelos descargados en el primer uso

| Modelo | Caché |
|---|---|
| silero-vad | `~/.cache/torch/hub/snakers4_silero-vad_master` |
| Whisper | `~/.cache/huggingface/` |

Los modelos no se incluyen en el bundle (~1-2 GB). Se descargan automáticamente al primer uso.
