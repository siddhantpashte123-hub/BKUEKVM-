"""Keep fresh installation and deployment port defaults consistent."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_installer_default_port():
    result = subprocess.run(
        ["bash", "-c", '. "$1"; printf "%s" "$PANEL_PORT"', "_", str(ROOT / "installer/lib.sh")],
        check=True, text=True, capture_output=True,
    )
    assert result.stdout == "8989"


def test_deployment_port_and_configured_systemd_override():
    unit = (ROOT / "deployment/bluekvm-api.service").read_text()
    assert "Environment=BLUEKVM_PORT=8989" in unit
    assert "EnvironmentFile=/opt/bluekvm/.env" in unit
    assert "--port ${BLUEKVM_PORT}" in unit
    assert '"8989:8989"' in (ROOT / "compose.yaml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "EXPOSE 8989" in dockerfile
    assert '"--port", "8989"' in dockerfile
    assert "127.0.0.1:8989/health/live" in dockerfile
    assert "127.0.0.1:8989" in (ROOT / "frontend/vite.config.ts").read_text()


def test_application_defaults_to_8989():
    from app.config import Settings

    settings = Settings(_env_file=None, BLUEKVM_PORT=8989)
    # Explicit assertions for the model defaults avoid inheriting fixture env.
    assert Settings.model_fields["port"].default == 8989
    assert Settings.model_fields["public_url"].default == "http://localhost:8989"
    assert settings.port == 8989
