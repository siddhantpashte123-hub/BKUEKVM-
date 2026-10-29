"""Application settings loaded from environment variables / .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BLUEKVM_", extra="ignore")

    env: str = "production"
    host: str = "0.0.0.0"
    port: int = 8080
    public_url: str = "http://localhost:8080"
    secret_key: str = "dev-insecure-secret-change-me"
    credential_key: str = ""

    # Database is read without the BLUEKVM_ prefix (standard DATABASE_URL)
    database_url: str = Field(
        default="sqlite:///./data/bluekvm.db",
        validation_alias="DATABASE_URL",
    )

    admin_username: str = "admin"
    admin_email: str = "admin@localhost"
    admin_password: str = ""

    session_ttl_minutes: int = 720
    cookie_secure: bool = True
    csrf_enabled: bool = True
    login_rate_per_minute: int = 8

    libvirt_uri: str = "qemu:///system"
    vm_storage_dir: str = "/var/lib/bluekvm/vms"
    template_dir: str = "/var/lib/bluekvm/templates"
    backup_dir: str = "/var/lib/bluekvm/backups"
    default_bridge: str = ""
    default_network: str = "default"

    # Hosted sshx.io sessions are bearer links: keep them short-lived and
    # terminate the local relay process at expiry. The URL is never stored.
    sshx_binary: str = "/usr/local/bin/sshx"
    sshx_runtime_dir: str = "/run/bluekvm/sshx"
    sshx_known_hosts_dir: str = "/var/lib/bluekvm/sshx-known-hosts"
    sshx_session_ttl_seconds: int = 900

    log_level: str = "INFO"
    log_dir: str = "/var/log/bluekvm"

    @property
    def is_dev(self) -> bool:
        return self.env.lower() in ("dev", "development", "test")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Ensure local data directories exist when using SQLite/default paths
    for path in (settings.vm_storage_dir, settings.template_dir, settings.backup_dir):
        if path.startswith(("/var/lib", "/var/log")) and os.geteuid() != 0 and not Path(path).exists():
            continue
        Path(path).mkdir(parents=True, exist_ok=True)
    if settings.is_sqlite:
        db_path = settings.database_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
