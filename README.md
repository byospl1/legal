# Sistema de llenado de Tabs — EOIR

Genera portadas de expediente EOIR (I-589) a partir de una plantilla `.dotx`,
capturando los datos del caso una vez por cliente y los datos de cada Tab
(exhibits) por corrida. Interfaz web local con botones — no requiere saber
programar para usarlo día a día.

## Requisitos (Windows)

1. **Python 3.11 o superior** — https://www.python.org/downloads/
   Al instalar, marca la casilla **"Add Python to PATH"**.
2. **LibreOffice** (gratis) — https://www.libreoffice.org/download/download/
   Se usa para convertir cada documento generado a PDF de verificación.
3. **Poppler for Windows** — https://github.com/oschwartz10612/poppler-windows/releases
   Se usa para generar las imágenes de cada página del PDF (para revisar
   visualmente antes de dar el documento por bueno). Descarga el `.zip`,
   descomprímelo (ej. en `C:\poppler`) y agrega la carpeta `Library\bin` de
   adentro al PATH del sistema (Panel de control → Sistema → Configuración
   avanzada → Variables de entorno → `Path` → Nueva).

Si LibreOffice o Poppler no están instalados, el sistema igual genera el
`.docx` — simplemente no podrás ver el PDF de verificación automático y
deberás abrir el Word manualmente para revisarlo.

## Instalación

1. Descarga/clona esta carpeta completa a tu computadora.
2. Doble clic en **`instalar.bat`**. Esto crea un entorno de Python aislado
   (`venv/`) e instala las dependencias necesarias.

## Uso diario

