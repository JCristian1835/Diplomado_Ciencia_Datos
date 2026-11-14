"""Configuración de la aplicación (pydantic-settings, en caché)."""
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    jwt_secret: str = "dev-secret-solo-para-desarrollo-cambiar-en-produccion"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    admin_user: str = "admin"
    admin_password: str = "admin123"
    fernet_key: str = ""
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'red_rooster.db').as_posix()}"
    cors_origins: str = "http://localhost:5180"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    apriori_min_support: float = 0.02
    apriori_min_confidence: float = 0.3
    apriori_min_lift: float = 1.2
    demanda_test_dias: int = 30
    seed_on_empty: bool = True
    data_source_mode: str = "red_rooster"
    red_rooster_json: str = str(BASE_DIR.parent / "BD" / "pedidos.json")
    data_privacy_key: str = ""
    red_rooster_poll_seconds: int = 60

    @property
    def cors_lista(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def obtener_clave_fernet() -> str:
    """Devuelve FERNET_KEY; en modo dev la genera y la persiste en data/.fernet_key."""
    s = get_settings()
    if s.fernet_key:
        return s.fernet_key
    archivo = BASE_DIR / "data" / ".fernet_key"
    if archivo.exists():
        return archivo.read_text().strip()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    clave = Fernet.generate_key().decode()
    archivo.write_text(clave)
    return clave


def obtener_clave_privacidad() -> str:
    """Clave HMAC estable para seudonimizar clientes importados."""
    s = get_settings()
    if s.data_privacy_key:
        return s.data_privacy_key
    archivo = BASE_DIR / "data" / ".privacy_key"
    if archivo.exists():
        return archivo.read_text().strip()
    import secrets
    archivo.parent.mkdir(parents=True, exist_ok=True)
    clave = secrets.token_urlsafe(48)
    archivo.write_text(clave)
    return clave


