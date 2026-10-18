# Ankimio
Aplicación personal en español con temática de One Piece para crear e importar mazos, repasar sin límites de tiempo y hacer simulacros.

## Datos permanentes en Render y Supabase
En producción, **mazos, tarjetas, ediciones e imágenes se guardan en PostgreSQL** mediante `DATABASE_URL`. Se usa el esquema `ankimio`, separado del esquema público de Supabase. Render puede reiniciarse sin eliminar esos datos. Esto requiere que la base externa esté configurada y disponible; el código por sí solo no crea una cuenta ni un proyecto de Supabase.

La aplicación rechaza iniciar con almacenamiento temporal cuando está en Render (`RENDER=true`) o `ANKIMIO_REQUIRE_DATABASE=1`. Si PostgreSQL falla, muestra un error y **no cambia silenciosamente a SQLite**.

### Configuración
1. Crear una cuenta y un proyecto en [Supabase](https://supabase.com/dashboard). Guardar la contraseña de la base de datos de forma segura.
2. En el proyecto, abrir **Connect** y seleccionar la URI de **Session pooler**, compatible con IPv4, puerto **5432**. Usar el usuario completo que muestra Supabase (incluye la referencia del proyecto). Reemplazar el marcador de contraseña por la contraseña de la base; los caracteres reservados de una contraseña deben codificarse como parte de una URI. No usar la clave pública/anon ni una clave de API como sustituto de la conexión PostgreSQL.
3. En Render → servicio Ankimio → **Environment**, añadir **DATABASE_URL** con esa URI. No escribir el valor en GitHub, en el código ni en el chat. Mantener `ANKIMIO_PASSWORD` para proteger la aplicación.
4. Guardar las variables y desplegar la rama `main`. El archivo `render.yaml` declara `DATABASE_URL` como valor que el usuario debe proporcionar; no incluye credenciales.
5. Comprobar que el despliegue esté **Live**, importar un mazo, editar una tarjeta y comprobar que los datos siguen disponibles tras reiniciar el servicio.

Las conexiones remotas usan TLS con verificación completa del certificado y del hostname. Por defecto se pasa explícitamente el archivo de certificados del sistema, evitando diferencias de rutas con el OpenSSL incluido en psycopg-binary. Si el proveedor requiere otra CA, configurar su ruta con `DATABASE_SSLROOTCERT` o `sslrootcert` en la conexión. No desactivar la verificación TLS. La conexión tiene límite de espera y las consultas tienen límites de duración y bloqueo.

El servicio web gratuito puede dormirse y tardar en despertar. Los límites, capacidad y políticas de inactividad de Supabase dependen de su plan; guardar las imágenes en la base también consume su almacenamiento. Conservar los archivos originales de Anki como respaldo. Esta configuración es un espacio personal protegido por una contraseña, no un sistema de cuentas independientes.

### Datos anteriores
La conexión nueva no puede recuperar tarjetas que el servidor temporal ya haya perdido. En ese caso, importar el `.colpkg` original en la aplicación conectada a PostgreSQL y volver a abrir el mazo. Las pestañas antiguas pueden contener identificadores que ya no existen.

Si se conserva un archivo SQLite de Ankimio (`data/study.db`), el script siguiente copia mazos, tarjetas e imágenes a una base PostgreSQL **vacía**, conserva sus identificadores y ediciones y no modifica el archivo original:

```sh
# Configurar DATABASE_URL de forma segura en el entorno antes de ejecutar.
.venv/bin/python migrate_sqlite.py data/study.db
```

La copia es transaccional. Si el destino contiene datos o falla una inserción, se cancela sin sobrescribir los datos existentes. No es un importador de colecciones Anki: recibe exclusivamente una base SQLite de Ankimio.

## Desarrollo local
Sin `DATABASE_URL`, fuera de Render y sin exigir PostgreSQL, usa SQLite local en `data/study.db`:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

También se puede desarrollar con PostgreSQL configurando `DATABASE_URL`. Las tablas se crean automáticamente sin borrar las existentes. En producción se ejecuta Gunicorn, según `render.yaml`.

## Funciones
- Crear mazos y tarjetas.
- Crear tarjetas consecutivamente con Ctrl + Enter.
- Explorar cada mazo, buscar por pregunta o respuesta, navegar 25 tarjetas por página y editar. También se puede editar la tarjeta dentro del repaso sin perder el progreso.
- Repasar sin esperas: Otra vez (1) y Difícil (2) se repiten durante la sesión; Bien (3) y Fácil (4) cuentan como aprendidas. Espacio revela la respuesta y una segunda pulsación elige Bien. Al dominar todas se puede reiniciar el mazo completo.
- Prueba opcional de repasos espaciados y dominio: el interruptor de la biblioteca permite desactivarla en este navegador sin borrar tarjetas ni progreso. «Repaso recomendado» reúne tarjetas nuevas y repasos pendientes; «Repasar todo» sigue disponible sin esperas ni límites.
- El seguimiento diferencia «Nueva», «En aprendizaje», «Aprendida hoy» y «Consolidada». Una tarjeta se considera consolidada tras al menos 3 aciertos en repasos recomendados de días distintos, a lo largo de 7 días o más. Es un indicador basado en tus calificaciones; pulsar Fácil una vez no basta.
- Al terminar una ronda aparece «Repasar las complicadas»: incluye únicamente las tarjetas marcadas como Otra vez o Difícil en esa ronda, aunque luego se hayan acertado. La selección se recalcula al terminar cada ronda de refuerzo. Deshacer una calificación también deshace su marca de dificultad. «Repasar todo de nuevo» recupera siempre el mazo completo, incluso después de un refuerzo. Este seguimiento dura la sesión abierta.
- Ctrl + Z o «Deshacer calificación» restaura la tarjeta anterior y su progreso, incluso al terminar la sesión. Si el seguimiento está activado, también restaura la fecha recomendada y el dominio guardados. No interfiere con la edición de texto. La cola de una ronda y los botones para deshacer son temporales y se reinician al recargar; los mazos, ediciones y progreso de aprendizaje se guardan en la base configurada.
- Simulacros con hasta cuatro alternativas basadas en otras respuestas del mismo mazo; requieren al menos dos respuestas distintas. Calificación automática y claves al terminar. Espacio avanza después de marcar una alternativa. Los resultados del simulacro son temporales.
- Eliminar todos los mazos y sus imágenes, previa confirmación.
- Guardado del editor con límite de espera, opción de dejar de esperar, conservación del texto ante errores y reintento.

### Repasos espaciados opcionales
El seguimiento está activado inicialmente y puede desmarcarse en «Probar repasos espaciados y seguimiento». Al desactivarlo, se ocultan las recomendaciones y el dominio y se dejan de registrar calificaciones; al reactivarlo se recupera el progreso anterior. Esta preferencia se guarda en el navegador. Los simulacros no alteran el seguimiento.

Los intervalos sugeridos para Bien siguen 1, 3, 7, 14, 30, 60 y 90 días; Fácil sugiere el escalón siguiente. Otra vez o Difícil reinician la secuencia y mantienen la tarjeta pendiente hoy, además de repetirla dentro de la ronda. Si finalmente se acierta después de una dificultad del mismo día, el siguiente repaso será mañana. Repetir antes de la fecha recomendada no añade días de aciertos ni retrasa la fecha. Se usa el día local de la zona horaria del navegador, calculado con el reloj del servidor.

Las fechas y el dominio se guardan por tarjeta en `card_progress`. Las operaciones de `review_events` permiten deshacer y reintentar solicitudes sin contar dos veces una respuesta perdida. Las escrituras son transaccionales y una pestaña con progreso antiguo no puede sobrescribir una sesión más reciente. Un fallo de guardado conserva la tarjeta en pantalla y ofrece Reintentar o volver a Mis mazos. Eliminar todos los mazos elimina también estos registros. La migración de SQLite a PostgreSQL conserva estas tablas cuando existen; las bases anteriores siguen siendo compatibles.

Las tablas nuevas se crean automáticamente sin cambiar el contenido de tarjetas, mazos o imágenes. Las ediciones de texto conservan el seguimiento de la tarjeta. La opción se puede retirar del código después de la prueba sin borrar esos contenidos.

## Importación e imágenes
Admite `.colpkg` y `.apkg` antiguos y modernos, incluidos paquetes comprimidos con Zstandard. Las colecciones modernas se leen con la biblioteca oficial de Anki; las antiguas conservan una representación básica de cloze.

Exportar desde Anki con los archivos multimedia incluidos. Se admiten PNG, JPEG, GIF, WebP, BMP y AVIF. Audio, SVG, oclusiones de imagen, estilos personalizados y programación de repasos no se importan. El contenido se muestra con una lista de etiquetas permitidas, sin scripts, eventos ni recursos externos.

Las imágenes están en la misma base que las tarjetas. `/api/decks/<id>/study` entrega las tarjetas y sus imágenes en una respuesta autenticada; el navegador conserva una copia de las imágenes para la sesión. La edición guarda referencias permanentes, no direcciones temporales del navegador. Los mazos importados antes del soporte de imágenes deben importarse de nuevo para recuperarlas.

## Pruebas
```sh
.venv/bin/python -m unittest discover -s tests -v
```

Para ejecutar también las pruebas de PostgreSQL y migración, usar una base **exclusiva para pruebas**, configurada mediante `ANKIMIO_TEST_DATABASE_URL`. La suite ignora la variable de producción `DATABASE_URL` y elimina datos en su destino de pruebas. Nunca apuntarla a la base de uso personal.

Las pruebas cubren paquetes exportados por Anki, imágenes, edición, transacciones, configuración de persistencia y TLS, migración sin pérdida de identificadores, intervalos de repaso, dominio en días distintos, reintentos, conflictos y deshacer persistente. Las pruebas específicas de SQLite se omiten al probar PostgreSQL; las de migración PostgreSQL se omiten cuando no hay una base de pruebas.

## Netlify
Este servidor Flask necesita un alojamiento Python. Netlify puede servir una interfaz separada, pero subir este repositorio como sitio estático no ejecuta la API. La configuración incluida usa Render para la aplicación y PostgreSQL externo para la persistencia.


### Si Render no conecta con Supabase
Los errores de inicio muestran un diagnóstico seguro: `PG_NETWORK` (conectividad, proyecto activo y pooler IPv4), `PG_AUTH` (contraseña de la base), `PG_USER` (usuario completo del pooler), `PG_DNS` (hostname), `PG_TLS` (certificado/TLS), `PG_PERMISSIONS` (permisos), o `PG_POOLER` (parámetros no aceptados). No se imprimen las credenciales del controlador. Los límites de consulta y el esquema se configuran mediante `SET LOCAL` después de conectar, en lugar de parámetros de inicio que algunos poolers rechazan.


### Certificado CA de Supabase en Render
Si el diagnóstico es `PG_TLS_TRUST`, descargar el certificado CA desde la configuración SSL de la base de datos de Supabase. En Render → Environment → Secret Files, añadir el certificado como `supabase-ca.crt` y configurar `DATABASE_SSLROOTCERT=/etc/secrets/supabase-ca.crt`. El archivo debe contener el certificado CA público en PEM, no una clave privada. No poner esta ruta al final de `DATABASE_URL` sin codificarla; la variable independiente evita ese problema. Guardar y volver a desplegar.

`PG_TLS_CA_FILE` indica que el archivo CA no existe o no se puede cargar; `PG_TLS_HOST` indica que el certificado no coincide con el hostname. La verificación completa sigue activada: no se recurre a `sslmode=disable` ni a aceptar certificados sin verificar.
