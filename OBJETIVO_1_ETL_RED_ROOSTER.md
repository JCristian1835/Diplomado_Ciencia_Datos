# Objetivo 1 ETL y migración de datos reales

## Fuente y destino

La fuente real es `BD/pedidos.json` (3.042 pedidos, del 23-mar al 13-nov-2026), acompañada por `BD/productos.json` (44 productos); la ruta se define en `config.py:30`. `BD/pedidos_24meses.json` ya no se usa. El backend carga ambos archivos en `backend/data/red_rooster.db`, una base SQLite separada de la base sintética. `BD/` no se versiona.

## Transformaciones

- Las fechas con zona horaria se convierten a hora local de Bogotá; las fechas sin zona se interpretan como hora local.
- Los estados `pagado` y `entregado` se cuentan como ventas completadas. Los demás no alimentan los KPIs como ventas completadas.
- Los métodos de pago se normalizan al vocabulario del sistema.
- Los pedidos y sus líneas se insertan o actualizan por ID de origen; repetir la carga no duplica registros. El importador no borra pedidos que desaparecen del origen: para reconstruir la base desde cero se borra `red_rooster.db`.
- El catálogo se actualiza sin reiniciar el stock que gestiona el POS.
- No se guardan nombres, teléfonos, notas ni direcciones. Cada cliente recibe una huella HMAC-SHA256 del teléfono normalizado (sin el prefijo 57) o, si es domicilio, de la dirección, y un código anónimo estable `C###` asignado por primera compra (`CustomerModel.codigo_anonimo`). Cada venta guarda su `canal` (mesa, llevar, domicilio, sin_dato). La clave privada (`data/.privacy_key`) se conserva localmente, fuera del control de versiones, y no se cambia: hacerlo rompe los códigos de cliente.

## Capa analítica

`app/etl/red_rooster_analitica.py` construye tres tablas sobre DataFrames:

- `dim_fecha`: festivos de `holidays.Colombia`, quincena (días 15 y último del mes) y descanso (martes).
- `ventas_diarias`: ventas por día con `lag_1`, `lag_7` y `media_movil_7` calculada con `shift(1).rolling(7)`, sin fuga de información.
- `calidad_datos`: 9 reglas de calidad, expuestas en `GET /api/v1/etl/quality`.

Resultado de la carga real: 3.042 pedidos, 5.022 líneas, 44 productos, 126 clientes (C001–C126), 236 filas en `dim_fecha` y en `ventas_diarias`, 3.017 pedidos pagados e ingresos de 138.605.100. Hallazgos de calidad: 91 fechas en UTC y 2.951 en Bogotá, 5 pedidos sin canal, 77 valores distintos de mesero (texto libre), 8 líneas con costo cero, 1 total que no cuadra, 25 cancelados, 25 sin método de pago y 0 líneas omitidas.

## Carga inicial y continua

FastAPI intenta importar la fuente al iniciar; las columnas nuevas se agregan con ALTER aditivos en el lifespan de `main.py`. En la página Datos se puede consultar el estado de los archivos y ejecutar una sincronización manual mediante `GET /api/v1/etl/source-status` y `POST /api/v1/etl/import`. Para vigilar cambios periódicamente, desde `backend/` se ejecuta `venv\Scripts\python -m app.etl.watch_red_rooster`; el intervalo se controla con `RED_ROOSTER_POLL_SECONDS`.

Cada importación registra estado, conteos, errores y huella de los archivos. Si éstos no cambian, se devuelve `SIN_CAMBIOS`; `force=true` fuerza una reconciliación. La carga y el entrenamiento de modelos son pasos separados: después de importar, se ejecuta el pipeline analítico para actualizar pronósticos, reglas y segmentos.

## Verificación y estado

Verificado el 2026-11-14: `pytest` con 224 pruebas pasadas y 0 fallidas (las 9 nuevas cubren `codigo_anonimo` en la API de clientes), `npm run build`, `npm run lint` y comprobaciones estáticas `92/92` sin errores. Sobre la base ya cargada se agregó un stock inicial de 100 unidades por producto (44 entradas IN en el kardex, por la API; respaldo previo `red_rooster_respaldo_20261114_antes_stock.db`), que una reimportación forzada no borra, pero que hay que volver a cargar si la BD se recrea desde cero. La fuente 3.042 coincide con los 3.042 pedidos cargados.

Verificado el 2026-11-13: `pytest` con 215 pruebas pasadas y 0 fallidas (43 del ETL), `npm run build`, `npm run lint` y comprobaciones estáticas `92/92` sin errores. La base `backend/data/red_rooster.db` se respaldó en `red_rooster_respaldo_20261113.db` y se recargó desde cero solo con `BD/pedidos.json`. Las evidencias (32 capturas y su manifiesto) están en `documentos/evidencias_objetivo_1/`.

Limitaciones conocidas: el margen en `repositories.py:189` trata el costo 0 como real; un `null` dentro de `productos` descarta el pedido completo en `red_rooster.py` en lugar de solo la línea; `api.ts:101` tipa `errors` como `string[]` aunque el backend devuelve un entero.
