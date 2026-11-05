/**
 * Energy Ops Hub · Altas masivas desde Google Sheets (docs/spec.md, sección 11).
 *
 * Hoja "Altas" con columnas fijas:
 *   cliente_nif | cups | tipo | direccion | tarifa_acceso | potencia_kw | estado | mensaje
 *
 * Menú Energy Ops:
 *   1. Validar filas        -> validarFilas()
 *   2. Enviar altas válidas -> enviarAltas()
 *   3. Actualizar estados   -> actualizarEstados()
 *
 * informeDiario() se asigna a un activador de tiempo diario: genera la pestaña
 * "Resumen" con las altas paradas y envía un email.
 *
 * Criterio: lectura y escritura en bloque (getValues/setValues/setBackgrounds),
 * nunca celda a celda; secretos (API_URL, API_KEY) en Script Properties, nunca
 * en el código; la API vuelve a validar todo porque nunca se confía en un cliente
 * y POST /altas/lote es idempotente por CUPS.
 */

const HOJA_ALTAS = 'Altas';
const HOJA_RESUMEN = 'Resumen';
const COLS = { nif: 0, cups: 1, tipo: 2, direccion: 3, tarifa: 4, potencia: 5, estado: 6, mensaje: 7 };
const LETRAS = 'TRWAGMYFPDXBNJZSQVHLCKE';
const TIPOS_VALIDOS = ['luz', 'gas', 'agua'];
const COLOR_ERROR = '#FDE2E1';
const DIAS_PARADA_RESUMEN = 7;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Energy Ops')
    .addItem('Validar filas', 'validarFilas')
    .addItem('Enviar altas válidas', 'enviarAltas')
    .addItem('Actualizar estados', 'actualizarEstados')
    .addToUi();
}

/** Secretos fuera del código: se leen de las propiedades del script. */
function cfg_() {
  const propiedades = PropertiesService.getScriptProperties();
  const url = propiedades.getProperty('API_URL');
  const key = propiedades.getProperty('API_KEY');
  if (!url || !key) {
    throw new Error(
      'Faltan API_URL o API_KEY: configúralas en Configuración del proyecto > ' +
        'Propiedades del script. Nunca van en el código.'
    );
  }
  return { url: url.replace(/\/+$/, ''), key: key };
}

function hojaAltas_() {
  const hoja = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HOJA_ALTAS);
  if (!hoja) throw new Error('No se encuentra la hoja "' + HOJA_ALTAS + '"');
  return hoja;
}

function aviso_(mensaje) {
  try {
    SpreadsheetApp.getUi().alert(mensaje);
  } catch (e) {
    // Desde un activador no hay interfaz: queda en el registro de ejecuciones.
    Logger.log(mensaje);
  }
}

function normalizarCups_(cups) {
  return String(cups === null || cups === undefined ? '' : cups).replace(/\s+/g, '').toUpperCase();
}

/** Módulo de una cadena de dígitos, calculado dígito a dígito.
 *
 * 16 dígitos superan la precisión de Number y Apps Script no admite literales BigInt
 * (`529n` da "Unexpected token ILLEGAL" al pegar el código en la hoja), así que el resto
 * se acumula de izquierda a derecha sin salir nunca del rango seguro.
 */
function restoModulo_(digitos, modulo) {
  let resto = 0;
  for (let i = 0; i < digitos.length; i += 1) {
    resto = (resto * 10 + (digitos.charCodeAt(i) - 48)) % modulo;
  }
  return resto;
}

function cupsValido_(cups) {
  const m = /^ES(\d{16})([A-Z]{2})(\d[A-Z])?$/.exec(normalizarCups_(cups));
  if (!m) return false;
  const resto = restoModulo_(m[1], 529);
  return LETRAS[Math.floor(resto / 23)] + LETRAS[resto % 23] === m[2];
}

/**
 * Opción 1 del menú: valida en la propia hoja CUPS, duplicados, campos
 * obligatorios y tipo, escribe estado y motivo, y colorea en rojo las filas
 * con error. Una sola lectura y una sola escritura del rango (en bloque).
 */
