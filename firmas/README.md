# Firmas escaneadas — cómo nombrar los archivos

> **Nota:** la firma del paralegal/preparador (subcarpeta `preparadores/`)
> ya **no** se inserta en ningún template — se quitó de los `field_map.json`
> porque la imagen se sobreponía con otro texto del documento. Esta carpeta
> y el código que la lee siguen existiendo (por si se necesita reactivar
> más adelante), pero hoy ningún documento generado la usa. Solo la firma
> del abogado (`abogados/`) sigue activa.

Esta carpeta guarda las firmas escaneadas que el sistema pega automáticamente
en los documentos generados (en vez de dejar la línea en blanco). Hay dos
subcarpetas, una por tipo de firmante:

```
firmas/
  abogados/       <- firma del abogado que aparece en el caso
  preparadores/   <- firma del paralegal/preparador del caso (también se usa
                      para el "SIGN HERE" del Proof of Service del EOIR-33)
```

**Formato del archivo: siempre `.png`** (no `.jpg`, no `.jpeg`, no `.pdf`).
Si tu firma está en otro formato, conviértela a PNG antes de guardarla aquí
— idealmente con fondo transparente, pero un fondo blanco normal también
funciona bien.

## Cómo se llama el archivo

El nombre del archivo (sin la extensión `.png`) debe ser **exactamente**
el nombre con el que esa persona aparece en el sistema — ver el detalle de
cada carpeta abajo. Mayúsculas/minúsculas y espacios deben coincidir tal
cual. Si no existe un archivo con ese nombre exacto, el sistema simplemente
deja la línea de firma en blanco (no truena la generación del documento).

### `firmas/abogados/`

El nombre del archivo es el nombre del abogado **tal como aparece en el
menú "Abogado" ANTES de la primera coma** — sin el ", Esq." ni el "(SBN
...)".

| Abogado en el sistema | Nombre del archivo |
|---|---|
| `Carlos Caraballo, Esq. (SBN 21605)` | `firmas/abogados/Carlos Caraballo.png` |
| `John Negron, Esq. (SBN 21806)` | `firmas/abogados/John Negron.png` |
| `Raul Mejia Santos, Esq. (SBN 22998)` | `firmas/abogados/Raul Mejia Santos.png` |
| `Zahira Rodriguez Feliciano, Esq., LL.M. (SBN 20327)` | `firmas/abogados/Zahira Rodriguez Feliciano.png` |
| `Michael Quiroga, Esq. (SBN 333058)` | `firmas/abogados/Michael Quiroga.png` |

### `firmas/preparadores/`

El nombre del archivo es el nombre del preparador/paralegal **exactamente
como aparece en el campo "Preparador" del caso** (no lleva coma ni título).

| Preparador en el sistema | Nombre del archivo |
|---|---|
| `Lorenzo Bracamontes` | `firmas/preparadores/Lorenzo Bracamontes.png` |
| `Kevin Calvillo` | `firmas/preparadores/Kevin Calvillo.png` |
| `Bruno Briz` | `firmas/preparadores/Bruno Briz.png` |

Esta misma carpeta es la que usa el EOIR-33 para la firma del "SIGN HERE"
del Proof of Service — no hay que subir la firma del paralegal en dos
lugares distintos, con que esté aquí ya la toman todos los documentos.

## Si agregas un abogado o preparador nuevo

Al agregar un nombre nuevo a las listas de `catalogos.json`, guarda su
firma aquí con el mismo criterio de nombre de esta guía. No hace falta
tocar ningún código — el sistema busca el archivo por nombre cada vez que
genera un documento.
