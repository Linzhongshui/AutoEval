import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    evaluation_follow_up_enabled: bool = False
    enforce_task_budget: bool = False
    billing_execution_config: Path | None = None
    langfuse_host: str | None = None
    langfuse_browser_url: str | None = None
    langfuse_project_id: str | None = None
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_content_mode: Literal["structural", "full"] = "full"
    archived_manifest_ids: list[uuid.UUID] = []
    archived_compilation_ids: list[uuid.UUID] = []
    planning_container_config: str | None = None
    model_config = SettingsConfigDict(env_prefix="AE_", env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["local", "oauth"] = "local"
    # 逗号分隔的纯文本列表（NoDecode 跳过 pydantic-settings 的 JSON 解码）
    oauth_enabled_providers: Annotated[list[str], NoDecode] = ["github", "gitcode"]
    # 首管理员引导白名单：provider:provider_uid（稳定标识，而非可变登录名）
    admin_accounts: Annotated[list[str], NoDecode] = []
    # 首超级管理员引导白名单：provider:provider_uid；仅账号创建时生效
    superadmin_accounts: Annotated[list[str], NoDecode] = []
    github_client_id: SecretStr = SecretStr("")
    github_client_secret: SecretStr = SecretStr("")
    gitcode_client_id: SecretStr = SecretStr("")
    gitcode_client_secret: SecretStr = SecretStr("")
    oauth_redirect_base: str = "http://127.0.0.1:8000"
    frontend_origin: str = "http://127.0.0.1:5173"
    session_ttl_hours: int = Field(default=168, ge=1, le=8760)
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://autoeval:autoeval@127.0.0.1:5432/autoeval"
    )
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_bucket: str = "autoeval-evidence"
    s3_access_key: SecretStr = SecretStr("local-development")
    s3_secret_key: SecretStr = SecretStr("local-development-only")
    dependency_timeout_seconds: float = 3.0
    poll_seconds: float = 5.0
    secret_store_path: Path = Path(".secrets")
    unified_fixture_config: Path | None = None
    aisbench_monitor_config: Path | None = None
    aisbench_lock_path: Path = Path("tool-locks/aisbench.json")
    gpqa_activity_queue: str = "demo.gpqa.v1"
    gpqa_workflow_queue: str = "demo.workflow.v1"
    analysis_target_id: uuid.UUID | None = None
    analysis_resource_id: uuid.UUID | None = None
    analysis_activity_queue: str = "demo.result.v1"
    analysis_workflow_queue: str = "demo.workflow.v1"
    analysis_max_output_tokens: int = Field(default=2048, ge=1, le=4096)
    analysis_runner: Literal["native", "openai_compatible"] = "native"
    analysis_short_citations: bool = False
    evaluation_origin: Literal["real", "simulation"] = "real"
    allowed_model_hosts: list[str] = ["api.deepseek.com"]
    docker_executable: str = "docker"

    @field_validator(
        "oauth_enabled_providers", "admin_accounts", "superadmin_accounts", mode="before"
    )
    @classmethod
    def split_csv_list(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def production_identity_config(self):
        # 免登录（local）模式仅限开发/测试环境；正式环境必须走 OAuth：
        # 至少配置一个平台的完整应用凭据，且前端源/回调必须是非本机地址，
        # 否则拒绝启动（维护接口自然随之受限，data workbench 亦拒绝生产环境）。
        if self.environment != "production":
            return self
        if self.auth_mode != "oauth":
            raise ValueError(
                "Production requires OAuth identity; AE_AUTH_MODE=local is development only"
            )
        providers_ready = (
            self.github_client_id.get_secret_value()
            and self.github_client_secret.get_secret_value()
        ) or (
            self.gitcode_client_id.get_secret_value()
            and self.gitcode_client_secret.get_secret_value()
        )
        if not providers_ready:
            raise ValueError(
                "Production OAuth requires at least one fully configured provider "
                "(GitHub or GitCode application credentials)"
            )
        if not (self.superadmin_accounts or self.admin_accounts):
            raise ValueError(
                "Production requires at least one bootstrap account "
                "(AE_SUPERADMIN_ACCOUNTS or AE_ADMIN_ACCOUNTS with provider:provider_uid), "
                "otherwise the platform could end up with no privileged account"
            )
        loopback = ("http://localhost", "http://127.0.0.1")
        if self.oauth_redirect_base.startswith(loopback) or self.frontend_origin.startswith(
            loopback
        ):
            raise ValueError("Production requires a public frontend origin and OAuth redirect base")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
