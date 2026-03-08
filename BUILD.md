# Generar el instalador .exe

Guía paso a paso para empaquetar **Transcriptor en Tiempo Real** en un instalador Windows.

---

## Requisitos previos

| Herramienta | Versión mínima | Cómo obtenerla |
|---|---|---|
| Python 3.11 (via uv) | 3.11 | ya instalado en `.venv/` |
| PyInstaller | 6.x | ver paso 1 |
| Inno Setup | 6.x | https://jrsoftware.org/isdl.php |

> Inno Setup solo es necesario para generar el instalador final (`.exe` con wizard).
> Si solo quieres el directorio con el ejecutable, con PyInstaller es suficiente.

---

## Paso 1 — Instalar PyInstaller en el entorno

```bash
export PATH="$PATH:/c/Users/favio/.local/bin"
uv pip install pyinstaller --python .venv/Scripts/python.exe
```

---

## Paso 2 — Construir el ejecutable con PyInstaller

Desde la raíz del proyecto:

```bash
.venv/Scripts/python.exe -m PyInstaller transcriptor.spec --clean
```

Esto genera:
```
dist/
  Transcriptor/          ← carpeta con el exe y todas sus dependencias
    Transcriptor.exe
    _internal/
    ...
build/                   ← archivos temporales (se puede borrar)
```

> **Primera ejecución:** el exe descargará automáticamente los modelos de Whisper
> y silero-vad en `%USERPROFILE%\.cache\`. Requiere conexión a internet.

---

## Paso 3 — Verificar el ejecutable

```bash
dist/Transcriptor/Transcriptor.exe
```

Comprueba que la ventana abre correctamente y que el VAD se carga.

---

## Paso 4 — Generar el instalador con Inno Setup

1. Instala [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. Abre el archivo `installer.iss` con Inno Setup Compiler.
3. Haz clic en **Build → Compile** (o presiona `F9`).
4. El instalador se genera en:
   ```
   dist/Transcriptor-Setup-1.0.0.exe
   ```

O desde la línea de comandos (si `iscc` está en el PATH):

```bash
"C:/Program Files (x86)/Inno Setup 6/ISCC.exe" installer.iss
```

---

## Solución de problemas frecuentes

### `ModuleNotFoundError: No module named 'ctranslate2'`
PyInstaller no detectó ctranslate2 automáticamente. Asegúrate de que
`hiddenimports` en `transcriptor.spec` incluye `"ctranslate2"`.

### El exe abre y cierra inmediatamente
Prueba en modo consola para ver el error:
1. Edita `transcriptor.spec`: cambia `console=False` → `console=True`.
2. Reconstruye con `--clean`.
3. Ejecuta desde PowerShell para ver el traceback.
4. Corrige el error, luego vuelve a `console=False`.

### Antivirus bloquea el exe
PyInstaller genera falsos positivos en algunos antivirus. Es un problema conocido.
Puedes firmarlo con un certificado de código (Code Signing Certificate) para evitarlo.

### Error al capturar audio del sistema
PyAudioWPatch requiere que el dispositivo loopback esté disponible en Windows.
Verifica en Panel de control → Sonido → Grabación que "Stereo Mix" esté habilitado,
o usa un dispositivo virtual como VB-Cable.

---

## Estructura de archivos de empaquetado

```
transcriptor.spec    ← configuración de PyInstaller
installer.iss        ← script de Inno Setup para el instalador
BUILD.md             ← esta guía
```

---

## Actualizar la versión

Para cambiar la versión del instalador, edita la línea en `installer.iss`:

```ini
#define MyAppVersion   "1.0.0"
```

Y actualiza también el nombre del ejecutable de salida (`OutputBaseFilename`).
