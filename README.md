# Ankimio
Aplicación local en español para crear mazos, repasar sin límites diarios y hacer simulacros sin tiempo máximo. Los datos se guardan en SQLite en `data/study.db`.

## Inicio
```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```
Abre el puerto 5000 en tu entorno. No requiere claves ni servicios externos. Es una aplicación personal sin autenticación: no exponer públicamente con datos privados. El servidor incluido es de desarrollo.

## Funciones
- Crear mazos y tarjetas de pregunta/respuesta.
- Explorar cada mazo, buscar por pregunta o respuesta y editar tarjetas. El explorador muestra 25 tarjetas por página; Ctrl + Enter guarda los cambios del editor. También se puede editar la tarjeta actual desde el botón «Editar tarjeta» dentro del repaso, conservando el progreso y si la respuesta ya estaba visible.
- Repasar todo el mazo y reiniciar inmediatamente cuantas veces quieras. En el repaso libre, Espacio muestra la respuesta. Después puedes calificar con Otra vez (1), Difícil (2), Bien (3) o Fácil (4); Espacio elige Bien. Otra vez y Difícil vuelven a la cola de esta sesión sin intervalos de tiempo, y solo Bien/Fácil cuentan como aprendidas. Al dominar todas, se puede reiniciar el mazo completo. Ctrl + Z (o el botón «Deshacer calificación») restaura la tarjeta anterior, el orden de pendientes y el contador, incluso al terminar. Se pueden deshacer varias calificaciones seguidas; el historial se reinicia al salir o comenzar otra vuelta. El atajo no interfiere con deshacer texto en el editor. El progreso de la sesión no se conserva al recargar.
- Simulacros aleatorios con cantidad de preguntas configurable, alternativas A–D y calificación automática al terminar. Los distractores son respuestas distintas de otras tarjetas del mismo mazo (hasta cuatro opciones; mínimo dos respuestas distintas). Las claves se muestran al finalizar. Es recomendable usar preguntas con una única respuesta válida. Los resultados son temporales.
- Importación de texto e imágenes incluidas en `.colpkg` y `.apkg`, tanto antiguos como modernos, incluidas colecciones comprimidas con Zstandard (`collection.anki21b`). Las colecciones modernas se leen con la biblioteca oficial de Anki, que interpreta sus plantillas y tarjetas cloze. Las colecciones antiguas conservan el lector anterior y su representación básica de cloze. Se importan imágenes PNG, JPEG, GIF, WebP, BMP y AVIF y se muestran en el repaso, explorador y simulacros, incluso si la tarjeta solo contiene una imagen. No se importan audio, CSS personalizado, SVG/oclusiones de imagen ni la programación de repasos. No es necesario activar la exportación con compatibilidad antigua para las colecciones modernas probadas.
- El contenido importado se muestra con formato básico e imágenes locales mediante una lista de etiquetas permitidas; no se ejecutan scripts, eventos ni contenido remoto.

## Pruebas
```sh
.venv/bin/python -m unittest discover -s tests -v
```

## Publicación y Netlify
Netlify puede alojar una interfaz estática, pero no ejecuta este servidor Flask persistente ni conserva su SQLite local. Subir este repositorio directamente como sitio estático no permite crear/importar mazos.

Para conservar la arquitectura actual, usar un alojamiento con Python y un disco persistente para `data/` (o configurar `ANKIMIO_DATA` a la ruta del disco). Instalar las dependencias y usar un servidor WSGI de producción en lugar del servidor de desarrollo incluido. Antes de hacer la aplicación pública hay que añadir autenticación y separación de datos por usuario.

Otra opción es separar la interfaz para Netlify y alojar la API Flask con almacenamiento persistente en otro servicio; eso requiere adaptar las URL de la API y configurar el acceso entre ambos orígenes. La aplicación aún no está preparada para esa modalidad ni ha sido desplegada.

### Prueba gratuita en Render (Blueprint)
Este repositorio incluye `render.yaml` con el plan `free`, Gunicorn y una contraseña generada por Render. En el panel de Render, elegir **New → Blueprint**, seleccionar este repositorio, usar la rama `main` y crear los recursos descritos en el archivo.

Cuando el despliegue termine, abrir la URL que Render asigne al servicio. El usuario es `ankimio`; la contraseña se consulta en la variable `ANKIMIO_PASSWORD` de la sección **Environment** del servicio. No compartir esa contraseña ni subirla al repositorio. Esta protección es para un espacio personal compartido; no implementa cuentas independientes.

**Los datos del plan gratuito son temporales**: los mazos creados o importados pueden perderse con reinicios y nuevos despliegues. Usar solo datos de prueba y conservar los archivos originales de Anki. El servicio gratuito también puede tardar en responder al despertar después de estar inactivo. Para guardar datos de forma permanente, cambiar a un plan con disco persistente y configurar `ANKIMIO_DATA` a la ruta montada.

Las pruebas de importación generan archivos con la biblioteca oficial de Anki y verifican paquetes modernos comprimidos, colecciones sin compresión, exportaciones antiguas, tarjetas normales, inversas y cloze, además del rechazo de archivos dañados.


## Imágenes de Anki
Al exportar desde Anki, incluir los archivos multimedia. El importador lee tanto el índice JSON antiguo como el índice protobuf comprimido moderno, verifica las sumas de integridad disponibles y guarda las imágenes junto con los mazos en SQLite. No extrae rutas del paquete al sistema de archivos. Las rutas `/media/<id>` requieren la misma contraseña que la aplicación cuando está configurada. Eliminar todos los mazos elimina también sus imágenes.

Los mazos importados antes de esta función deben importarse de nuevo desde el archivo original, ya que sus imágenes nunca se guardaron. Se avisa cuando una referencia no tiene archivo incluido o usa un formato no compatible. Las imágenes externas enlazadas y SVG no se cargan. Editar el texto de una tarjeta conserva sus imágenes existentes. En el plan gratuito de Render, las imágenes también son temporales junto con el resto de la base de datos.

Si una imagen local falla al cargarse, se reintenta una vez y después se ofrece «Reintentar imagen». Esta recuperación no restaura archivos perdidos por reinicios del alojamiento gratuito; en ese caso hay que reimportar el paquete original.
