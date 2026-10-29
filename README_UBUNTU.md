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
./vanishcam.sh                   # modo Dragon Ball (por defecto)
./vanishcam.sh --mode normal     # V con índice y medio: disolución
./vanishcam.sh --mode naruto     # palmas juntas: humo y tronco
./vanishcam.sh --menu            # elegir el modo en una ventana
```

1. Se abre la ventana de vista previa. **Salí del cuadro**: a los 4 segundos saca la foto del fondo vacío. Si todavía te ve en cuadro, te avisa en la terminal y espera 2 segundos más.
2. Volvé a entrar y hacé el gesto del modo **sosteniéndolo**. Desaparecés con el efecto.
3. Mientras estás desaparecido, la llamada ve la foto del fondo. Para volver, **bajá la mano y repetí el mismo gesto**: reaparecés con el efecto al revés.

| Modo | Gesto | Cuánto sostenerlo | Efecto |
|---|---|---|---|
| **Dragon Ball** | Índice y medio juntos y estirados, apoyados en la frente (la Teletransportación Instantánea) | 1 segundo | Líneas verticales de cómic sobre tu silueta, un destello y desaparecés (casi 1 segundo) |
| **Normal** | V con índice y medio | un instante (0,3 s) | Te disolvés de abajo hacia arriba (3,6 s); al volver te armás de arriba hacia abajo |
| **Naruto** | Palmas juntas frente a la cámara | un instante (0,3 s) | Nube de humo y un tronco que cae (1,5 s); al volver, el tronco se va en una nube de humo |

Un gesto suelto de un solo cuadro ya no te hace desaparecer, y después de cada efecto hay que bajar la mano antes de que el gesto vuelva a contar.

| Tecla (con la ventana de vista previa activa) | Acción |
|---|---|
| `V` | desaparecer a mano |
| `R` | reaparecer a mano |
| `ESPACIO` | sacar de nuevo la foto del fondo |
| `F` | pantalla completa |
| `Q` / `ESC` | salir |

En la vista previa te ves espejado, como en un espejo. A Zoom y Meet la imagen les llega derecha, así que los textos que tengas atrás se leen bien. Si preferís mandarla espejada, usá `--mirror-output`.

### Zoom

Configuración → Video → Cámara → **VanishCam**. Si no aparece, cerrá Zoom del todo y abrilo después de arrancar `vanishcam.sh`.

### Google Meet (Chrome o Firefox)

Primero arrancá `vanishcam.sh` y después abrí Meet. En Configuración → Video elegí **VanishCam**.
Chrome solo muestra la cámara cuando ya está recibiendo video, por eso hay que arrancar la app antes que Meet.

## Opciones útiles

```bash
./vanishcam.sh --camera /dev/video2          # otra webcam (listalas con v4l2-ctl --list-devices)
./vanishcam.sh --width 640 --height 360      # menos carga en PCs viejas
./vanishcam.sh --no-mirror                   # sin espejo, tampoco en la vista previa
./vanishcam.sh --mirror-output               # mandar la imagen espejada a Zoom/Meet
./vanishcam.sh --gesture-debug               # muestra en la terminal qué gesto detecta
```

Si no pasás `--camera`, se usa la primera webcam real y se ignora la cámara virtual.

## Problemas comunes

- **"La cámara virtual no está cargada":** corré `sudo modprobe v4l2loopback`. Si falla, revisá lo de Secure Boot.
- **La webcam está ocupada:** cerrá cualquier otra app que la esté usando (Zoom, Meet, Cheese) antes de arrancar VanishCam. En Zoom o Meet tiene que estar elegida *VanishCam*, no tu webcam.
- **Te borra mal o deja manchas:** usá un fondo fijo y con buena luz. Si se movió la cámara, apretá `ESPACIO`.
- **El gesto de Dragon Ball no entra:** la cara tiene que verse (aunque la mano tape parte de la frente), con los dedos índice y medio juntos y el anular y el meñique doblados. Con `--gesture-debug` la terminal muestra si ve la mano, la cara y la pose.
- **Va lento:** corre solo con el procesador. Bajale la resolución con `--width 640 --height 360`.

## Diferencias con el original

- **Modo Dragon Ball (nuevo, por defecto):** el README original lo describía como *Goku*, pero no estaba en el código. Acá está implementado; `--mode goku` también funciona. El sonido del teletransporte se genera en el momento; si ponés tu propio `assets/teleport.MP3`, usa ese.
- **Gestos sostenidos:** antes alcanzaba un solo cuadro con el gesto, y eso hacía que desaparecieras sin querer.
- **Reaparecer con el gesto y con efecto:** antes solo se podía con `R`, sin efecto.
- **Mejor foto del fondo:** junta 1,5 segundos de cuadros en vez de medio, y espera si todavía hay alguien.
- **Imagen derecha en la llamada:** solo la vista previa va espejada.
- **Mensajes en español** en la terminal.
- **Webcam real:** en Linux se detecta sola, se abre con V4L2 en MJPG y no se confunde con la cámara virtual. `--camera` también acepta rutas como `/dev/video2`.
- **Scripts nuevos:** `install-ubuntu.sh` y `vanishcam.sh` reemplazan a los `.bat` de Windows.
- **Tests:** corren desde la raíz del repo con `python -m unittest`.
- **Lo que sigue sin estar:** el modo *Particles* del README original.
- **Sonido:** el de los efectos sale por tus parlantes, no entra a la llamada.