function validarFilas() {
  const hoja = hojaAltas_();
  const rango = hoja.getDataRange();
  const datos = rango.getValues(); // una sola lectura
  const vistos = {};
  const fondos = [];
  let errores = 0;

  for (let i = 1; i < datos.length; i++) {
    const f = datos[i];
    const problemas = [];

    const cups = normalizarCups_(f[COLS.cups]);
    f[COLS.cups] = cups;
    if (!cupsValido_(cups)) problemas.push('CUPS inválido');
    if (vistos[cups]) problemas.push('CUPS duplicado en la hoja');
    vistos[cups] = true;

    if (!String(f[COLS.nif]).trim()) problemas.push('Falta NIF del cliente');
    if (!String(f[COLS.direccion]).trim()) problemas.push('Falta dirección');
    const tipo = String(f[COLS.tipo]).trim().toLowerCase();
    if (TIPOS_VALIDOS.indexOf(tipo) === -1) problemas.push('Tipo no válido');

    // Las filas ya enviadas no se tocan; el resto se recalcula.
    if (!f[COLS.estado] || f[COLS.estado] === 'error' || f[COLS.estado] === 'validada') {
      f[COLS.estado] = problemas.length ? 'error' : 'validada';
      f[COLS.mensaje] = problemas.join('; ');
    }
    if (f[COLS.estado] === 'error') errores += 1;

    fondos.push(f.map(function () { return f[COLS.estado] === 'error' ? COLOR_ERROR : null; }));
  }

  rango.setValues(datos); // una sola escritura
  if (fondos.length > 0) {
    hoja.getRange(2, 1, fondos.length, datos[0].length).setBackgrounds(fondos);
  }

  aviso_(
    'Validación terminada: ' + (datos.length - 1) + ' filas, ' +
      (datos.length - 1 - errores) + ' válidas y ' + errores + ' con error.'
  );
}

/**
 * Opción 2 del menú: envía a POST /altas/lote solo las filas validadas, en una
 * única llamada, con el `fila` de la hoja y `cliente_nif` (docs/spec.md, sección
 * 11), y escribe el resultado fila a fila (el `fila` vuelve tal cual). Si la API
 * devuelve error HTTP, avisa y no marca nada como enviado. El endpoint es
 * idempotente por CUPS: repetir el envío no duplica altas.
 */
function enviarAltas() {
  const cfg = cfg_();
  const hoja = hojaAltas_();
  const datos = hoja.getDataRange().getValues();

  const filas = [];
  for (let i = 1; i < datos.length; i++) {
    if (datos[i][COLS.estado] !== 'validada') continue;
    filas.push({
      fila: i + 1, // el resultado lo devuelve tal cual (eco exacto)
      cliente_nif: String(datos[i][COLS.nif]).trim(),
      cups: datos[i][COLS.cups],
      tipo: String(datos[i][COLS.tipo]).trim().toLowerCase(),
      direccion: String(datos[i][COLS.direccion]).trim(),
      tarifa_acceso: datos[i][COLS.tarifa] === '' ? null : datos[i][COLS.tarifa],
      potencia_kw: datos[i][COLS.potencia] === '' ? null : datos[i][COLS.potencia],
    });
  }
  if (filas.length === 0) {
    aviso_('No hay filas validadas pendientes de enviar.');
    return;
  }

  const res = UrlFetchApp.fetch(cfg.url + '/altas/lote', {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-API-Key': cfg.key },
    payload: JSON.stringify({ filas: filas }),
    muteHttpExceptions: true, // para gestionar nosotros el error
  });
  if (res.getResponseCode() >= 300) {
    aviso_(
      'Error de la API (HTTP ' + res.getResponseCode() + '): ninguna fila se ha ' +
        'marcado como enviada. Respuesta: ' + res.getContentText()
    );
    return;
  }

  const salida = JSON.parse(res.getContentText());
  let enviadas = 0;
  // resultados[].fila es el eco del `fila` que envió cada fila de la hoja.
  salida.resultados.forEach(function (r) {
    if (!r.fila) return;
    const estado = r.ok ? 'enviada' : 'error';
    hoja.getRange(r.fila, COLS.estado + 1, 1, 2).setValues([[estado, r.mensaje || '']]);
    if (!r.ok) {
      hoja.getRange(r.fila, 1, 1, COLS.mensaje + 1).setBackground(COLOR_ERROR);
    } else {
      enviadas += 1;
    }
  });
  aviso_(
    'Lote enviado: ' + enviadas + ' altas correctas y ' + (salida.resultados.length - enviadas) +
      ' con error. Resumen de la API: ' + JSON.stringify(salida.resumen)
  );
}

