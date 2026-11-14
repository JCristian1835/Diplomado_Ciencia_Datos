// Capturas de las evidencias del ETL (playwright-core + Chromium de Playwright).
//   node capturar.mjs html <carpeta_html> <carpeta_png> [prefijo]   -> .panel de cada HTML a PNG
//   node capturar.mjs app  <carpeta_png> <datos.json> <png_antes> <png_despues> <png_swagger>
// `app` necesita backend (8010) y frontend (5180) levantados; credenciales en RR_USER / RR_PASS.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const PROYECTO = path.resolve(AQUI, '..', '..');
const FRONT = process.env.URL_FRONT || 'http://localhost:5180';
const API = process.env.URL_API || 'http://localhost:8010';

async function cargarPlaywright() {
  const candidatos = [process.env.PLAYWRIGHT_CORE, path.join(PROYECTO, 'frontend', 'node_modules', 'playwright-core')]
    .filter(Boolean);
  for (const dir of candidatos) {
    const entrada = path.join(dir, 'index.mjs');
    if (fs.existsSync(entrada)) return import(pathToFileURL(entrada).href);
  }
  throw new Error('No se encontró playwright-core; defina PLAYWRIGHT_CORE con su carpeta');
}

const { chromium } = await cargarPlaywright();
const [modo, ...args] = process.argv.slice(2);
const navegador = await chromium.launch();

async function capturarHtml([dirHtml, dirPng, prefijo = '']) {
  fs.mkdirSync(dirPng, { recursive: true });
  const contexto = await navegador.newContext({ viewport: { width: 1900, height: 1300 }, deviceScaleFactor: 2 });
  const pagina = await contexto.newPage();
  const archivos = fs.readdirSync(dirHtml).filter((f) => f.endsWith('.html') && f.startsWith(prefijo)).sort();
  for (const archivo of archivos) {
    await pagina.goto(pathToFileURL(path.join(dirHtml, archivo)).href);
    await pagina.evaluate(() => document.fonts.ready);
    const salida = path.join(dirPng, archivo.replace(/\.html$/, '.png'));
    await pagina.locator('.panel').screenshot({ path: salida });
    console.log('png', path.basename(salida));
  }
  await contexto.close();
}

async function capturarApp([dirPng, datosJson, pngAntes, pngDespues, pngSwagger]) {
  const usuario = process.env.RR_USER, clave = process.env.RR_PASS;
  const contexto = await navegador.newContext({
    viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, colorScheme: 'light', locale: 'es-CO',
  });
  const datos = {};
  const pagina = await contexto.newPage();

  // ---- Paso 9: tarjeta «Datos reales · Red Rooster» antes y después de sincronizar
  await pagina.goto(`${FRONT}/login`);
  await pagina.locator('input').first().fill(usuario);
  await pagina.locator('input[type=password]').fill(clave);
  await pagina.keyboard.press('Enter');
  await pagina.waitForURL((u) => !u.pathname.startsWith('/login'));
  await pagina.goto(`${FRONT}/datos`);
  const tarjeta = pagina.locator('section.card', { has: pagina.getByRole('heading', { name: 'Datos reales · Red Rooster' }) });
  await tarjeta.locator('.run-metrics').first().waitFor({ timeout: 30000 });
  await pagina.waitForTimeout(1500);
  datos.antes = (await tarjeta.locator('.run-metrics').first().innerText()).split('\n').filter(Boolean);
  datos.ruta_configurada = (await tarjeta.locator('code').first().innerText()).trim();
  await tarjeta.screenshot({ path: path.join(dirPng, pngAntes) });

  await tarjeta.getByRole('button', { name: /Sincronizar pedidos/ }).click();
  await tarjeta.locator('[role=status]').first().waitFor({ timeout: 120000 });
  await tarjeta.locator('.run-metrics').nth(1).waitFor({ timeout: 30000 });
  // Esperar a que desaparezca el aviso flotante (toast) para que no tape la tarjeta.
  await pagina.getByText('Importación completada').nth(1).waitFor({ state: 'detached', timeout: 20000 });
  await pagina.waitForTimeout(800);
  datos.mensaje = (await tarjeta.locator('[role=status]').first().innerText()).split('\n').filter(Boolean);
  datos.despues = (await tarjeta.locator('.run-metrics').first().innerText()).split('\n').filter(Boolean);
  datos.resultado = (await tarjeta.locator('.run-metrics').nth(1).innerText()).split('\n').filter(Boolean);
  datos.alertas = await tarjeta.locator('[role=alert], .alert').allInnerTexts();
  await tarjeta.screenshot({ path: path.join(dirPng, pngDespues) });

  // ---- Paso 11: Swagger (/docs), POST /etl/import con Authorize
  const login = await contexto.request.post(`${API}/api/v1/auth/login`, { data: { username: usuario, password: clave } });
  const token = (await login.json()).access_token;
  const docs = await contexto.newPage();
  await docs.goto(`${API}/docs`);
  await docs.locator('.swagger-ui .opblock').first().waitFor({ timeout: 30000 });
  await docs.locator('button.authorize').first().click();
  await docs.locator('.auth-container input').first().fill(token);
  await docs.locator('.auth-btn-wrapper button.authorize').click();
  await docs.locator('.modal-btn.btn-done, .auth-btn-wrapper button.btn-done').first().click();
  const operacion = docs.locator('.opblock-post', { has: docs.locator('[data-path="/api/v1/etl/import"]') });
  await operacion.locator('.opblock-summary').click();
  await operacion.locator('.try-out__btn').click();
  await operacion.locator('button.execute').click();
  await operacion.locator('.live-responses-table .response-col_status').first().waitFor({ timeout: 120000 });
  await docs.waitForTimeout(1000);
  // El bloque curl incluye el JWT completo: se oculta para no publicarlo.
  // También se oculta la tabla de ejemplos del esquema (documentación), que no es parte de la ejecución.
  await docs.evaluate(() => document.querySelectorAll(
    '.curl-command, .curl-container, .responses-inner table.responses-table:not(.live-responses-table)')
    .forEach((e) => { e.style.display = 'none'; }));
  await docs.evaluate(() => document.querySelectorAll('.responses-inner h4').forEach((e) => {
    if (e.textContent.trim() === 'Responses') e.style.display = 'none';
  }));
  datos.swagger = {
    codigo: (await operacion.locator('.live-responses-table tr.response .response-col_status').first().innerText()).trim().split('\n')[0],
    cuerpo: (await operacion.locator('.live-responses-table .response-col_description pre').first().innerText()).trim(),
  };
  await operacion.screenshot({ path: path.join(dirPng, pngSwagger) });
  await contexto.close();
  fs.writeFileSync(datosJson, JSON.stringify(datos, null, 2), 'utf-8');
  console.log('app', JSON.stringify(datos.swagger));
}

try {
  if (modo === 'html') await capturarHtml(args);
  else if (modo === 'app') await capturarApp(args);
  else throw new Error('Modo desconocido: ' + modo);
} finally {
  await navegador.close();
}
