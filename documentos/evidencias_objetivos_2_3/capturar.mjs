// Capturas de la aplicación para las evidencias de los Objetivos 2 y 3 (playwright-core + Chromium de Playwright).
//   node capturar.mjs app    <carpeta_png> <datos.json>   -> páginas Datos, Inicio, Analítica, Clientes y Swagger
//   node capturar.mjs asesor <carpeta_png> <datos.json>   -> página Asesor con una pregunta real (requiere GEMINI_API_KEY)
// Necesita backend (8010) y frontend (5180) levantados; credenciales en RR_USER / RR_PASS. Viewport 1440 x 900, factor 2.
// Los paneles de código y terminal los fotografía ../evidencias_objetivo_1/capturar.mjs (modo html).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const PROYECTO = path.resolve(AQUI, '..', '..');
const FRONT = process.env.URL_FRONT || 'http://localhost:5180';
const API = process.env.URL_API || 'http://localhost:8010';
const PREGUNTA = '¿Qué combos me recomiendas para aumentar el ticket y qué clientes debo reactivar?';

async function cargarPlaywright() {
  const candidatos = [process.env.PLAYWRIGHT_CORE, path.join(PROYECTO, 'frontend', 'node_modules', 'playwright-core')].filter(Boolean);
  for (const dir of candidatos) {
    const entrada = path.join(dir, 'index.mjs');
    if (fs.existsSync(entrada)) return import(pathToFileURL(entrada).href);
  }
  throw new Error('No se encontró playwright-core; defina PLAYWRIGHT_CORE con su carpeta');
}

const { chromium } = await cargarPlaywright();
const [modo, dirPng, datosJson] = process.argv.slice(2);
const navegador = await chromium.launch();
const lineas = (texto) => texto.split('\n').map((l) => l.trim()).filter(Boolean);

async function sesion() {
  const contexto = await navegador.newContext({
    viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'light', locale: 'es-CO',
  });
  // El botón flotante del asesor se mueve por la pantalla y tapa el texto: se oculta en las capturas.
  await contexto.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const e = document.createElement('style');
      e.textContent = '.agente{display:none !important}';
      document.head.appendChild(e);
    });
  });
  const pagina = await contexto.newPage();
  await pagina.goto(`${FRONT}/login`);
  await pagina.locator('input').first().fill(process.env.RR_USER);
  await pagina.locator('input[type=password]').fill(process.env.RR_PASS);
  await pagina.keyboard.press('Enter');
  await pagina.waitForURL((u) => !u.pathname.startsWith('/login'));
  return { contexto, pagina };
}

// Espera a que terminen las animaciones de entrada (.rise) y a que no haya esqueletos de carga.
async function asentar(pagina, ms = 1800) {
  await pagina.locator('.skeleton, [aria-busy=true] .skeleton').first().waitFor({ state: 'detached', timeout: 30000 }).catch(() => {});
  await pagina.waitForTimeout(ms);
}

async function foto(pagina, nombre, completa = true) {
  await pagina.mouse.move(2, 2);
  await pagina.screenshot({ path: path.join(dirPng, nombre), fullPage: completa });
}

async function leerDatos(pagina) {
  await pagina.getByText('MAE (unidades)').waitFor({ timeout: 30000 });
  await asentar(pagina);
  return {
    metricas: lineas(await pagina.locator('.grid-3').first().innerText()),
    corridas: await pagina.locator('table.tbl tbody tr').count(),
  };
}

