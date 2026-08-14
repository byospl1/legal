Firmas escaneadas (PNG) — abogados y preparadores
===================================================

Coloca aquí las imágenes de firma en formato PNG, con fondo transparente
de preferencia. El sistema las inserta automáticamente en los documentos
que las usan (por ahora, "Webex — Motion for Webex Appearance") según
quién esté seleccionado como abogado/preparador del caso — no hace falta
tocar ningún otro archivo ni reiniciar el programa, solo colocar el PNG
con el nombre correcto y volver a generar el documento.

Dónde va cada una y cómo se debe llamar el archivo
---------------------------------------------------

firmas/abogados/{nombre y apellido del abogado}.png

  El nombre del archivo debe ser la parte del nombre ANTES de la primera
  coma en el catálogo de abogados (catalogos.json). Ejemplos:

    Catálogo: "John Negron, Esq. (SBN 21806)"
    Archivo:  firmas/abogados/John Negron.png

    Catálogo: "Zahira Rodriguez Feliciano, Esq., LL.M. (SBN 20327)"
    Archivo:  firmas/abogados/Zahira Rodriguez Feliciano.png

firmas/preparadores/{nombre del preparador}.png

  El nombre del archivo es igual al nombre tal como aparece en el
  catálogo de preparadores (catalogos.json). Ejemplos:

    Catálogo: "Lorenzo Bracamontes"
    Archivo:  firmas/preparadores/Lorenzo Bracamontes.png

    Catálogo: "Kevin Calvillo"
    Archivo:  firmas/preparadores/Kevin Calvillo.png

Si un abogado o preparador no tiene su PNG todavía, el documento se
genera igual — la línea de firma queda en blanco (con el subrayado),
lista para firmarse a mano, exactamente como antes.

Recomendaciones de la imagen
-----------------------------
- Formato PNG (no JPG).
- Fondo transparente si es posible (se ve mejor sobre el texto).
- No hace falta que sea pequeña: el sistema la escala sola para que quepa
  en la línea de firma sin deformarse.