1. Doble clic en **`iniciar.bat`**.
2. Se abre tu navegador en `http://127.0.0.1:5000` con el formulario.
3. **Paso 1 — Caso**: elige un caso existente o captura uno nuevo (nombre,
   A#, corte, juez, próxima audiencia, abogado, preparador) y da clic en
   *Guardar caso*.
4. **Paso 2 — Generar documento**: elige la plantilla y el título del
   documento. Si la plantilla tiene tabla de exhibits, agrega uno o más
   Tabs: letra, páginas y las categorías que aplican (Country Conditions,
   Form of Identity, etc.) — si eliges "Form of Identity" te pedirá el país.
5. Clic en **Generar documento**. El sistema llena el Word, lo valida, lo
   convierte a PDF y genera una imagen por página para que la revises antes
   de usarlo — así se detectaron los bugs reales durante el desarrollo.
6. Descarga el `.docx` o el PDF desde los enlaces que aparecen, o desde la
   tabla de "Documentos generados" más abajo (también sirve para corridas
   anteriores).

Para dejar el sistema corriendo, no cierres la ventana negra (consola) que
abrió `iniciar.bat`. Para apagarlo, ciérrala.

## Control de accesos (login)

El sistema pide **usuario y contraseña** al entrar, para controlar quién lo
usa y dejar registro de quién generó cada documento.

**La primera vez, antes de poder entrar, crea al menos un usuario:**

1. Doble clic en **`gestionar-usuarios.bat`**.
2. Elige la opción **1 (Crear un usuario nuevo)** y escribe usuario, nombre
   y contraseña. Repite por cada persona del despacho que vaya a usarlo.
3. Desde ahí también puedes ver la lista, cambiar contraseñas o borrar
   usuarios.

Después, `iniciar.bat` pedirá login normalmente. Las contraseñas se guardan
**cifradas** en `usuarios/usuarios.json` (nunca en texto plano) y ese
archivo no se sube al repositorio.

> **Nota de alcance:** con el login local, las cuentas viven en cada
> computadora por separado. Si quieres **administrar las cuentas desde un
> solo lado (por internet)** y que varias máquinas compartan los mismos
> usuarios, usa la opción de Firebase de abajo.

### Opción avanzada: validar el login con Firebase (por internet)

En vez del login local, puedes validar usuario y contraseña **por internet
contra Firebase Authentication** (un servicio gratuito de Google). Ventaja:
administras todas las cuentas desde un solo panel web, y varias computadoras
del despacho comparten los mismos usuarios. Requiere internet al iniciar
sesión.

**Configuración (una sola vez, la hace el administrador):**

1. Entra a https://console.firebase.google.com/ con una cuenta de Google
   (gratis, sin tarjeta) y crea un proyecto (ej. "Kostiv EOIR"). Puedes
   desactivar Google Analytics.
2. Menú lateral → **Build → Authentication → Comenzar (Get started)**.
3. En **Sign-in method**, habilita **Correo electrónico/contraseña**
   (Email/Password) y guarda.
4. Pestaña **Users → Agregar usuario**: crea una cuenta (correo +
   contraseña) por cada persona del despacho. **Aquí administras las cuentas
   siempre** (agregar, quitar, resetear contraseña).
5. Consigue la *Web API key*: ícono de engranaje (**Configuración del
   proyecto**) → pestaña **General** → sección **Tus apps** → si no hay una
   app web, crea una con el ícono `</>` (cualquier apodo, no necesitas
   Hosting) → copia el valor **apiKey** (empieza con `AIza...`).
6. En la carpeta del proyecto, crea un archivo de texto llamado exactamente
   **`firebase-api-key.txt`** y pega adentro **solo esa apiKey**, en una sola
   línea, sin comillas. Guárdalo.
7. Doble clic en **`iniciar.bat`**: ahora la pantalla de login pedirá
   **correo electrónico** y contraseña, validados contra Firebase.

**Notas:**

- Los usuarios inician sesión con su **correo** (el que creaste en Firebase),
  no con un usuario corto.
- La *Web API key* no es secreta (es la misma que llevaría cualquier app
  cliente), pero es específica de tu instalación — por eso
  `firebase-api-key.txt` no se sube al repositorio. Pon ese archivo solo en
  las computadoras del despacho.
- Si no hay internet al momento de entrar, aparece un aviso claro y no se
  puede iniciar sesión (la validación es en línea).
- Para volver al login local, borra o renombra `firebase-api-key.txt`.
- `gestionar-usuarios.bat` es solo para el login **local**; en modo Firebase
  las cuentas se administran en el panel de Firebase.

#### Candado "1 cuenta = 1 computadora" (evitar que se compartan cuentas)

Opcionalmente, puedes atar cada cuenta a **una sola computadora**: la primera
vez que alguien entra con su cuenta, queda registrada a esa máquina; si
intentan usar la misma cuenta en otra computadora, se rechaza. Así una cuenta
no se puede "pasar" a otra persona. Usa **Firestore** (también gratis, del
mismo proyecto de Firebase). Solo aplica al uso local (una instalación por
máquina).

**Configuración (una sola vez, la hace el administrador):**

1. En la consola de Firebase → **Build → Firestore Database → Crear base de
   datos** → modo **producción** → elige la ubicación → listo.
2. Pestaña **Rules** (reglas) y pega exactamente esto (deja crear su registro
   a cada usuario una sola vez, pero **impide moverlo o borrarlo** — solo tú,
   desde la consola, puedes liberarlo):
   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /device_bindings/{uid} {
         allow read, create: if request.auth != null && request.auth.uid == uid;
         allow update, delete: if false;
       }
     }
   }
   ```
   Da clic en **Publicar**.
3. En la carpeta del proyecto, crea un archivo de texto llamado exactamente
   **`firebase-project-id.txt`** con el **ID del proyecto** adentro (una sola
   línea; es el `projectId` de la config de Firebase, ej. `tabsmaster-12345`).
4. Doble clic en `iniciar.bat`: ahora, además de validar el login, atará cada
   cuenta a la computadora donde entra por primera vez.

**Para liberar una cuenta** (cambio de computadora, se dañó la PC, etc.):

- En la consola de Firebase → **Firestore Database** → colección
  **`device_bindings`** → busca el documento de esa persona (por su ID de
  usuario) y **bórralo**. La próxima vez que entre, quedará atada a la nueva
  computadora.

> El ID de la computadora se guarda en el perfil de Windows del usuario
> (`%USERPROFILE%\.eoir-device-id`), así que sobrevive a actualizaciones del
> programa. Si no hay internet al iniciar sesión, no se puede entrar (la
> verificación es en línea, igual que el login).

## Agregar una plantilla `.dotx` nueva

1. Copia el archivo a `plantillas/<id-de-la-plantilla>/archivo.dotx`.
2. Desde la carpeta del proyecto, con el entorno activado:
   ```
   venv\Scripts\activate
   python -m motor.analyze_template "plantillas\<id>\archivo.dotx" --template-id <id>
   ```
3. Esto genera `field_map.json` con un borrador de los campos detectados
   (simples, agrupados por bookmark, anidados, candidatos a sincronía
   manual, campos automáticos de Word que no se deben tocar). **Revísalo a
   mano**: completa los `"nombre": null` con el nombre semántico del campo
   (ej. `"corte_sede"`, `"juez"`) — el script detecta la estructura pero no
   adivina el significado de cada campo.
4. Si la plantilla tiene tabla de exhibits con categorías fijas de
   contenido (como `i589-tab-cover`), captura el XML literal de cada
   categoría en `plantillas/<id>/fragments/` siguiendo el mismo patrón que
   `plantillas/i589-tab-cover/fragments/` y ajusta
   `motor/exhibit_builder.py` — este paso es manual porque cada plantilla
   tiene su propio contenido fijo.
5. Agrega la plantilla a `plantillas/registro.json`.

## Editar un `.dotx` a mano en Word

Si abrís un `.dotx` con doble clic (o "Abrir" normal), Word no abre el
archivo original: crea un **documento nuevo basado en la plantilla**
(`Documento1`, etc.). Por eso al guardar Word pide "Guardar como" con un
nombre nuevo en vez de dejarte sobrescribir la plantilla — es el
comportamiento estándar de Word con archivos de plantilla, no una
restricción del proyecto.

Para editar el `.dotx` original:

1. Clic derecho sobre el archivo → **Abrir** (no doble clic), o desde Word
   con **Archivo → Abrir** navegando al archivo.
2. Alternativa: renombrar temporalmente la extensión a `.docx`, editar, y
   volver a ponerle `.dotx` al terminar.

Las plantillas en `plantillas/*/*.dotx` y `*.docx` son las originales del
despacho — hacé backup antes de tocarlas a mano, cualquier cambio de
layout ahí afecta a todos los documentos que se generen después.

## Estructura de carpetas

```
/plantillas/<id>/archivo.dotx       plantilla original (no se modifica)
/plantillas/<id>/field_map.json     mapa de campos (generado + revisado a mano)
/plantillas/<id>/fragments/         XML literal de bloques fijos (tabla de exhibits, etc.)
/catalogos.json                     catálogos fijos (corte, juez, abogado, preparador, títulos)
/case_store/<id>.json               datos de cada caso (NO se sube a git — datos de clientes)
/output/                            documentos generados (.docx + .pdf + imágenes de verificación)
/input/                             carpeta libre para que dejes ahí documentos de entrada si los necesitas
/motor/                             el motor (analyze_template, fill_engine, exhibit_builder, etc.)
/app.py                             servidor web local (Flask)
/static/                            interfaz HTML/JS
```

## Pendientes de negocio (no técnicos)

Ver la especificación original — quedan dos decisiones para el despacho:

1. **¿La firma litiga fuera de California?** Los catálogos de `corte_sede`
   y `juez` en `catalogos.json` solo traen las sedes/jueces de California
   que vienen en la plantilla original. Los campos son de texto libre
   (`comboBox`), así que el sistema **sí permite** escribir cualquier corte
   o juez aunque no esté en la lista — pero si alguien abre el Word y usa
   el desplegable de la interfaz de Word, solo verá las opciones de
   California. Si la firma litiga en otros estados regularmente, hay que
   ampliar `catalogos.json` (y opcionalmente el `.dotx`, si se quiere que el
   desplegable de Word también las muestre).
2. **Fecha del FBI Fingerprint** en la categoría `fee` — hoy sigue quemada
   como en el original (`06/04/2026`, ver
   `plantillas/i589-tab-cover/fragments/item_fbi_fingerprint.xml`). Si debe
   ser variable por caso, avisa y se agrega como campo capturable.
