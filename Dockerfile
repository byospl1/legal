# Imagen de producción: Python + LibreOffice headless (resuelve la
# conversión .docx -> PDF que en el sandbox de desarrollo está rota) +
# gunicorn como servidor WSGI real (en vez de app.run(), que es solo para
# desarrollo local).
FROM python:3.11-slim

# libreoffice: conversión docx->pdf (motor/pdf_tools.py busca el binario
#   "soffice" que este paquete deja en /usr/bin/soffice).
# fonts-liberation + fonts-crosextra-carlito: sustitutos métricamente
#   compatibles con Times New Roman/Arial — sin ellos LibreOffice re-wrappea
#   el texto con una fuente distinta y rompe el layout calibrado a mano
#   (ver motor/exhibit_builder._estimar_lineas_visuales en CLAUDE.md).
# fonts-liberation2 trae "Liberation Serif", que Word/LibreOffice mapean
#   automáticamente cuando declaras "Times New Roman" y la fuente real no
#   está instalada.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    fonts-liberation \
    fonts-liberation2 \
    fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY . .

# Los datos reales (case_store/, output/, firmas/, usuarios/) viven en
# volúmenes montados por docker-compose.yml, NO dentro de la imagen — así
# sobreviven a un rebuild/redeploy. Se crean vacíos acá por si el volumen
# todavía no existe en el primer arranque.
RUN mkdir -p case_store output input usuarios firmas/abogados firmas/preparadores

EXPOSE 5000

# 2 workers: LibreOffice no soporta bien conversiones concurrentes desde el
# mismo proceso soffice, así que más workers no ayuda a la parte lenta
# (conversión a PDF) — solo evita que una request de solo-lectura (ej.
# listar casos) se bloquee detrás de una generación de documento en curso.
# --timeout 120: una conversión a PDF con evidencia grande puede tardar.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
