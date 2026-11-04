/**
 * variant-filter.js — filtro de la tabla de exploración, sin DOM.
 *
 * Vive aparte de `explore.js` para poder probarlo en Node
 * (`tests/test_variant_filter.mjs`) sin navegador ni jsdom: la lógica de
 * filtrado fue justo el punto donde la vista se rompía con los datos reales.
 *
 * Los registros agregados pueden traer `protein_change: null` (mutaciones
 * intrónicas, intergénicas o de regiones no codificantes: 11 166 de las 11 233
 * filas del contrato actual). Por eso el filtro por defecto sólo deja pasar las
 * variantes con cambio proteico y todas las comparaciones son null-safe.
 */

/** ¿La fila tiene cambio proteico (es codificante)? */
export function isCoding(row) {
  return Boolean(row?.protein_change);
}

/**
 * Filtra las filas agregadas.
 *
 * @param {Array<object>} rows filas de `buildVariantTable`
 * @param {{geneQ?: string, variantQ?: string, classQ?: string, onlyCoding?: boolean}} opts
 * @returns {Array<object>} subconjunto en el mismo orden
 */
export function filterVariants(rows, opts = {}) {
  const {
    geneQ = '',
    variantQ = '',
    classQ = '',
    onlyCoding = true,
  } = opts;

  const gene = geneQ.toLowerCase().trim();
  const change = variantQ.toLowerCase().trim();
  const cls = classQ.toLowerCase().trim();

  return (rows ?? []).filter(row => {
    if (onlyCoding && !isCoding(row)) return false;

    if (gene && !String(row.hugo_symbol ?? '').toLowerCase().includes(gene)) {
      return false;
    }
    if (change && !String(row.protein_change ?? '').toLowerCase().includes(change)) {
      return false;
    }
    if (cls) {
      const value = String(row.classification ?? '').toLowerCase();
      if (cls === 'patog'   && !value.includes('patog'))   return false;
      if (cls === 'hotspot' && !value.includes('hotspot')) return false;
      if (cls === 'vus'     && !value.includes('vus'))     return false;
      if (cls === 'baja'    && !value.includes('baja'))    return false;
    }
    return true;
  });
}

/** Cuántas filas tienen cambio proteico (denominador del contador). */
export function countCoding(rows) {
  return (rows ?? []).filter(isCoding).length;
}
