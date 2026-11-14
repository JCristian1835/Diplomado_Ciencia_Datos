"""Vigilante continuo del JSON (python -m app.etl.watch_red_rooster)."""
import logging
import time

from app.core.config import get_settings, obtener_clave_privacidad
from app.core.db import SessionLocal
from app.etl.red_rooster import importar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("red_rooster_watcher")


def main() -> None:
    cfg = get_settings()
    intervalo = max(5, cfg.red_rooster_poll_seconds)
    log.info("Vigilando %s cada %s segundos. Ctrl+C para detener.", cfg.red_rooster_json, intervalo)
    while True:
        try:
            with SessionLocal() as session:
                log.info("Carga: %s", importar(session, cfg.red_rooster_json, obtener_clave_privacidad()))
        except Exception:
            log.exception("Falló la carga; se reintentará en %s segundos", intervalo)
        time.sleep(intervalo)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Vigilante detenido")
