from __future__ import annotations

import argparse
import os
from pathlib import Path

from common.env import parse_env_file

from integrations.feishu.lark_document_gateway import (
    build_production_lark_document_gateway,
)

from .account import (
    AccountAuthService,
    AccountDatabase,
    AccountDatabaseSettings,
    AccountRegistrationService,
    AccountSchemaService,
    MEDIA_CALLBACK_PATH,
    MediaFeishuLoginService,
)
from .adapters.http_api import AuthConfig, HttpAuthorityConfig, load_auth_environment, make_server
from .app import OpenClawApp
from .services.capability_matcher import CapabilityMatcher
from .services.device_job_service import DeviceJobService
from .services.device_job_store import DeviceJobStore
from .services.media_archive_service import MediaArchiveService
from .services.media_archive_store import MediaArchiveStore
from .services.media_task_repository import PostgresMediaTaskRepository
from .services.media_task_runner import MediaTaskRunner
from .services.media_web_tasks import MediaWebTaskService
from .services.retail_billing import RetailBillingService
from .services.retail_admin import RetailAdminService
from .services.retail_fulfillment import RetailFulfillmentService, load_redemption_secret
from .services.stock_usage_reconciliation import StockUsageReconciler
from .services.tenant_model_transport import TenantModelGateway
from .services.upstream_gateway_credentials import CanonicalFileSecretStore, PlatformCredentialService
from .services.media_business.assets import AssetPreviewService, AssetsService
from .services.media_business.document_resources import DocumentResourceService
from .services.media_business.lark_base_projection import LarkBaseProjection
from .services.feishu_service import FeishuService
from .services.stage1_administrator_authorization import Stage1AdministratorAuthorizer
from .services.stage1_feishu_provisioning_gateway import Stage1FeishuProvisioningGateway
from .services.stage1_provisioning_runtime import build_stage1_provisioning_runtime
from .services.resource_owner_registry import ResourceOwnerRegistry
from .services.resource_access import ResourceAccessService
from .services.tenant_projection import CanonicalCreationRunOwnerAccessor, TenantProjectionService
from .services.tenant_projection_vault import MediaVaultTenantProjectionReader
from .services.media_business.admin_access import AdminAccessService
from .services.media_business.admin_billing import AdminBillingService
from .services.media_business.admin_overview import AdminOverviewService
from .services.media_business.admin_tenants import AdminTenantsService
from .services.media_business.admin_upstreams import AdminUpstreamsService
from .services.media_business.admin_platform_cookies import AdminPlatformCookiesService
from .services.media_business.assets import AssetsService
from .services.media_business.decisions import DecisionsService
from .services.media_business.documents import DocumentsService
from .services.media_business.invites import InvitesService
from .services.media_business.overview import OverviewService
from .services.media_business.publishing import PublishingService
from .services.media_business.reviews import ReviewsService
from .services.media_business.runs import RunsService
from .services.media_business.source_asset_projection import (
    SourceAssetProjection,
    project_growth_source_asset,
)
from .services.media_business.tracks import H00AccountMonitorAdapter, TracksService
from .services.media_business.usage_billing import UsageBillingService