/**
 * Opción 3 del menú: trae de la API el estado actual de las altas (GET /altas,
 * docs/spec.md, sección 15: {cups, cliente, estado, dias_parada}) y lo escribe
 * en la hoja por CUPS, en bloque.
 */
function actualizarEstados() {
  const cfg = cfg_();
  const res = UrlFetchApp.fetch(cfg.url + '/altas', {
    headers: { 'X-API-Key': cfg.key },
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() >= 300) {
    aviso_('Error de la API al leer las altas (HTTP ' + res.getResponseCode() + '): ' + res.getContentText());
    return;
  }

  const respuesta = JSON.parse(res.getContentText());
  const altas = Array.isArray(respuesta) ? respuesta : respuesta.altas || [];
  const porCups = {};
  altas.forEach(function (a) {
    if (a && a.cups) porCups[normalizarCups_(a.cups)] = a;
  });
  if (Object.keys(porCups).length === 0) {
    aviso_('La API no ha devuelto ninguna alta: no hay estados que actualizar.');
    return;
  }

  const hoja = hojaAltas_();
  const rango = hoja.getDataRange();
  const datos = rango.getValues(); // una sola lectura
  const estados = [];
  for (let i = 0; i < datos.length; i++) {
    if (i === 0) {
      estados.push([datos[0][COLS.estado], datos[0][COLS.mensaje]]); // cabecera intacta
      continue;
    }
    const alta = porCups[normalizarCups_(datos[i][COLS.cups])];
    if (alta && alta.estado) {
      estados.push([
        alta.estado,
        'Actualizado desde la API' + (alta.dias_parada != null ? ': ' + alta.dias_parada + ' días en el mismo estado' : ''),
      ]);
    } else {
      estados.push([datos[i][COLS.estado], datos[i][COLS.mensaje]]);
    }
  }
  hoja.getRange(1, COLS.estado + 1, estados.length, 2).setValues(estados); // una sola escritura
  aviso_('Estados actualizados desde la API para ' + Object.keys(porCups).length + ' altas.');
}

/**
 * Informe diario, para asignar a un activador de tiempo: genera la pestaña
 * "Resumen" con las altas paradas más de DIAS_PARADA_RESUMEN días y envía un
 * email. No usa getUi(): desde un activador no hay interfaz.
 */
function informeDiario() {
  const cfg = cfg_();
  const res = UrlFetchApp.fetch(cfg.url + '/altas?parada_dias=' + DIAS_PARADA_RESUMEN, {
    headers: { 'X-API-Key': cfg.key },
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() >= 300) {
    Logger.log('informeDiario: error de la API al leer las altas (HTTP ' + res.getResponseCode() + '): ' + res.getContentText());
    return;
  }

  const respuesta = JSON.parse(res.getContentText());
  const paradas = Array.isArray(respuesta) ? respuesta : respuesta.altas || [];

  const libro = SpreadsheetApp.getActiveSpreadsheet();
  const hoja = libro.getSheetByName(HOJA_RESUMEN) || libro.insertSheet(HOJA_RESUMEN);
  hoja.clear();
  hoja.getRange(1, 1, 1, 4).setValues([['CUPS', 'Cliente', 'Estado', 'Días parada']]);
  if (paradas.length > 0) {
    hoja.getRange(2, 1, paradas.length, 4).setValues(paradas.map(function (a) {
      return [a.cups, a.cliente, a.estado, a.dias_parada === null || a.dias_parada === undefined ? '' : a.dias_parada];
    }));
  }

  if (paradas.length > 0) {
    MailApp.sendEmail(
      Session.getEffectiveUser().getEmail(),
      'Energy Ops: ' + paradas.length + ' altas paradas más de ' + DIAS_PARADA_RESUMEN + ' días',
      'Revisa la pestaña Resumen: ' + libro.getUrl()
    );
  }
}
