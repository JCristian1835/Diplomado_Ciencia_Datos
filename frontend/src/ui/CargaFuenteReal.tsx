import type { FuenteReal, ResultadoImportacion } from '../services/api';
import { Pill, RunPill } from './Badges';
import { Button } from './Button';
import { Switch } from './Inputs';
import { Alert, Card, CardHeader, Skeleton, Stat } from './Surfaces';

interface Props {
  fuente?: FuenteReal;
  fuenteCargando: boolean;
  importando: boolean;
  forzar: boolean;
  onForzar: (v: boolean) => void;
  onImportar: () => void;
  error?: string;
  resultado?: ResultadoImportacion;
}

const FECHA_CORTA: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false };

/** Carga del histórico Red Rooster; independiente del entrenamiento de modelos analíticos. */
export function CargaFuenteReal({ fuente, fuenteCargando, importando, forzar, onForzar, onImportar, error, resultado }: Props) {
  return (
    <Card feature>
      <CardHeader icon="datos" title="Datos reales · Red Rooster" aside={
        fuente ? <Pill tone={fuente.exists ? 'ok' : 'danger'}>{fuente.exists ? 'Fuente disponible' : 'Fuente no encontrada'}</Pill> : undefined
      } />
      <p className="muted small">Migra y actualiza pedidos desde el JSON hacia SQLite. Esta carga no entrena modelos; el pipeline analítico se ejecuta por separado.</p>
      {fuenteCargando ? <Skeleton ancho="100%" /> : fuente && (
        <div className="stack">
          {!fuente.exists && <Alert tone="danger" title="No se encontró el archivo de datos" role="alert">Revisa la ruta de la fuente en la configuración del backend.</Alert>}
          <div className="stack">
            <small className="muted">Archivo configurado</small>
            <code style={{ overflowWrap: 'anywhere' }}>{fuente.source_path}</code>
          </div>
          <div className="run-metrics">
            <Stat valor={fuente.source_orders.toLocaleString('es-CO')} etiqueta="Pedidos en el JSON" />
            <Stat valor={fuente.loaded_orders.toLocaleString('es-CO')} etiqueta="Pedidos en SQLite" />
            <Stat valor={<span className="num-texto">{fuente.last_import_at ? new Date(fuente.last_import_at).toLocaleString('es-CO', FECHA_CORTA) : '—'}</span>} etiqueta="Última sincronización" />
            <Stat valor={fuente.last_status ? <RunPill estado={fuente.last_status} /> : <Pill>Sin cargas</Pill>} etiqueta="Estado de la última carga" />
          </div>
          <div className="toolbar">
            <Button icon="next" loading={importando} disabled={!fuente.exists} onClick={onImportar}>
              {forzar ? 'Reconciliar todos los pedidos' : 'Sincronizar pedidos'}
            </Button>
            <label className="row-gap small"><Switch checked={forzar} onChange={onForzar} label="Forzar reconciliación completa" /> Reconciliar todos, incluso si no hubo cambios en el archivo</label>
          </div>
          <p className="muted small">Para mantener la carga continua, el backend puede ejecutar el observador JSON cada {fuente.watcher_interval_seconds} segundos.</p>
        </div>
      )}
      {error && <Alert tone="danger" title="La carga no se completó" role="alert">{error}</Alert>}
      {resultado && (
        <div className="stack" aria-live="polite">
          <Alert tone={resultado.status === 'SUCCESS' || resultado.status === 'SIN_CAMBIOS' ? 'ok' : 'warn'} title={resultado.message || `Carga: ${resultado.status}`} role="status">
            <p>Inicio: {new Date(resultado.started_at).toLocaleString('es-CO')} · duración {resultado.finished_at ? `${Math.max(0, (Date.parse(resultado.finished_at) - Date.parse(resultado.started_at)) / 1000).toFixed(1)} s` : '—'}.</p>
          </Alert>
          <div className="run-metrics">
            <Stat valor={resultado.inserted.toLocaleString('es-CO')} etiqueta="Pedidos nuevos" />
            <Stat valor={resultado.updated.toLocaleString('es-CO')} etiqueta="Pedidos actualizados" />
            <Stat valor={resultado.unchanged.toLocaleString('es-CO')} etiqueta="Sin cambios" />
            <Stat valor={resultado.lines.toLocaleString('es-CO')} etiqueta="Líneas procesadas" />
          </div>
          {(resultado.skipped > 0 || resultado.errors.length > 0) && (
            <Alert tone="warn" title={`${resultado.skipped} elementos omitidos · ${resultado.errors.length} errores`}>
              {resultado.errors.length > 0 && <ul>{resultado.errors.slice(0, 5).map((e, i) => <li key={i}>{e}</li>)}</ul>}
            </Alert>
          )}
        </div>
      )}
    </Card>
  );
}