def _load_environment_file(path: Path) -> dict[str, str]:
    # Thin wrapper over the canonical parser (dedup pe-01): this reader's
    # rules -- matched-pair quote slicing, `export ` prefix, missing file ->
    # {} -- already matched common.env.parse_env_file byte-for-byte.
    return parse_env_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw Media HTTP API or task runner")
    parser.add_argument("--mode", choices=("http", "runner"), default="http")
    parser.add_argument("--settings", default="/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml")
    parser.add_argument("--auth-env", default="/home/ubuntu/.config/openclaw-bot-center/auth.env")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--public-origin", default=os.getenv("OPENCLAW_MEDIA_PUBLIC_ORIGIN", ""))
    parser.add_argument(
        "--openclaw-config",
        default=os.getenv("OPENCLAW_CONFIG_PATH", "/home/ubuntu/.openclaw/openclaw.json"),
    )
    parser.add_argument(
        "--runner-public-id",
        default=os.getenv("OPENCLAW_MEDIA_RUNNER_PUBLIC_ID", ""),
    )
    parser.add_argument(
        "--executor-public-id",
        default=os.getenv("OPENCLAW_MEDIA_EXECUTOR_PUBLIC_ID", ""),
    )
    parser.add_argument(
        "--runner-lease-seconds",
        type=int,
        default=int(os.getenv("OPENCLAW_MEDIA_RUNNER_LEASE_SECONDS", "60")),
    )
    parser.add_argument(
        "--runner-heartbeat-seconds",
        type=float,
        default=float(os.getenv("OPENCLAW_MEDIA_RUNNER_HEARTBEAT_SECONDS", "0")),
    )
    parser.add_argument(
        "--runner-poll-seconds",
        type=float,
        default=float(os.getenv("OPENCLAW_MEDIA_RUNNER_POLL_SECONDS", "1")),
    )
    parser.add_argument("--runner-once", action="store_true")
    parser.add_argument(
        "--feishu-application-ref",
        default=os.getenv("OPENCLAW_MEDIA_FEISHU_APPLICATION_REF", ""),
    )
    parser.add_argument(
        "--trusted-proxy-cidr",
        action="append",
        default=[
            value.strip()
            for value in os.getenv("OPENCLAW_MEDIA_TRUSTED_PROXY_CIDRS", "").split(",")
            if value.strip()
        ],
    )
    parser.add_argument(
        "--device-job-db",
        default=os.getenv("OPENCLAW_DEVICE_JOB_DB_PATH", "/home/ubuntu/.openclaw/state/device_jobs.sqlite3"),
    )
    parser.add_argument(
        "--resource-owner-db",
        default=os.getenv("OPENCLAW_RESOURCE_OWNER_DB_PATH", "/home/ubuntu/.openclaw/state/resource_owners.sqlite3"),
    )
    parser.add_argument(
        "--media-vault-root",
        default=os.getenv("OPENCLAW_MEDIA_VAULT_ROOT", "/home/ubuntu/selfmedia-tools/data/media_vault"),
    )
    parser.add_argument(
        "--document-resource-root",
        default=os.getenv(
            "OPENCLAW_MEDIA_DOCUMENT_RESOURCE_ROOT",
            "/home/ubuntu/.openclaw/media-document-resources",
        ),
    )
    parser.add_argument(
        "--media-archive-db",
        default=os.getenv("OPENCLAW_MEDIA_ARCHIVE_DB_PATH", "/home/ubuntu/.openclaw/state/media_archives.sqlite3"),
    )
    parser.add_argument(
        "--upstream-credential-state",
        default=os.getenv("OPENCLAW_UPSTREAM_CREDENTIAL_STATE", "/home/ubuntu/.openclaw/state/upstream-credential.json"),
    )
    parser.add_argument(
        "--upstream-token-file",
        default=os.getenv("OPENCLAW_UPSTREAM_TOKEN_FILE", "/home/ubuntu/.config/sub2api-stock/api-token"),
    )
    parser.add_argument(
        "--upstream-staged-token-file",
        default=os.getenv(
            "OPENCLAW_UPSTREAM_STAGED_TOKEN_FILE",
            "/home/ubuntu/.config/sub2api-stock/api-token.staged",
        ),
    )
    parser.add_argument(
        "--upstream-admin-token-file",
        default=os.getenv(
            "OPENCLAW_UPSTREAM_ADMIN_TOKEN_FILE",
            "/home/ubuntu/.config/sub2api-stock/admin-token",
        ),
    )
    parser.add_argument(
        "--redemption-hmac-secret-file",
        default=os.getenv(
            "OPENCLAW_REDEMPTION_HMAC_SECRET_FILE",
            "/home/ubuntu/.config/openclaw-billing/redemption-hmac-secret",
        ),
    )
    parser.add_argument(
        "--redemption-export-root",
        default=os.getenv("OPENCLAW_REDEMPTION_EXPORT_ROOT", ""),
    )
    parser.add_argument(
        "--stage1-admin-grants-file",
        default=os.getenv("OPENCLAW_STAGE1_ADMIN_GRANTS_FILE", ""),
    )
    args = parser.parse_args()
    if args.mode == "http" and not args.public_origin:
        raise RuntimeError("OPENCLAW_MEDIA_PUBLIC_ORIGIN or --public-origin is required")

    auth_environment = load_auth_environment(args.auth_env)
    auth_config = AuthConfig.from_environment(auth_environment)
    account_database = AccountDatabase(AccountDatabaseSettings.from_environment(auth_environment))
    AccountSchemaService(account_database).ensure_current()
    account_auth = AccountAuthService(
        account_database,
        csrf_secret=auth_config.session_secret,
        session_ttl_seconds=auth_config.session_ttl_seconds,
    )
    account_registration = AccountRegistrationService(
        account_database,
        account_auth=account_auth,
        code_secret=auth_config.session_secret,
    )
    media_feishu_login = MediaFeishuLoginService.from_openclaw_config(
        args.openclaw_config,
        redirect_uri=args.public_origin.rstrip("/") + MEDIA_CALLBACK_PATH,
    )
    device_job_service = DeviceJobService(
        DeviceJobStore(args.device_job_db, credential_secret=auth_config.session_secret),
    )
    media_archive_service = MediaArchiveService(MediaArchiveStore(args.media_archive_db))
    app = OpenClawApp(args.settings)
    source_asset_binding = LarkBaseProjection(
        app.feishu_service,
        None,
    ).resolve_table_binding("source_asset")
    source_base_token = str(source_asset_binding["base_token"])

    assets_service = AssetsService(account_database.connect, cursor_secret=auth_config.session_secret)
    preview_environment = _load_environment_file(
        Path(os.getenv("OPENCLAW_MEDIA_FEISHU_ENV", "/home/ubuntu/.openclaw/openclaw-feishu-env.conf"))
    )
    preview_app_id = str(preview_environment.get("FEISHU_APP_ID") or "").strip()
    preview_app_secret = str(preview_environment.get("FEISHU_APP_SECRET") or "").strip()
    if not preview_app_id or not preview_app_secret:
        raise RuntimeError("media preview Feishu credentials are unavailable")
    preview_feishu = FeishuService(
        "api",
        "/tmp/openclaw-media-preview",
        app_id=preview_app_id,
        app_secret=preview_app_secret,
        api_base_url=app.feishu_service.api_base_url,
    )
    app.router.media_source_feishu_service = preview_feishu
    asset_preview_service = AssetPreviewService(
        account_database.connect,
        preview_feishu,
        base_token=source_base_token,
        cache_root=Path(
            os.getenv(
                "OPENCLAW_MEDIA_PREVIEW_CACHE_ROOT",
                str(Path.home() / ".local/share/openclaw/media-preview-cache"),
            )
        ),
    )
    document_resource_service = DocumentResourceService(
        account_database.connect,
        resource_root=args.document_resource_root,
    )
    owner_registry = ResourceOwnerRegistry(args.resource_owner_db)
    resource_access = ResourceAccessService(owner_registry)
    projection_service = TenantProjectionService(
        MediaVaultTenantProjectionReader(owner_registry, vault_root=args.media_vault_root),
        CanonicalCreationRunOwnerAccessor(owner_registry),
    )
    upstream_endpoint = str(os.environ.get("OPENCLAW_SUB2API_BASE_URL") or "").strip()
    if not upstream_endpoint:
        raise RuntimeError("OPENCLAW_SUB2API_BASE_URL is required")
    credential_service = PlatformCredentialService(
        args.upstream_credential_state,
        CanonicalFileSecretStore(args.upstream_token_file, args.upstream_staged_token_file),
    )
    if not credential_service.state_path.exists():
        credential_service.adopt_existing()
    tenant_model_gateway = TenantModelGateway(
        credential_service,
        RetailBillingService(account_database),
        StockUsageReconciler(upstream_endpoint, args.upstream_admin_token_file),
        sub2api_base_url=upstream_endpoint,
    )
    retail_fulfillment = RetailFulfillmentService(
        account_database,
        code_secret=load_redemption_secret(args.redemption_hmac_secret_file),
        export_root=args.redemption_export_root,
    )
    retail_admin = RetailAdminService(account_database)
    source_asset_projection = SourceAssetProjection(
        account_database.connect,
        owner_registry=owner_registry,
    )
    app.router.source_asset_projection = source_asset_projection
    task_repository = PostgresMediaTaskRepository(account_database.connect)
    media_web_tasks = MediaWebTaskService(
        app,
        repository=task_repository,
        tenant_model_gateway=tenant_model_gateway,
        content_flow_client=app.router.content_flow_client,
    )
    if args.mode == "runner":
        tenant_model_gateway.prepare()
        application_ref = str(args.feishu_application_ref or "").strip()
        if not application_ref and preview_app_id:
            application_ref = f"feishu-app:{preview_app_id}"
        runner = MediaTaskRunner(
            app,
            task_repository,
            media_web_tasks,
            runner_public_id=args.runner_public_id,
            executor_public_id=args.executor_public_id,
            tenant_model_gateway=tenant_model_gateway,
            lease_seconds=args.runner_lease_seconds,
            heartbeat_seconds=(
                args.runner_heartbeat_seconds
                if args.runner_heartbeat_seconds > 0
                else None
            ),
            declared_application_ref=application_ref,
        )
        if args.runner_once:
            runner.run_once()
            return 0
        print("media task runner started", flush=True)
        try:
            runner.run_forever(poll_seconds=args.runner_poll_seconds)
        except KeyboardInterrupt:
            return 0
    secret = auth_config.session_secret
    stage1_authorizer = Stage1AdministratorAuthorizer(
        account_database.connect,
        args.stage1_admin_grants_file,
    )

    def resolve_stage1_resource_target(context):
        target = stage1_authorizer.resource_target_for_context(context)
        if target is None:
            raise RuntimeError("Stage 1 Feishu resource target is not configured")
        return target

    stage1_credential_ref = str(
        os.environ.get("OPENCLAW_STAGE1_FEISHU_CREDENTIAL_REF") or ""
    ).strip()

    def resolve_stage1_feishu_client(context):
        # The normal media Feishu client is not a Stage 1 credential fallback.
        # It may be selected only by an explicit binding credential mapping.
        if not stage1_credential_ref or context.credential_ref != stage1_credential_ref:
            raise RuntimeError("Stage 1 Feishu credential client is not configured for this binding")
        return app.feishu_service

    stage1_gateway = Stage1FeishuProvisioningGateway(
        app.feishu_service,
        target_resolver=resolve_stage1_resource_target,
        credential_client_resolver=resolve_stage1_feishu_client,
    )
    stage1_runtime = build_stage1_provisioning_runtime(
        account_database.connect,
        stage1_gateway,
        administrator_grants_file=args.stage1_admin_grants_file,
        administrator_authorizer=stage1_authorizer,
        resource_target_resolver=resolve_stage1_resource_target,
    )
    feishu_document_config = app.settings.get("feishu") or {}
    lark_gateway = build_production_lark_document_gateway(
        app.feishu_service,
        account_database.connect,
        feishu_document_config.get("document_bindings"),
        resources=feishu_document_config.get("document_resources"),
    )
    monitor_url = os.getenv("FEISHU_ACCOUNT_MONITOR_URL", "").strip()
    monitor_adapter = None
    if monitor_url:
        def monitor_binding_validator(tenant_id: str, public_account_id: str) -> bool:
            with account_database.connect() as connection:
                return connection.execute(
                    "SELECT 1 FROM media_product.owned_media_accounts WHERE tenant_id = %s AND public_id = %s",
                    (tenant_id, public_account_id),
                ).fetchone() is not None
        def monitor_account_metadata(tenant_id: str, public_account_id: str) -> dict[str, str] | None:
            with account_database.connect() as connection:
                row = connection.execute(
                    "SELECT canonical_data FROM media_product.owned_media_accounts WHERE tenant_id = %s AND public_id = %s",
                    (tenant_id, public_account_id),
                ).fetchone()
            if not row:
                return None
            data = row[0] if isinstance(row, (tuple, list)) else row
            if not isinstance(data, dict):
                return None
            return {
                "account_name": str(data.get("account_name") or data.get("accountName") or "").strip(),
                "platform": str(data.get("platform") or "").strip(),
            }
        monitor_adapter = H00AccountMonitorAdapter(
            monitor_url,
            view_id=os.getenv("FEISHU_ACCOUNT_MONITOR_VIEW_ID", "").strip(),
            binding_validator=monitor_binding_validator,
            account_metadata=monitor_account_metadata,
        )
    media_business_services = {
        "overview": OverviewService(account_database.connect, task_reader=media_web_tasks, cursor_secret=secret),
        "tracks": TracksService(account_database.connect, cursor_secret=secret, monitor_adapter=monitor_adapter),
        "assets": assets_service,
        "decisions": DecisionsService(account_database.connect, cursor_secret=secret, public_id_secret=secret),
        "runs": RunsService(account_database.connect, cursor_secret=secret),
        "publishing": PublishingService(account_database.connect, cursor_secret=secret, public_id_secret=secret),
        "reviews": ReviewsService(account_database.connect, cursor_secret=secret, public_id_secret=secret),
        "usage_billing": UsageBillingService(
            account_database.connect,
            cursor_secret=secret,
            redemption_service=retail_fulfillment,
        ),
        "invites": InvitesService(account_database.connect, public_id_secret=secret, cursor_secret=secret),
        "admin_overview": AdminOverviewService(account_database),
        "admin_access": AdminAccessService(
            account_database,
            public_id_secret=secret,
            cursor_secret=secret,
            registration_service=account_registration,
        ),
        "admin_tenants": AdminTenantsService(account_database, public_id_secret=secret, cursor_secret=secret),
        "admin_billing": AdminBillingService(
            account_database,
            public_id_secret=secret,
            retail_admin=retail_admin,
            retail_fulfillment=retail_fulfillment,
        ),
        "admin_upstreams": AdminUpstreamsService(account_database, upstream_gateway=tenant_model_gateway),
        "admin_platform_cookies": AdminPlatformCookiesService(),
        "documents": DocumentsService(account_database.connect, lark_gateway=lark_gateway, cursor_secret=secret),
    }
    app.router.publishing_service = media_business_services["publishing"]
    tenant_model_gateway.prepare()
    server = make_server(
        args.host,
        args.port,
        app,
        auth_config=auth_config,
        account_auth=account_auth,
        account_registration=account_registration,
        media_feishu_login=media_feishu_login,
        matcher=CapabilityMatcher(),
        guidance_plan_service=app.guidance_plan_service,
        tenant_model_gateway=tenant_model_gateway,
        retail_admin_service=retail_admin,
        retail_fulfillment_service=retail_fulfillment,
        device_job_service=device_job_service,
        media_archive_service=media_archive_service,
        media_web_tasks=media_web_tasks,
        media_business_services=media_business_services,
        tenant_projection_service=projection_service,
        assets_service=assets_service,
        asset_preview_service=asset_preview_service,
        document_resource_service=document_resource_service,
        resource_access_service=resource_access,
        authority_config=HttpAuthorityConfig(
            args.public_origin,
            tuple(args.trusted_proxy_cidr),
        ),
        stage1_provisioning=stage1_runtime,
    )
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main())
