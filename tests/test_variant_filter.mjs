#!/usr/bin/env node
/**
 * Prueba del filtro de la tabla de exploración (webapp/js/variant-filter.js).
 *
 * No necesita navegador ni jsdom: el módulo no toca el DOM. Reproduce el caso
 * que rompía la vista —filas con `protein_change: null`, 11 166 de las 11 233
 * del contrato actual— y comprueba el filtro por defecto.
 *
 * Uso: node tests/test_variant_filter.mjs
 */
import { filterVariants, countCoding, isCoding } from '../webapp/js/variant-filter.js';

let ok = 0;

function check(condition, message) {
  if (!condition) throw new Error(message);
  ok++;
  console.log(`  OK  ${message}`);
}

const rows = [
  { key: 'PIK3CA_H1047R', hugo_symbol: 'PIK3CA', protein_change: 'H1047R', classification: 'Patogénica' },
  { key: 'TP53_R175H',    hugo_symbol: 'TP53',   protein_change: 'R175H',  classification: 'Patogénica' },
  { key: 'AKT1_E17K',     hugo_symbol: 'AKT1',   protein_change: 'E17K',   classification: 'VUS' },
  { key: 'AMPD2_undefined',   hugo_symbol: 'AMPD2',   protein_change: null,      classification: 'Hotspot' },
  { key: 'ARHGAP6_undefined', hugo_symbol: 'ARHGAP6', protein_change: undefined, classification: 'Hotspot' },
];

console.log('> Filtro por defecto (sólo codificantes)');
check(countCoding(rows) === 3, 'countCoding cuenta sólo las variantes con cambio proteico');
check(isCoding(rows[0]) && !isCoding(rows[3]) && !isCoding(rows[4]),
      'isCoding tolera null y undefined');
const byDefault = filterVariants(rows);
check(byDefault.length === 3, 'se excluyen las filas sin cambio proteico');
check(byDefault.every(r => r.protein_change), 'ninguna fila del resultado tiene protein_change nulo');
check(filterVariants(rows, { onlyCoding: false }).length === 5,
      'con onlyCoding=false entran todas las filas');

console.log('> Búsqueda con filas nulas presentes (el caso que lanzaba TypeError)');
const byVariant = filterVariants(rows, { variantQ: 'h1047' });
check(byVariant.length === 1 && byVariant[0].hugo_symbol === 'PIK3CA',
      'buscar por variante no lanza aunque haya protein_change nulo');
check(filterVariants(rows, { variantQ: 'h1047', onlyCoding: false }).length === 1,
      'la búsqueda por variante funciona también sin el filtro de codificantes');
const byGene = filterVariants(rows, { geneQ: 'tp53' });
check(byGene.length === 1 && byGene[0].protein_change === 'R175H',
      'filtro por gen, sin distinguir mayúsculas');
check(filterVariants(rows, { geneQ: 'ampd2', onlyCoding: false }).length === 1,
      'las filas sin cambio proteico se pueden buscar por gen');
const byClass = filterVariants(rows, { classQ: 'vus' });
check(byClass.length === 1 && byClass[0].hugo_symbol === 'AKT1', 'filtro por clasificación');

console.log('> Casos límite');
check(filterVariants(rows, { geneQ: 'GENQUENOEXISTE' }).length === 0,
      'sin coincidencias devuelve lista vacía');
check(filterVariants(undefined).length === 0, 'tolera una lista indefinida');
check(filterVariants(rows, { variantQ: '  R175H  ' }).length === 1,
      'recorta espacios en el término de búsqueda');

console.log(`OK filtro de variantes (${ok} comprobaciones)`);
