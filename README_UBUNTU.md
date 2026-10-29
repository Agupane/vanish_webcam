# VanishCam en Ubuntu

Fork de [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) adaptado a Ubuntu 22.04 y 24.04.
El video sale por una cámara virtual (`v4l2loopback`) que podés elegir en Zoom, Google Meet o cualquier otra app.

## Instalación

```bash
git clone https://github.com/Agupane/vanish_webcam.git
cd vanish_webcam
./install-ubuntu.sh
```

El script instala lo siguiente:

- **Paquetes del sistema:** `v4l2loopback-dkms`, `v4l-utils`, `ffmpeg` y las librerías gráficas.
- **Cámara virtual:** la crea como `VanishCam` (`/dev/video10`) y la deja configurada para que vuelva después de cada reinicio.
- **Entorno Python:** crea `.venv` e instala las dependencias.
- **Modelos de MediaPipe:** los descarga una sola vez (unos 10 MB).
- **Menú de aplicaciones:** agrega un acceso llamado **VanishCam**.

**Secure Boot:** si `apt` te pide una contraseña para firmar el módulo, elegí una y reiniciá. Al arrancar aparece una pantalla azul (MOK): elegí *Enroll MOK* y escribí esa contraseña. Después volvé a correr `./install-ubuntu.sh`.

## Uso

```bash
./vanishcam.sh                 # muestra el menú para elegir el efecto
./vanishcam.sh --mode normal   # gesto de V con índice y medio
./vanishcam.sh --mode naruto   # palmas juntas: humo y tronco
```

1. Se abre la ventana de vista previa. **Salí del cuadro 4 segundos** para que capture el fondo vacío.
2. Volvé a entrar y hacé el gesto. Para reaparecer, apretá `R`.

| Tecla | Acción |
|---|---|
| `V` | dispara el efecto a mano |
| `R` | reaparecer |
| `ESPACIO` | capturar el fondo de nuevo |
| `F` | pantalla completa |
| `Q` / `ESC` | salir |

### Zoom

Configuración → Video → Cámara → **VanishCam**. Si no aparece, cerrá Zoom del todo y abrilo después de arrancar `vanishcam.sh`.

### Google Meet (Chrome o Firefox)

Primero arrancá `vanishcam.sh` y después abrí Meet. En Configuración → Video elegí **VanishCam**.
Chrome solo muestra la cámara cuando ya está recibiendo video, por eso hay que arrancar la app antes que Meet.

## Opciones útiles

```bash
./vanishcam.sh --camera /dev/video2          # otra webcam (listalas con v4l2-ctl --list-devices)
./vanishcam.sh --width 640 --height 360      # menos carga en PCs viejas
./vanishcam.sh --no-mirror                   # sin efecto espejo
./vanishcam.sh --gesture-debug               # muestra en la terminal qué gesto detecta
```

Si no pasás `--camera`, se usa la primera webcam real y se ignora la cámara virtual.

## Problemas comunes

- **"La cámara virtual no está cargada":** corré `sudo modprobe v4l2loopback`. Si falla, revisá lo de Secure Boot.
- **La webcam está ocupada:** cerrá cualquier otra app que la esté usando (Zoom, Meet, Cheese) antes de arrancar VanishCam. En Zoom o Meet tiene que estar elegida *VanishCam*, no tu webcam.
- **Te borra mal o deja manchas:** usá un fondo fijo y con buena luz. Si se movió la cámara, apretá `ESPACIO`.
- **Va lento:** corre solo con el procesador. Bajale la resolución con `--width 640 --height 360`.

## Diferencias con el original

- **Webcam real:** en Linux se detecta sola, se abre con V4L2 en MJPG y no se confunde con la cámara virtual. `--camera` también acepta rutas como `/dev/video2`.
- **Scripts nuevos:** `install-ubuntu.sh` y `vanishcam.sh` reemplazan a los `.bat` de Windows.
- **Tests:** ya corren desde la raíz del repo con `python -m unittest`. Se actualizaron los tests de reintentos de gestos que habían quedado viejos.
- **Modos que no están:** el README original menciona *Goku* y *Particles*, pero no están en el código; acá solo hay *normal* y *naruto*.
- **Sonido:** el sonido del modo naruto sale por tus parlantes, no entra a la llamada.
