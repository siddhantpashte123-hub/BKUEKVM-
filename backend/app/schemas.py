"""Pydantic request/response schemas with strict input validation."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

# ------------------------------------------------------------------ auth --
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    user: "UserOut"
    csrf_token: str
    expires_at: datetime


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        classes = [
            any(c.islower() for c in value),
            any(c.isupper() for c in value),
            any(c.isdigit() for c in value),
            any(not c.isalnum() for c in value),
        ]
        if sum(classes) < 3:
            raise ValueError(
                "Password must contain at least three of: lowercase, uppercase, digit, symbol"
            )
        return value


# ------------------------------------------------------------------ users --
class RoleOut(BaseModel):
    id: int
    name: str
    permissions: list[str]
    is_system: bool

    model_config = {"from_attributes": True}

    @field_validator("permissions", mode="before")
    @classmethod
    def _parse_permissions(cls, value):
        if isinstance(value, str):
            return json.loads(value or "[]")
        return value


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=512)
    role_id: int
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role_id: int | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role_id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class LoginHistoryOut(BaseModel):
    id: int
    username: str
    ip_address: str
    success: bool
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


# -------------------------------------------------------------------- VPS --
class VPSCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    hostname: str = Field(min_length=2, max_length=253)
    description: str = Field(default="", max_length=1024)
    owner_id: int | None = None
    template_id: int
    node_id: int | None = None  # None = automatic placement
    vcpus: int = Field(ge=1, le=64)
    ram_mb: int = Field(ge=256, le=262144)
    disk_gb: int = Field(ge=5, le=16384)
    network_id: int | None = None
    ip_address: str = ""
    mac_address: str = Field(default="", pattern=r"^$|^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
    ssh_public_key: str = Field(default="", max_length=8192)
    expires_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class VPSOut(BaseModel):
    id: int
    public_id: str
    name: str
    hostname: str
    description: str
    owner_id: int | None
    node_id: int
    template_id: int
    vcpus: int
    ram_mb: int
    disk_gb: int
    status: str
    power_state: str
    last_error: str
    ip_address: str
    mac_address: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VPSDetailOut(VPSOut):
    ssh_public_key: str
    node_name: str = ""
    template_name: str = ""
    stats: dict[str, Any] | None = None


class LifecycleRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


# ------------------------------------------------------------------- nodes --
class NodeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    address: str = Field(min_length=2, max_length=255)
    libvirt_uri: str = Field(min_length=4, max_length=512)
    credential: str = Field(default="", max_length=1024)
    is_local: bool = False


class NodeUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    status: str | None = None


class NodeOut(BaseModel):
    id: int
    name: str
    address: str
    libvirt_uri: str
    is_local: bool
    status: str
    hypervisor_version: str
    cpu_cores: int
    ram_mb: int
    kvm_ready: bool
    last_health_at: datetime | None
    last_error: str
    created_at: datetime
    vm_count: int = 0

    model_config = {"from_attributes": True}


# --------------------------------------------------------------- templates --
class TemplateOut(BaseModel):
    id: int
    name: str
    os_family: str
    version: str
    arch: str
    image_url: str
    checksum_sha256: str
    size_bytes: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------ infra / misc --
class NetworkOut(BaseModel):
    id: int
    name: str
    network_type: str
    bridge: str
    subnet: str
    dhcp_enabled: bool
    status: str

    model_config = {"from_attributes": True}


class StoragePoolOut(BaseModel):
    id: int
    node_id: int | None
    name: str
    pool_type: str
    path: str
    capacity_bytes: int
    used_bytes: int
    status: str

    model_config = {"from_attributes": True}


class BackupOut(BaseModel):
    id: int
    vps_id: int
    backup_type: str
    status: str
    snapshot_name: str
    path: str
    size_bytes: int
    note: str
    error: str
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: int
    vps_id: int | None
    task_type: str
    status: str
    progress: int
    steps: list[dict]
    logs: str
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}

    @field_validator("steps", mode="before")
    @classmethod
    def _parse_steps(cls, value):
        if isinstance(value, str):
            return json.loads(value or "[]")
        return value

    @field_validator("status", mode="before")
    @classmethod
    def _enum_to_value(cls, value):
        return value.value if hasattr(value, "value") else value


class AuditOut(BaseModel):
    id: int
    user_id: int | None
    action: str
    resource_type: str
    resource_id: str
    ip_address: str
    details: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConsoleSessionOut(BaseModel):
    console_token: str
    vps_id: int
    expires_at: datetime
    ws_path: str


class SettingUpdate(BaseModel):
    value: Any


class Message(BaseModel):
    message: str


LoginResponse.model_rebuild()