async function capturarApp() {
  const { contexto, pagina } = await sesion();
  const datos = {};

  // ---- Objetivo 3, paso 4: página Datos antes y después de ejecutar el pipeline con reentrenamiento forzado
  await pagina.goto(`${FRONT}/datos`);
  datos.datos_antes = await leerDatos(pagina);
  await foto(pagina, 'o3_04a_app_datos_antes.png');

  await pagina.getByRole('switch', { name: 'Forzar reentrenamiento' }).click();
  await pagina.getByRole('button', { name: 'Ejecutar pipeline' }).click();
  const aviso = pagina.getByText(/Pipeline completado en/).first();
  await aviso.waitFor({ timeout: 180000 });
  datos.aviso_pipeline = (await aviso.innerText()).trim();
  await pagina.getByText(/Pipeline completado en/).first().waitFor({ state: 'detached', timeout: 30000 });
  await pagina.waitForFunction((antes) => document.querySelectorAll('table.tbl tbody tr').length > antes, datos.datos_antes.corridas,
    { timeout: 30000 });
  datos.datos_despues = await leerDatos(pagina);
  await foto(pagina, 'o3_04b_app_datos_despues.png');

  // ---- Paso 5: Inicio, indicadores de 30 días (periodo por defecto)
  await pagina.goto(`${FRONT}/`);
  await pagina.locator('.kpi-row .card').first().waitFor({ timeout: 30000 });
  await asentar(pagina, 2500);
  datos.inicio = { periodo: lineas(await pagina.getByRole('radiogroup', { name: 'Periodo' }).innerText().catch(() => '')),
                   tarjetas: (await pagina.locator('.kpi-row .card').allInnerTexts()).map((t) => lineas(t)) };
  await foto(pagina, 'o3_05a_app_inicio_kpis.png');

  // ---- Paso 6: Analítica, tres pestañas
  await pagina.goto(`${FRONT}/analitica`);
  await pagina.locator('.metrics .pill').first().waitFor({ timeout: 30000 });
  await asentar(pagina, 2500);
  datos.demanda = { pastillas: lineas(await pagina.locator('.metrics').first().innerText()) };
  await foto(pagina, 'o3_06a_app_analitica_demanda.png');

  await pagina.getByRole('tab', { name: 'Venta cruzada' }).click();
  await pagina.locator('table.tbl tbody tr').first().waitFor({ timeout: 30000 });
  await asentar(pagina, 1500);
  const filas = await pagina.locator('table.tbl tbody tr').allInnerTexts();
  datos.cruzada = { filas: filas.length, primeras: filas.slice(0, 5).map((f) => f.replace(/\s+/g, ' ').trim()) };
  await foto(pagina, 'o3_06b_app_analitica_venta_cruzada.png');

  await pagina.getByRole('tab', { name: 'Segmentos' }).click();
  await pagina.locator('.recharts-scatter-symbol, .recharts-symbols').first().waitFor({ timeout: 30000 });
  await asentar(pagina, 2500);
  datos.segmentos = { pastillas: lineas(await pagina.locator('.metrics').first().innerText()) };
  // Hover real sobre el punto más alto del gráfico de dispersión (mayor valor monetario).
  const puntos = pagina.locator('.recharts-scatter .recharts-symbols');
  const total = await puntos.count();
  let mejor = null;
  for (let i = 0; i < total; i++) {
    const caja = await puntos.nth(i).boundingBox();
    if (caja && (!mejor || caja.y < mejor.caja.y)) mejor = { i, caja };
  }
  const grafico = pagina.locator('.chart-box.tall').first();
  await grafico.scrollIntoViewIfNeeded();
  await pagina.waitForTimeout(600);
  const caja = await puntos.nth(mejor.i).boundingBox();
  await pagina.mouse.move(caja.x + caja.width / 2 - 6, caja.y + caja.height / 2 - 6);
  await pagina.mouse.move(caja.x + caja.width / 2, caja.y + caja.height / 2, { steps: 6 });
  await pagina.locator('.chart-tip').waitFor({ timeout: 10000 });
  datos.segmentos.tooltip = lineas(await pagina.locator('.chart-tip').innerText());
  await pagina.waitForTimeout(500);
  await pagina.screenshot({ path: path.join(dirPng, 'o3_06c_app_analitica_segmentos.png') });

  // ---- Paso 7: Clientes con la búsqueda C001
  await pagina.goto(`${FRONT}/clientes`);
  await pagina.locator('table.tbl tbody tr').first().waitFor({ timeout: 30000 });
  await pagina.getByPlaceholder(/C001/).fill('C001');
  await pagina.waitForFunction(() => document.querySelectorAll('table.tbl tbody tr').length <= 3, null, { timeout: 15000 });
  await asentar(pagina, 1500);
  const clientes = await pagina.locator('table.tbl tbody tr').allInnerTexts();
  datos.clientes = { filas: clientes.length, codigos: clientes.map((f) => f.split('\t')[0].trim()) };
  await pagina.mouse.move(2, 2);
  await pagina.screenshot({ path: path.join(dirPng, 'o3_07a_app_clientes_busqueda.png'), clip: { x: 0, y: 0, width: 1440, height: 580 } });

  // ---- Paso 9: Swagger, sección analytics con GET /analytics/segments ejecutado
  const login = await contexto.request.post(`${API}/api/v1/auth/login`, { data: { username: process.env.RR_USER, password: process.env.RR_PASS } });
  const token = (await login.json()).access_token;
  const docs = await contexto.newPage();
  await docs.setViewportSize({ width: 1440, height: 900 });
  await docs.goto(`${API}/docs`);
  await docs.locator('.swagger-ui .opblock').first().waitFor({ timeout: 30000 });
  await docs.locator('button.authorize').first().click();
  await docs.locator('.auth-container input').first().fill(token);
  await docs.locator('.auth-btn-wrapper button.authorize').click();
  await docs.locator('.modal-btn.btn-done, .auth-btn-wrapper button.btn-done').first().click();
  const seccion = docs.locator('.opblock-tag-section', { has: docs.locator('h3.opblock-tag[data-tag="analytics"]') });
  const operacion = seccion.locator('.opblock-get', { has: docs.locator('[data-path="/api/v1/analytics/segments"]') });
  await operacion.locator('.opblock-summary').click();
  await operacion.locator('.try-out__btn').click();
  await operacion.locator('button.execute').click();
  await operacion.locator('.live-responses-table .response-col_status').first().waitFor({ timeout: 60000 });
  await docs.waitForTimeout(1000);
  // El bloque curl incluye el JWT completo: se oculta. También la tabla de ejemplos del esquema (documentación).
  await docs.evaluate(() => document.querySelectorAll(
    '.curl-command, .curl-container, .responses-inner table.responses-table:not(.live-responses-table)')
    .forEach((e) => { e.style.display = 'none'; }));
  await docs.evaluate(() => document.querySelectorAll('.responses-inner h4').forEach((e) => {
    if (e.textContent.trim() === 'Responses') e.style.display = 'none';
  }));
  // El cuerpo de la respuesta es largo: se desplaza hasta la lista de clientes para que se vea codigo_anonimo.
  const cuerpo = await operacion.locator('.live-responses-table .response-col_description pre').first().innerText();
  await operacion.locator('.live-responses-table .response-col_description pre').first().evaluate((pre) => {
    const texto = pre.innerText;
    pre.scrollTop = pre.scrollHeight * (texto.indexOf('"clientes"') / texto.length);
  });
  datos.swagger = {
    codigo: (await operacion.locator('.live-responses-table tr.response .response-col_status').first().innerText()).trim().split('\n')[0],
    tiene_codigo_anonimo: cuerpo.includes('"codigo_anonimo"'),
  };
  await docs.waitForTimeout(500);
  await seccion.screenshot({ path: path.join(dirPng, 'o3_09a_swagger_analytics.png') });
  await contexto.close();
  fs.writeFileSync(datosJson, JSON.stringify(datos, null, 2), 'utf-8');
  console.log('app', JSON.stringify({ aviso: datos.aviso_pipeline, tooltip: datos.segmentos.tooltip, swagger: datos.swagger }));
}

