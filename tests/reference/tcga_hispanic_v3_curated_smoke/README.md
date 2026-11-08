# Fixture histórico `tcga_hispanic_v3_curated_smoke`

Este directorio conserva el **fixture antiguo** del Pipeline V3, con
`contract_version = 1.2.0`. **No es un bundle científico válido** y no debe
usarse para análisis.

## Por qué se conserva

Se mantiene como procedencia histórica de la auditoría
`docs/V3_DNA_AUDIT.md`. Permite reproducir los defectos encontrados sin
mezclarlos con el bundle real.

## Defectos conocidos

- Declara `Data Release 41.0` hardcodeado; el release real del GDC es
  `Data Release 46.0 - August 10, 2026`.
- Contiene 21 registros de mutación, pero 7 apuntaban a muestras normales
  (`-10A`, `-11A`) porque el exportador tomaba `samples[0]`.
- Contiene la variante inexistente `GATA3 M294K` (la real es `M293K`).
- Omite variantes reales como `GATA3 M293K`, `BRCA2 E1158Q` y `BRCA2 K1191N`.
- No declara `mutation_scope`, `data_origin` ni `curated`.

## Uso permitido

Solo pruebas de humo de compatibilidad hacia atrás o reproducción de la
auditoría. Para V3, usar `../tcga_hispanic_v3/`.

```bash
# Debe fallar: el fixture no cumple el contrato 2.0.0.
python bin/validate_contract.py --contract-dir tests/reference/tcga_hispanic_v3_curated_smoke
```
