'use strict';

/**
 * Test de la lógica pura de CUPS de apps_script/Code.gs (docs/spec.md, sección 11).
 *
 * Ejecutar con: node apps_script/test_cups.js
 * Sin dependencias: carga Code.gs en un contexto `vm` (el archivo solo define
 * funciones y constantes, sin llamadas a APIs de Apps Script en el nivel superior)
 * y comprueba cupsValido_ contra los mismos casos que cups_valido de Python
 * (app/domain/cups.py). Sale con código 1 si algo falla.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ruta = path.join(__dirname, 'Code.gs');
const codigo = fs.readFileSync(ruta, 'utf8');

// Apps Script rechaza los literales BigInt (`529n`) con "Unexpected token ILLEGAL"
// aunque el runtime tenga `BigInt()`: el parser del editor no los admite. Este guard
// convierte ese fallo, que sólo aparece al pegar el código en la hoja, en un test.
const LITERAL_BIGINT = /\b\d+n\b/;
const esComentario = (linea) => /^\s*(\/\/|\*|\/\*)/.test(linea);
const culpable = codigo
  .split('\n')
  .findIndex((linea) => LITERAL_BIGINT.test(linea) && !esComentario(linea));
if (culpable >= 0) {
  console.error(
    `FALLO: apps_script/Code.gs usa un literal BigInt en la línea ${culpable + 1}. ` +
      'Apps Script lo rechaza con "Unexpected token ILLEGAL".'
  );
  process.exit(1);
}

const contexto = vm.createContext({ console });
vm.runInContext(codigo + '\nthis.__cupsValido = cupsValido_;', contexto);
const cupsValido = contexto.__cupsValido;

if (typeof cupsValido !== 'function') {
  console.error('FALLO: no se ha encontrado cupsValido_ en apps_script/Code.gs');
  process.exit(1);
}

// [cups, esperado, descripción]
const CASOS = [
  ['ES0031102846140001AK0F', true, 'CUPS real de luz, con sufijo (letras de control AK)'],
  ['ES0021000000000001RK', true, 'CUPS real corto, sin sufijo (letras de control RK)'],
  ['es0031102846140001ak0f', true, 'minúsculas se normalizan a mayúsculas'],
  [' ES 0031 1028 4614 0001 AK0F ', true, 'espacios intercalados se eliminan'],
  ['ES0031102846140001XX0F', false, 'letras de control incorrectas (con sufijo)'],
  ['ES0021000000000001XK', false, 'letras de control incorrectas (sin sufijo)'],
  ['ES0021000000000001AK', false, 'letras de control de otro CUPS'],
  ['ES0031102846140001AK0', false, 'sufijo incompleto (falta la letra)'],
  ['ES0031102846140001AKF0', false, 'sufijo malformado (letra antes del dígito)'],
  ['ES0031102846140001AK0F1', false, 'caracteres de más tras el sufijo'],
  ['PT0031102846140001AK0F', false, 'país distinto de ES'],
  ['FR0021000000000001RK', false, 'país distinto de ES, sin sufijo'],
  ['', false, 'cadena vacía'],
  ['   ', false, 'solo espacios'],
  ['ES003110284614000', false, 'menos de 16 dígitos'],
  ['ES00311028461400011', false, '17 dígitos, sin letras de control'],
  ['ES0031102846140001AK0F', true, 'formato exacto tras normalizar'],
  ['ES9999999999999999SA', true, '16 dígitos por encima de 2^53: el módulo no pierde precisión'],
  ['ES9999999999999999SG', false, 'la misma cuenta con Number daría otras letras de control'],
  [null, false, 'valor nulo'],
  [undefined, false, 'valor sin definir'],
];

let pasados = 0;
const fallos = [];

for (const [cups, esperado, descripcion] of CASOS) {
  let obtenido;
  try {
    obtenido = cupsValido(cups);
  } catch (error) {
    fallos.push(`- ${descripcion}: lanzó una excepción: ${error.message}`);
    continue;
  }
  if (obtenido === esperado) {
    pasados += 1;
  } else {
    fallos.push(`- ${descripcion}: esperado ${esperado}, obtenido ${obtenido} (cups: ${JSON.stringify(cups)})`);
  }
}

if (fallos.length > 0) {
  console.error(`FALLOS (${fallos.length} de ${CASOS.length} casos):`);
  for (const fallo of fallos) console.error(fallo);
  process.exit(1);
}

console.log(`${pasados}/${CASOS.length} casos de CUPS correctos`);