async function capturarAsesor() {
  const { contexto, pagina } = await sesion();
  await pagina.goto(`${FRONT}/asesor`);
  await pagina.getByPlaceholder('Escribe tu pregunta…').fill(PREGUNTA);
  await pagina.getByRole('button', { name: 'Preguntar' }).click();
  const plan = pagina.locator('.plan');
  await plan.first().waitFor({ timeout: 180000 });
  await asentar(pagina, 2500);
  const modo = (await plan.first().locator('.plan-head .pill, .plan-head [class*=pill]').first().innerText()).trim();
  const datos = {
    pregunta: PREGUNTA, modo: modo === 'Gemini' ? 'gemini' : modo.toLowerCase(),
    acciones: await plan.first().locator('.plan-card').count(),
    resumen: (await plan.first().locator('.plan-summary').innerText()).trim(),
    datos_citados: await plan.first().locator('.plan-card ul li').allInnerTexts(),
    advertencias: await plan.first().locator('.alert li, [role=alert] li').allInnerTexts().catch(() => []),
  };
  await foto(pagina, 'o3_08b_app_asesor.png');
  await contexto.close();
  fs.writeFileSync(datosJson, JSON.stringify(datos, null, 2), 'utf-8');
  console.log('asesor', datos.modo, datos.acciones);
}

try {
  if (modo === 'app') await capturarApp();
  else if (modo === 'asesor') await capturarAsesor();
  else throw new Error('Modo desconocido: ' + modo);
} finally {
  await navegador.close();
}
