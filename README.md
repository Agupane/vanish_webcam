# VanishCam

Efectos de desaparición para tu webcam en Zoom, Google Meet o cualquier app de videollamadas. Hacés un gesto y desaparecés de la imagen; repetís el gesto y volvés.

El modo por defecto es **Dragon Ball**: apoyás índice y medio juntos en la frente durante 1 segundo (la Teletransportación Instantánea) y te vas con líneas de cómic y un destello. También están el modo **Normal** (V con dos dedos, te disolvés) y el modo **Naruto** (palmas juntas, humo y un tronco).

Todo se procesa en tu computadora: el video no se graba ni se manda a ningún servidor. Es un fork de [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) (README original en [README_ORIGINAL.md](README_ORIGINAL.md)).

## Instalación

| Sistema | Soporte | Cámara virtual |
|---|---|---|
| **Ubuntu 22.04 / 24.04** (y Debian) | Completo | v4l2loopback (la instala el instalador) |
| **Windows 10 / 11** | Completo | OBS Studio (lo instala el instalador) |
| **macOS con chip Apple** (M1 o posterior) | Completo | OBS Studio 30 o posterior |
| **macOS con Intel** | Experimental: usa versiones viejas de MediaPipe | OBS Studio 30 o posterior |

Los instaladores bajan unos 300 MB (Python, librerías y modelos) y no tocan el Python de tu sistema.

### Ubuntu / Linux

```bash
curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
```

O, si preferís revisar el código antes:

```bash
git clone https://github.com/Agupane/vanish_webcam.git ~/VanishCam
cd ~/VanishCam
./install.sh
```

Te pide la contraseña de `sudo` para instalar los paquetes y la cámara virtual **VanishCam**. Si el paquete de la cámara virtual de tu Ubuntu no compila para tu kernel (pasa en 22.04 con kernels 6.8), el instalador compila la versión oficial.

**Secure Boot:** si `apt` te pide una contraseña para firmar el módulo, elegí una y reiniciá. Al arrancar aparece una pantalla azul (MOK): elegí *Enroll MOK* → *Continue*, escribí esa contraseña y reiniciá. Después volvé a correr el instalador.

### Windows

Abrí **PowerShell** (no hace falta como administrador) y pegá:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.ps1 | iex"
```

O bajá el repo (**Code → Download ZIP**), descomprimilo y hacé clic derecho en `install.ps1` → **Ejecutar con PowerShell**.

El instalador deja todo en `%USERPROFILE%\VanishCam`, instala **OBS Studio** con `winget` si no lo tenés (puede pedir permiso de administrador) y crea el acceso **VanishCam** en el Escritorio.

### macOS

Abrí la **Terminal** y pegá:

```bash
curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
```

Si tenés [Homebrew](https://brew.sh), el instalador instala OBS Studio; si no, te abre la página para bajarlo. Después hay que **activar una sola vez la cámara virtual de OBS**:

1. Abrí OBS Studio.
2. Tocá **Iniciar cámara virtual** y aceptá el permiso que pide macOS (Ajustes del Sistema → General → Ítems de inicio y extensiones → Extensiones de cámara).
3. Tocá **Detener cámara virtual** y cerrá OBS.

La primera vez que abras VanishCam, macOS pide permiso para que la Terminal use la cámara: aceptalo.

## Uso

| Sistema | Cómo abrirlo |
|---|---|
| Ubuntu | Menú de aplicaciones → **VanishCam**, o `~/VanishCam/vanishcam.sh` |
| Windows | **VanishCam** en el Escritorio, o `vanishcam.bat` |
| macOS | **VanishCam.command** en el Escritorio, o `~/VanishCam/vanishcam.sh` |

1. Se abre una ventana con tu cámara. **Salí del cuadro**: a los 4 segundos saca la foto del fondo vacío (la terminal te avisa).
2. Volvé a entrar y hacé el gesto **sosteniéndolo**: desaparecés.
3. Para volver, **bajá la mano y repetí el gesto**.

| Modo | Gesto | Sostener |
|---|---|---|
| **Dragon Ball** (por defecto) | Índice y medio juntos, estirados, apoyados en la frente | 1 s |
| **Normal** (`--mode normal`) | V con índice y medio | 0,3 s |
| **Naruto** (`--mode naruto`) | Palmas juntas frente a la cámara | 0,3 s |

Teclas (con la ventana de VanishCam activa): `V` desaparecer, `R` reaparecer, `ESPACIO` foto del fondo de nuevo, `F` pantalla completa, `Q` salir.

**En Zoom o Meet**, primero abrí VanishCam y después elegí la cámara en la configuración de video:

- Ubuntu: **VanishCam**.
- Windows y macOS: **OBS Virtual Camera**. Si OBS está abierto, no actives su cámara virtual: la usa VanishCam.

Si no aparece, cerrá Zoom del todo (o recargá Meet) y volvé a abrirlo.

La guía completa (opciones, efectos, problemas comunes) está en [README_UBUNTU.md](README_UBUNTU.md); casi todo vale igual para Windows y macOS.

## Sonido de los efectos en la llamada

Los sonidos de los efectos suenan en **tus parlantes**: la cámara virtual lleva solo video. Los demás los escuchan si los levanta tu micrófono, y la supresión de ruido de Zoom/Meet suele borrarlos.

- **Ubuntu:** arrancá con `./vanishcam.sh --sonido-en-llamada`. Crea un micrófono virtual **VanishCam-Microfono** que mezcla tu micrófono real con los efectos (y los seguís escuchando vos). En Zoom/Meet elegí ese micrófono y bajá la supresión de ruido (Zoom: Configuración → Audio → Supresión de ruido de fondo: Baja, o activá "Sonido original para músicos"). Al cerrar VanishCam se desarma solo.
- **Windows y macOS:** todavía no está automatizado. Hace falta un cable de audio virtual ([VB-Cable](https://vb-audio.com/Cable/) en Windows, [BlackHole](https://github.com/ExistentialAudio/BlackHole) en macOS) y que VanishCam toque los efectos ahí; está en la lista de pendientes.

## Seguridad y privacidad

- El video se procesa solo en tu computadora; VanishCam no guarda imágenes ni abre conexiones de red, salvo la primera descarga de los modelos de Google MediaPipe, que se verifica con SHA-256.
- En Linux, si hay que compilar la cámara virtual, el instalador verifica el commit exacto del código fuente antes de compilarlo.
- Los instaladores de una línea (`curl | bash`, `irm | iex`) ejecutan lo que está en la rama `main` de este repo: si preferís, cloná el repo, revisá los scripts y corrélos a mano.

## Desarrollo

Contexto para agentes y desarrolladores en [AGENTS.md](AGENTS.md). Tests:

```bash
.venv/bin/python -m unittest discover -p 'test_*.py'
```
