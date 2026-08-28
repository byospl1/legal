# INICIA AQUI

Si necesitas más información, detectas un error o quieres solicitar una mejora, coloca un **request (Issue)** en el repositorio: [abrir un request en GitHub](https://github.com/byospl1/legal/issues/new).

## Qué es este programa

Sistema web local para preparar portadas de Tabs y documentos de apoyo de expedientes EOIR/I-589. Está diseñado para **Windows 10/11**: procesa la información en la computadora, abre una interfaz en el navegador y no debe publicarse directamente en Internet.

## 1. Descargar y preparar la carpeta

1. Descarga el repositorio privado completo desde GitHub (ZIP) o clónalo con Git.
2. Si descargaste ZIP, descomprímelo por completo. **No ejecutes los `.bat` dentro del ZIP**.
3. Conserva todos los archivos y subcarpetas juntos, especialmente `plantillas/`, `motor/`, `static/`, `requirements.txt`, `instalar.bat` e `iniciar.bat`.
4. Abre la carpeta que contiene directamente `instalar.bat`; no abras una carpeta superior o interna.

No subas al repositorio datos de clientes, PDFs, documentos generados, contraseñas ni los archivos locales de casos.

## 2. Instalar por primera vez

1. Haz doble clic en **`instalar.bat`**.
2. Espera a que termine. El instalador comprueba o instala automáticamente:
   - Python 3;
   - LibreOffice, para convertir los documentos a PDF;
   - Poppler, para contar/renderizar páginas PDF;
   - un entorno virtual `venv/` y las dependencias de Python.
3. Si Windows solicita autorización, acéptala solo para esas instalaciones.
4. Debe aparecer el mensaje **“Instalación terminada y verificada”**. Si aparece un error, corrígelo y vuelve a ejecutar el archivo.

El instalador necesita Internet, `winget` (App Installer de Windows) y permisos para instalar software. En computadoras corporativas con instalaciones bloqueadas, políticas de TI, Windows antiguo o sin Internet puede ser necesario que el administrador de la computadora instale los requisitos manualmente.

## 3. Cuentas y primer inicio

### Inicio normal con Firebase

El repositorio incluye `firebase-api-key.txt` y `firebase-project-id.txt`. No los borres, renombres ni reemplaces: activan el login por Firebase y el candado de una cuenta por computadora.

El administrador crea y administra las cuentas desde **Firebase Console → Authentication → Users → Agregar usuario**. Cada persona entra con el correo y contraseña que le entregue el administrador. Para que solo el administrador cree cuentas, debe desactivar el registro y borrado por usuarios finales en la configuración de Authentication.

La primera entrada de una cuenta en una computadora registra esa cuenta en ese equipo. El mecanismo usa un identificador local de Windows (`%USERPROFILE%\\.eoir-device-id`), **no la dirección IP**. Cambiar de red no cambia el equipo vinculado. Para autorizar otra computadora, el administrador elimina el documento correspondiente en Firebase → Firestore → colección `device_bindings`; después la cuenta puede iniciar sesión una vez en la nueva PC.

El login de Firebase y la comprobación del dispositivo necesitan Internet. No compartas las credenciales entre personas.

Al iniciar sesión también se comprueba la última versión obligatoria. Si existe una actualización, se descarga desde Firebase, se verifica, la aplicación se cierra y vuelve a abrir automáticamente. Espera a que el navegador recargue el login y entra otra vez. La actualización conserva casos, documentos generados, firmas, usuarios y configuración local.

Las instalaciones hechas antes de que existiera este actualizador necesitan recibir esta versión manualmente una sola vez. Antes de reemplazar su carpeta, respalda `case_store/`, `output/`, `input/`, `firmas/`, `usuarios/` y los archivos `firebase-*.txt`; restáuralos en la nueva copia y ejecuta `instalar.bat`. Las versiones posteriores se instalarán automáticamente.

### Inicio local alternativo

Si una copia no tiene `firebase-api-key.txt`, `iniciar.bat` usa usuarios locales. Antes del primer inicio:

1. Ejecuta **`gestionar-usuarios.bat`**.
2. Elige `1` para crear un usuario y captura usuario, nombre y contraseña.
3. Usa las opciones `2`, `3` y `4` para listar usuarios, cambiar una contraseña o eliminar un usuario.

Las cuentas locales quedan separadas en cada computadora. Las contraseñas se almacenan con hash en `usuarios/usuarios.json`; ese archivo no debe subirse a GitHub.

## 4. Iniciar y cargar el sistema

1. Haz doble clic en **`iniciar.bat`** desde la raíz del repositorio.
2. Se abrirá el navegador en [http://127.0.0.1:5000](http://127.0.0.1:5000). Si no se abre, escribe esa dirección manualmente.
3. Inicia sesión con Firebase o con el usuario local, según el modo configurado.
4. Mantén abierta la ventana negra de la consola mientras uses el programa. Esa ventana es el servidor; cerrarla apaga la aplicación.

Si el navegador muestra una sesión expirada, vuelve a iniciar sesión. Si la dirección no responde, verifica que la consola siga abierta y que ningún otro programa esté usando el puerto 5000.

## 5. Crear o cargar un caso

En **Paso 1 — Caso**:

- Para continuar un caso, escribe parte del nombre o del A# en **Caso existente** y elige el resultado.
- Para comenzar otro expediente, pulsa **Nuevo caso**.
- Captura el **Nombre del cliente**, preferentemente `APELLIDO, Nombre`.
- Captura el **A#**. El sistema lo formatea como `A 000-000-000` y valida 8 o 9 dígitos.
- Captura **Corte / sede**, **Juez** y la **Próxima audiencia** tal como aparecen en el portal EOIR, incluyendo fecha, hora, tipo y modalidad.
- Selecciona el **Abogado** y captura el **Preparador**.
- Si existen co-aplicantes, pulsa **+ Agregar rider** y agrega nombre y A# de cada uno.
- Pulsa **Guardar caso** antes de generar documentos.

El caso conserva los datos generales, los riders y la sugerencia de la siguiente página. La sugerencia se puede corregir manualmente antes de cada generación.

## 6. Generar Tabs de I-589

Después de guardar el caso aparece **Paso 2 — Generar documento**.

1. Selecciona la plantilla **Portada de Tab — I-589 (Asilo)**.
2. Elige el **Título del documento** general.
3. En **¿En qué página empieza este lote?**, confirma o corrige la página inicial.
4. Pulsa **+ Agregar Tab** por cada exhibición.
5. En cada Tab captura o revisa:
   - letra (`A`, `B`, `C`, etc.);
   - páginas, si no se adjunta evidencia (por ejemplo, `15-29`);
   - título específico del documento;
   - una o varias categorías de contenido.
6. Si adjuntas evidencia, el sistema cuenta las páginas y calcula automáticamente el rango; revisa la página inicial y no escribas un rango contradictorio.
7. Deja marcada **Generar cada Tab como un archivo separado** si vas a imprimir o archivar cada Tab por separado. Si la desmarcas, se genera un documento conjunto cuando la evidencia lo permite.
8. Marca **Generar también el PDF de verificación** para obtener el PDF junto con el `.docx`.
9. Pulsa **Generar documento** y espera a que termine.

### Categorías disponibles

- **I-589 Application**: la solicitud I-589.
- **Country Conditions**: `Country Reports on Human Rights Practice` y `OSAC Crime and Safety Report`. Captura país y año de cada informe; si solo adjuntas uno, el otro puede quedar vacío. El sistema puede sugerir país y año al leer el PDF, pero debes verificarlos.
- **Form of Identity**: por cada persona del caso (Respondent líder y cada rider), elige `Passport`, `Birth Certificate` o `ID` y adjunta el PDF. Puedes agregar más de un documento por persona.
- **Supplemental Evidence**: documentos de apoyo por persona o sin persona asociada. Elige `Declaration`, `Psychological Report` o `News`; para `News` revisa y corrige el título de la noticia.
- **Fee**: `Fee Receipt` y/o `FBI Fingerprint`. Elige `Initial` o `Annual` cuando corresponda; el sistema puede sugerirlo al leer el recibo. También puede solicitar la fecha de Biometrics Compliance para cada persona.

Los archivos de evidencia deben ser PDF. La aplicación cuenta las páginas, inserta la evidencia después de la página divisoria `EXHIBIT A/B/...` y numera las páginas. Si un Tab tiene evidencia, se genera automáticamente un PDF separado para ese Tab; esto evita mezclar evidencia detrás de la divisoria equivocada.

Límites predeterminados: 50 MB por solicitud y hasta 2,000 páginas por PDF. La evidencia subida es temporal y se elimina al reiniciar el servidor o después de 24 horas; si reinicias antes de generar, vuelve a subirla.

## 7. Revisar y descargar

Al terminar, revisa los mensajes de validación y abre todos los `.docx`, PDFs y avances de página disponibles. Comprueba nombres, A#, letras, rangos, país, años, títulos, orden de documentos, números de página, fuentes y saltos de página antes de usar el archivo.

Los resultados quedan en `output/` y aparecen en **Documentos generados**. Descarga el `.docx` editable y el PDF cuando se haya solicitado. El historial permite volver a descargar corridas anteriores; **Eliminar** borra esa salida y no debe usarse si todavía necesitas el archivo.

## 8. Otras plantillas

Selecciona la plantilla correspondiente y completa sus campos adicionales antes de generar:

- **Webex — Motion for Webex Appearance**: captura el caso y, si aparecen exhibits, sube sus PDFs. Indica la página donde empieza la evidencia de la moción.
- **Respondent's Written Pleadings**: completa fecha del NTA, alegaciones admitidas, cargos de removibilidad, designación del país de remoción, formas de alivio, horas estimadas, idioma/dialecto del intérprete, traductor, firma abreviada y documento traducido.
- **EOIR-33 — Change of Address/Contact Information Form**: completa dirección anterior y actual, teléfonos/correos si aplican, y la dirección vigente de la corte. Indica si se presentará mediante ECAS. Si eliges `No`, la dirección de servicio a OPLA/ICE es obligatoria.
- **Motion to Withdraw as Counsel**: elige `No Cooperation`, `Cancelation of Services` u `Only Location Known` y completa los campos de esa variante. `Only Location Known` está marcado como borrador: revísalo con un abogado antes de usarlo. Si la variante tiene exhibits, sube los PDFs desde su sección de evidencia.

## 9. Privacidad y copias de seguridad

- Los casos se guardan localmente en `case_store/` y, en Windows, se cifran por defecto con DPAPI ligado a la cuenta de Windows.
- Cada guardado conserva un respaldo `.json.bak`; el botón **Eliminar caso** borra el caso y su respaldo.
- Los documentos finales permanecen en `output/` hasta que los elimines. Haz copias de seguridad protegidas y limita el acceso a la carpeta.
- No publiques la aplicación en una IP pública ni abras el puerto 5000 al exterior: el servidor está pensado para `127.0.0.1`.
- Protege la computadora con contraseña y, si es posible, BitLocker. No envíes por request datos identificables de clientes; adjunta únicamente capturas anonimizadas y mensajes de error.

El sistema automatiza el llenado y la organización; no sustituye la revisión legal. El abogado debe validar el contenido y el documento final antes de presentarlo.

## 10. Detener, reiniciar y solucionar problemas

- **Detener**: cierra la ventana negra de `iniciar.bat`.
- **Reiniciar**: vuelve a ejecutar `iniciar.bat`; la evidencia temporal deberá subirse otra vez.
- **`winget` no encontrado**: actualiza o instala **App Installer** desde Microsoft Store y vuelve a ejecutar `instalar.bat`.
- **No existe `venv/`**: ejecuta `instalar.bat` desde la raíz correcta del repositorio.
- **Python se instaló pero no aparece**: cierra la consola, abre una nueva y ejecuta de nuevo `instalar.bat`.
- **No puede iniciar sesión**: comprueba Internet, correo/contraseña y que la cuenta exista en Firebase; en modo local, crea la cuenta con `gestionar-usuarios.bat`.
- **La actualización obligatoria falla**: vuelve a intentarlo con Internet estable. Si persiste, envía al administrador el contenido de `%LOCALAPPDATA%\EOIRTabs\update.log` y `_update\last_error.txt`, después de verificar que no incluyan datos de clientes.
- **No se genera el PDF**: verifica que LibreOffice esté instalado y revisa el error mostrado en la consola. Conserva el `.docx` para revisión manual.
- **No aparecen las páginas de evidencia**: genera antes de reiniciar; los PDFs temporales no sobreviven al reinicio.
- **Necesitas ayuda o una mejora**: abre un [request (Issue) en el repositorio](https://github.com/byospl1/legal/issues/new), indicando versión/commit, Windows, pasos para reproducir y el mensaje de error, sin datos de clientes ni contraseñas.

## 11. Desarrolladores: agregar una plantilla nueva

Esta sección es solo para quien mantiene el repositorio; el usuario diario no debe modificar `plantillas/` ni `motor/`.

1. Copia el `.dotx` o documento base a `plantillas/<id>/`.
2. Con el entorno virtual activo ejecuta:

   ```bat
   venv\Scripts\activate
   python -m motor.analyze_template "plantillas\<id>\archivo.dotx" --template-id <id>
   ```

3. Revisa y completa manualmente `field_map.json`; el analizador detecta estructura, pero no conoce el significado legal de cada campo.
4. Si la plantilla necesita tabla de exhibits, captura sus fragmentos XML en `plantillas/<id>/fragments/` y adapta `motor/exhibit_builder.py`.
5. Registra la plantilla en `plantillas/registro.json`.
6. Ejecuta las pruebas desde la raíz:

   ```bat
   venv\Scripts\activate
   python tests\run_tests.py
   ```

7. Prueba manualmente login, creación/carga de caso, generación con y sin evidencia, PDF, descarga y eliminación antes de publicar cambios.

## 12. Administradores: activar las actualizaciones obligatorias

El código del actualizador ya está incluido, pero la distribución privada requiere una configuración única en Firebase y GitHub:

1. En Firestore permite lectura autenticada de `app_config/windows_update` y `app_updates/{version}/chunks/{chunkId}`; conserva las escrituras bloqueadas para clientes.
2. Crea una cuenta de servicio de Google dedicada a publicar paquetes, con el rol `Cloud Datastore User`.
3. En GitHub Actions agrega el secret `FIREBASE_SERVICE_ACCOUNT_JSON` y las variables `FIREBASE_PROJECT_ID` y `FIREBASE_AUTO_UPDATE_ENABLED=true`.
4. Ejecuta el workflow **Publicar actualización obligatoria de Windows**. Desde entonces, cada push a `main` publica el ZIP fragmentado en Firestore y obliga a las PCs a instalarlo en el siguiente login con Internet.

Las reglas exactas y el procedimiento completo están en `README.md`, sección **Actualizaciones obligatorias de Windows**. No pongas la clave JSON de la cuenta de servicio dentro del repositorio ni en las computadoras de los usuarios.
