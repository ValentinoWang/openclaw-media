from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass, replace
import getpass
import json
import math
import os
import sys
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version
from typing import Sequence

from .doctor import run_doctor
from .credentials import CredentialStoreError, KeyringCredentialStore
from .provider_config import (
    ProviderConfigError,
    ProviderConfigRepository,
    ProviderConfigService,
)
from .catalog import CatalogError, InstalledCatalog
from .agent import Agent, AgentError, AgentState, AgentStateStore
from .archive_client import ArchiveClient, ArchiveClientError
from .device_credentials import DeviceCredentialError, DeviceCredentialStore
from .launchd import LaunchdError, LaunchdManager
from .node_registry import NodeRegistry
from .pipeline_runtime import PipelineRuntime
from .provider_adapter import ProviderAdapter
from .remote_client import RemoteClient, RemoteError
from .run import execute_descriptor


_DISTRIBUTION_NAME = "openclaw-media"

_CLI_ERROR_GUIDANCE: dict[str, tuple[str, str]] = {
    "catalog_rejected": ("本地流程目录未通过校验", "更新流程目录后重试。"),
    "credential_cleanup_failed": ("设备已撤销，但本机凭据尚未清理完成", "重新执行设备撤销以完成清理。"),
    "invalid_credential": ("凭据无效或未提供", "重新输入有效凭据后重试。"),
    "invalid_descriptor": ("流程请求描述格式无效", "检查 --descriptor-json 后重试。"),
    "invalid_manifest": ("归档清单格式无效", "重新导出清单后重试。"),
    "invalid_min_age_seconds": ("清理保留时长无效", "使用大于或等于 0 的有限秒数。"),
    "launchctl_failed": ("macOS 服务管理命令执行失败", "检查 launchctl 状态后重试。"),
    "launchctl_unavailable": ("找不到 macOS 服务管理命令", "请在 macOS 上运行并确认 launchctl 可用。"),
    "launchd_not_installed": ("本地服务尚未安装", "先运行 openclaw-media launchd install。"),
    "launchd_not_running": ("本地服务未能启动", "检查 launchctl 状态和服务日志。"),
    "macos_required": ("此命令只能在 macOS 上运行", "请在已配对的 Mac 上执行。"),
    "not_paired": ("这台设备尚未配对", "先运行 openclaw-media pair 完成配对。"),
    "provider_key_argv_forbidden": ("为保护凭据，不能通过命令行参数提供 API 密钥", "请通过标准输入提供 API 密钥。"),
    "session_not_configured": ("尚未配置所有者会话凭据", "先运行 openclaw-media session 并通过标准输入提供凭据。"),
    "workspace_not_configured": ("未找到可用的本地工作区", "使用 --workspace 指定一个存在的目录。"),
}


def _cli_error_code(error: object) -> str:
    candidate = error if isinstance(error, str) else getattr(error, "code", "")
    if isinstance(candidate, str) and candidate and all(
        character.isascii() and (character.isalnum() or character == "_")
        for character in candidate
    ):
        return candidate
    return "operation_failed"


def _emit_cli_error(error: object, *, json_output: bool = False) -> None:
    code = _cli_error_code(error)
    if json_output:
        print(json.dumps({"error": {"code": code}}, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return
    detail, next_step = _CLI_ERROR_GUIDANCE.get(
        code,
        ("操作未完成", "检查输入和本地配置后重试。"),
    )
    print(f"openclaw-media: error: {code} — {detail}；{next_step}", file=sys.stderr)


def _installed_version() -> str:
    """Read the version from the installed distribution, the sole release SSOT."""

    return version(_DISTRIBUTION_NAME)


def build_parser(package_version: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openclaw-media",
        description="Media Agent CLI for local OpenClaw media pipelines.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {package_version}",
    )
    config = parser.add_subparsers(dest="command")
    doctor = config.add_parser("doctor", help="verify local runtime dependencies")
    doctor.add_argument("--json", action="store_true", help="emit the versioned machine-readable report")
    config_parser = config.add_parser("config", help="manage local configuration")
    provider_commands = config_parser.add_subparsers(dest="config_command")
    provider = provider_commands.add_parser("provider", help="manage a local provider")
    provider.add_argument("provider_action", choices=("create", "update", "rotate", "read", "delete"))
    provider.add_argument("--id", dest="config_id")
    provider.add_argument("--base-url")
    provider.add_argument("--model")
    provider.add_argument("--model-label")
    provider.add_argument("--local-endpoint", action="store_true")
    run = config.add_parser("run", help="execute an installed local pipeline")
    run.add_argument("pipeline_id")
    run.add_argument("--descriptor-json", required=True)
    run.add_argument("--workspace")
    pair = config.add_parser("pair", help="pair this Mac with the remote Media service")
    pair.add_argument("--base-url", required=True)
    pair.add_argument("--pair-code", "--code", dest="pair_code", required=True)
    pair.add_argument("--device-label", required=True)
    pair.add_argument("--client-version", default=package_version)
    pair.add_argument("--workspace")
    pair.add_argument("--agent-dir")
    pair.add_argument("--local-endpoint", action="store_true")
    agent = config.add_parser("agent", help="run or inspect the local outbound agent")
    agent_commands = agent.add_subparsers(dest="agent_command")
    agent_run = agent_commands.add_parser("run", help="run one agent cycle or foreground loop")
    agent_run.add_argument("--once", action="store_true")
    agent_run.add_argument("--foreground", action="store_true")
    agent_run.add_argument("--interval", type=float, default=30.0)
    agent_run.add_argument("--agent-dir")
    agent_run.add_argument("--workspace")
    agent_run.add_argument("--local-endpoint", action="store_true")
    agent_status = agent_commands.add_parser("status", help="show redacted agent state")
    agent_status.add_argument("--agent-dir")
    agent = config.add_parser("archive", help="confirm and operate small remote archive artifacts")
    archive_commands = agent.add_subparsers(dest="archive_command")
    confirm = archive_commands.add_parser("confirm")
    confirm.add_argument("--manifest-json", required=True)
    confirm.add_argument("--confirmation-ref", required=True)
    commit = archive_commands.add_parser("commit")
    commit.add_argument("--base-url", required=True)
    commit.add_argument("--run-id", required=True)
    commit.add_argument("--manifest-json", required=True)
    commit.add_argument("--confirmation-ref", required=True)
    commit.add_argument("--agent-dir")
    commit.add_argument("--local-endpoint", action="store_true")
    archive_list = archive_commands.add_parser("list")
    archive_list.add_argument("--base-url", required=True)
    archive_list.add_argument("--agent-dir")
    archive_list.add_argument("--local-endpoint", action="store_true")
    readback = archive_commands.add_parser("readback")
    readback.add_argument("--base-url", required=True)
    readback.add_argument("--archive-id", required=True)
    readback.add_argument("--receipt-ref", required=True)
    readback.add_argument("--agent-dir")
    readback.add_argument("--local-endpoint", action="store_true")
    delete = archive_commands.add_parser("delete")
    delete.add_argument("--base-url", required=True)
    delete.add_argument("--archive-id", required=True)
    delete.add_argument("--confirmation-ref", required=True)
    delete.add_argument("--expected-revision", required=True, type=int)
    delete.add_argument("--readback-receipt-ref")
    delete.add_argument("--agent-dir")
    delete.add_argument("--local-endpoint", action="store_true")
    gc = config.add_parser("gc", help="garbage-collect unreferenced local blobs")
    gc.add_argument("--workspace")
    gc.add_argument("--agent-dir")
    gc.add_argument("--apply", action="store_true")
    gc.add_argument("--min-age-seconds", type=float, default=14 * 86400)
    launchd = config.add_parser("launchd", help="manage the macOS foreground agent service")
    launchd_commands = launchd.add_subparsers(dest="launchd_command")
    install = launchd_commands.add_parser("install")
    install.add_argument("--workspace")
    install.add_argument("--agent-dir")
    install.add_argument("--no-start", action="store_true")
    status = launchd_commands.add_parser("status")
    status.add_argument("--agent-dir")
    restart = launchd_commands.add_parser("restart")
    restart.add_argument("--agent-dir")
    uninstall = launchd_commands.add_parser("uninstall")
    uninstall.add_argument("--agent-dir")
    session = config.add_parser("session", help="configure an owner session credential from stdin")
    session.add_argument("session_action", nargs="?", choices=("configure", "set"), default="configure")
    session.add_argument("--agent-dir")
    device = config.add_parser("device", help="manage the paired device")
    device_commands = device.add_subparsers(dest="device_command")
    revoke = device_commands.add_parser("revoke")
    revoke.add_argument("--base-url", required=True)
    revoke.add_argument("--expected-revision", required=True, type=int)
    revoke.add_argument("--agent-dir")
    revoke.add_argument("--local-endpoint", action="store_true")
    return parser


def _agent_dir(value: str | None = None) -> Path:
    root = value or os.environ.get("OPENCLAW_MEDIA_AGENT_DIR")
    return Path(root).expanduser() if root else Path.home() / ".openclaw-media" / "agent"


def _agent_store(value: str | None = None) -> AgentStateStore:
    return AgentStateStore(_agent_dir(value) / "state.json")


def _workspace(explicit: str | None, persisted: str | None = None) -> Path:
    value = explicit or persisted or os.environ.get("OPENCLAW_MEDIA_WORKSPACE")
    if not value:
        raise AgentError("workspace_not_configured")
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise AgentError("workspace_not_configured")
    return root


def _json_result(value: object) -> None:
    if hasattr(value, "model_dump_json"):
        print(value.model_dump_json())
    else:
        if is_dataclass(value):
            value = asdict(value)
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _run_doctor_command() -> int:
    report = run_doctor()
    print(report.model_dump_json())
    return 0 if report.status == "healthy" else 1


def _agent_from_state(
    store: AgentStateStore,
    *,
    workspace: str | None = None,
    local_endpoint: bool = False,
) -> tuple[Agent, RemoteClient]:
    state = store.load()
    if not state.remote_base_url or not state.device_id:
        raise AgentError("not_paired")
    root = _workspace(workspace, state.workspace)
    credentials = DeviceCredentialStore()
    remote = RemoteClient(state.remote_base_url, local_endpoint_enabled=local_endpoint)
    return Agent(remote, store, credentials, root, provider=_provider()), remote


def _archive_client(base_url: str, agent_dir: str | None, local_endpoint: bool) -> tuple[ArchiveClient, RemoteClient]:
    store = _agent_store(agent_dir)
    state = store.load()
    if not state.device_id or not state.session_ref:
        raise DeviceCredentialError("session_not_configured")
    credentials = DeviceCredentialStore()
    try:
        session = credentials.get_session(state.device_id)
    except DeviceCredentialError as exc:
        if exc.code == "session_not_found":
            raise DeviceCredentialError("session_not_configured") from exc
        raise
    remote = RemoteClient(base_url, session_credential=session, local_endpoint_enabled=local_endpoint)
    return ArchiveClient(remote, workspace=state.workspace), remote


class _PairResponseContractRemote:
    """Hide non-contract response additions from the pairing state machine."""

    def __init__(self, remote: RemoteClient) -> None:
        self._remote = remote

    def pair(self, **request: str):
        response = self._remote.pair(**request)
        if isinstance(response, dict):
            return {key: value for key, value in response.items() if key != "session_credential"}
        return response

    def __getattr__(self, name: str):
        return getattr(self._remote, name)


def _read_manifest(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ArchiveClientError("invalid_manifest") from exc
    if not isinstance(parsed, dict):
        raise ArchiveClientError("invalid_manifest")
    return parsed


def _run_pair_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    store = _agent_store(opts.agent_dir)
    previous = store.load()
    try:
        workspace = _workspace(opts.workspace, previous.workspace)
        store.save(AgentState(remote_base_url=opts.base_url, workspace=str(workspace), client_version=opts.client_version))
        remote = RemoteClient(opts.base_url, local_endpoint_enabled=opts.local_endpoint)
        agent = Agent(_PairResponseContractRemote(remote), store, DeviceCredentialStore(), workspace, provider=_provider())
        _json_result(agent.pair(pair_code=opts.pair_code, device_label=opts.device_label, client_version=opts.client_version))
        return 0
    except (AgentError, DeviceCredentialError, RemoteError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    finally:
        if "remote" in locals():
            remote.close()


def _run_agent_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    store = _agent_store(opts.agent_dir)
    if opts.agent_command == "status":
        _json_result(store.load())
        return 0
    if opts.agent_command != "run":
        return 2
    try:
        agent, remote = _agent_from_state(store, workspace=opts.workspace, local_endpoint=opts.local_endpoint)
        try:
            if opts.foreground and not opts.once:
                agent.run_forever(interval=opts.interval)
                result = agent.state()
            else:
                result = agent.run_once()
            _json_result(result)
            return 0 if result.status != "blocked" else 1
        finally:
            remote.close()
    except (AgentError, DeviceCredentialError, RemoteError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2


def _run_archive_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    try:
        if opts.archive_command == "confirm":
            manifest = _read_manifest(opts.manifest_json)
            client = ArchiveClient.__new__(ArchiveClient)
            _json_result(client.confirm(manifest, confirmation_ref=opts.confirmation_ref))
            return 0
        client, remote = _archive_client(opts.base_url, opts.agent_dir, opts.local_endpoint)
        try:
            if opts.archive_command == "commit":
                result = client.commit(run_id=opts.run_id, manifest=_read_manifest(opts.manifest_json), confirmation_ref=opts.confirmation_ref)
            elif opts.archive_command == "list":
                result = remote.archive_list()
            elif opts.archive_command == "readback":
                result = client.readback(opts.archive_id, receipt_ref=opts.receipt_ref)
            elif opts.archive_command == "delete":
                result = client.delete(opts.archive_id, confirmation_ref=opts.confirmation_ref, expected_revision=opts.expected_revision, readback_receipt_ref=opts.readback_receipt_ref)
            else:
                return 2
            _json_result(result)
            return 0
        finally:
            remote.close()
    except (DeviceCredentialError, ArchiveClientError, RemoteError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    except Exception as exc:
        # Keep unexpected local/transport failures actionable without exposing raw traces.
        _emit_cli_error(exc, json_output=json_output)
        return 2


def _run_gc_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    try:
        if not math.isfinite(opts.min_age_seconds) or opts.min_age_seconds < 0:
            raise ArchiveClientError("invalid_min_age_seconds")
        state = _agent_store(opts.agent_dir).load()
        workspace_value = opts.workspace or state.workspace
        if not workspace_value:
            raise ArchiveClientError("workspace_not_configured")
        workspace = Path(workspace_value).expanduser().resolve()
        if not workspace.is_dir():
            raise ArchiveClientError("workspace_not_configured")
        result = ArchiveClient.__new__(ArchiveClient)
        result.workspace = workspace
        _json_result(result.gc(dry_run=not opts.apply, min_age_seconds=opts.min_age_seconds))
        return 0
    except (ArchiveClientError, AgentError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    except Exception as exc:
        # GC can fail on local filesystem state; report a stable sanitized CLI error.
        _emit_cli_error(exc, json_output=json_output)
        return 2


def _run_launchd_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    try:
        agent_dir_value = getattr(opts, "agent_dir", None)
        manager = LaunchdManager(
            agent_dir=Path(agent_dir_value).expanduser() if agent_dir_value else None
        )
        if opts.launchd_command == "install":
            result = manager.install(
                workspace=Path(opts.workspace).resolve() if opts.workspace else None,
                start=not opts.no_start,
            )
            _json_result(result)
        elif opts.launchd_command == "status":
            _json_result(manager.status())
        elif opts.launchd_command == "restart":
            _json_result(manager.restart())
        elif opts.launchd_command == "uninstall":
            _json_result(manager.uninstall())
        else:
            return 2
        return 0
    except LaunchdError as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2


def _read_session_credential() -> str:
    try:
        value = sys.stdin.read().rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise DeviceCredentialError("session_not_configured") from exc
    if not value:
        raise DeviceCredentialError("session_not_configured")
    return value


def _read_provider_key() -> str:
    try:
        if sys.stdin.isatty():
            value = getpass.getpass("Provider API key: ")
        else:
            value = sys.stdin.readline()
    except (EOFError, OSError, UnicodeError) as exc:
        raise ProviderConfigError("invalid_credential") from exc
    value = value.rstrip("\r\n") if isinstance(value, str) else ""
    if not value:
        raise ProviderConfigError("invalid_credential")
    return value


def _run_session_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    try:
        store = _agent_store(opts.agent_dir)
        state = store.load()
        if not state.device_id:
            raise DeviceCredentialError("session_not_configured")
        refs = DeviceCredentialStore().put_session(state.device_id, _read_session_credential())
        store.save(replace(state, session_ref=refs.session))
        _json_result({"configured": True, "session_ref": refs.session})
        return 0
    except DeviceCredentialError as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    except AgentError as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2


def _run_device_command(opts: argparse.Namespace, *, json_output: bool = False) -> int:
    if opts.device_command != "revoke":
        return 2
    remote = None
    try:
        store = _agent_store(opts.agent_dir)
        state = store.load()
        if not state.device_id:
            raise DeviceCredentialError("session_not_configured")
        credentials = DeviceCredentialStore()
        already_revoked = state.status == "revoked" and state.last_code in {"device_revoked", "credential_cleanup_failed"}
        if already_revoked:
            response = {"device_id": state.device_id, "revoked": True}
            updated = state
        else:
            try:
                session = credentials.get_session(state.device_id)
            except DeviceCredentialError as exc:
                if exc.code == "session_not_found":
                    raise DeviceCredentialError("session_not_configured") from exc
                raise
            remote = RemoteClient(opts.base_url, session_credential=session, local_endpoint_enabled=opts.local_endpoint)
            response = remote.device_revoke(state.device_id, expected_revision=opts.expected_revision)
            updated = replace(state, status="revoked", last_code="device_revoked")
            # Record remote success before touching either local secret so a
            # retry can finish cleanup without issuing another revoke.
            store.save(updated)
        cleanup_errors: list[str] = []
        try:
            credentials.delete_device(state.device_id)
        except DeviceCredentialError as exc:
            cleanup_errors.append(exc.code)
        try:
            credentials.delete_session(state.device_id)
        except DeviceCredentialError as exc:
            cleanup_errors.append(exc.code)
        if cleanup_errors:
            store.save(replace(updated, status="revoked", last_code="credential_cleanup_failed"))
            _emit_cli_error("credential_cleanup_failed", json_output=json_output)
            return 2
        store.save(replace(updated, status="revoked", last_code="device_revoked", credential_ref=None, session_ref=None))
        _json_result(response)
        return 0
    except DeviceCredentialError as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    except (AgentError, RemoteError) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    finally:
        if remote is not None:
            remote.close()


def _provider() -> ProviderAdapter | None:
    config_id = os.environ.get("OPENCLAW_MEDIA_PROVIDER_ID")
    if not config_id:
        return None
    root = os.environ.get("OPENCLAW_MEDIA_CONFIG_DIR")
    config_root = root if root else os.path.join(os.path.expanduser("~"), ".openclaw-media", "providers")
    try:
        config = ProviderConfigRepository(config_root).load(config_id)
        return ProviderAdapter(config, KeyringCredentialStore())
    except (ProviderConfigError, CredentialStoreError, ValueError):
        return None


def _run_pipeline_command(arguments: list[str], *, json_output: bool = False) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("pipeline_id")
    parser.add_argument("--descriptor-json", required=True)
    parser.add_argument("--workspace")
    try:
        opts = parser.parse_args(arguments[1:])
    except SystemExit:
        return 2
    try:
        descriptor = json.loads(opts.descriptor_json)
    except (TypeError, json.JSONDecodeError):
        _emit_cli_error("invalid_descriptor", json_output=json_output)
        return 2
    if not isinstance(descriptor, dict):
        _emit_cli_error("invalid_descriptor", json_output=json_output)
        return 2
    try:
        workspace = _workspace(opts.workspace)
        catalog = InstalledCatalog()
        registry = NodeRegistry(catalog, provider=_provider())
        runtime = PipelineRuntime(Path(workspace), catalog=catalog, node_registry=registry)
    except AgentError as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    except CatalogError:
        if json_output:
            print(json.dumps({"status": "pending_manual", "code": "catalog_rejected", "receipt": None}, separators=(",", ":")))
        else:
            _emit_cli_error("catalog_rejected")
        return 1
    outcome = execute_descriptor(runtime, opts.pipeline_id, descriptor)
    print(outcome.model_dump_json())
    return 0 if outcome.status == "succeeded" else 1


def _provider_service() -> ProviderConfigService:
    root = os.environ.get("OPENCLAW_MEDIA_CONFIG_DIR")
    config_root = root if root else os.path.join(os.path.expanduser("~"), ".openclaw-media", "providers")
    return ProviderConfigService(
        ProviderConfigRepository(config_root), KeyringCredentialStore()
    )


def _projection_json(service: ProviderConfigService, config_id: str) -> str:
    return json.dumps(
        service.projection(config_id).model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _run_provider_command(arguments: list[str], *, json_output: bool = False) -> int:
    # Parse manually after the stable command shape so secrets never appear in
    # argparse-generated diagnostics or help output.
    action = arguments[2] if len(arguments) > 2 else ""
    if action not in {"create", "update", "rotate", "read", "delete"}:
        _emit_cli_error("invalid_provider_request", json_output=json_output)
        return 2
    provider_arguments = arguments[3:]
    if any(
        option == "--api-key" or option.startswith("--api-key=")
        for option in provider_arguments
    ):
        _emit_cli_error("provider_key_argv_forbidden", json_output=json_output)
        return 2
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("--id", dest="config_id")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--model-label")
    parser.add_argument("--local-endpoint", action="store_true")
    try:
        opts, unknown = parser.parse_known_args(provider_arguments)
        if unknown:
            _emit_cli_error("invalid_provider_request", json_output=json_output)
            return 2
        service = _provider_service()
        if action in {"create", "update"}:
            required = (opts.config_id, opts.base_url, opts.model, opts.model_label)
            if not all(isinstance(value, str) and value for value in required):
                _emit_cli_error("invalid_provider_request", json_output=json_output)
                return 2
            api_key = _read_provider_key()
            config = service.configure(
                config_id=opts.config_id, base_url=opts.base_url, model=opts.model,
                model_label=opts.model_label, api_key=api_key,
                local_endpoint_enabled=opts.local_endpoint,
            )
            print(_projection_json(service, config.config_id))
            return 0
        if not isinstance(opts.config_id, str) or not opts.config_id:
            _emit_cli_error("invalid_provider_request", json_output=json_output)
            return 2
        if action == "read":
            print(_projection_json(service, opts.config_id))
        elif action == "delete":
            service.delete(opts.config_id)
            print(json.dumps({"deleted": True}, separators=(",", ":")))
        elif action == "rotate":
            current = service.repository.load(opts.config_id)
            api_key = _read_provider_key()
            config = service.configure(
                config_id=current.config_id, base_url=current.base_url, model=current.model,
                model_label=current.model_label, api_key=api_key,
                provider_type=current.provider_type,
                local_endpoint_enabled=current.local_endpoint_enabled,
            )
            print(_projection_json(service, config.config_id))
        return 0
    except (
        argparse.ArgumentError,
        ProviderConfigError,
        CredentialStoreError,
        ValueError,
    ) as exc:
        _emit_cli_error(exc, json_output=json_output)
        return 2
    return parser


def main(
    argv: Sequence[str] | None = None, *, package_version: str | None = None
) -> int:
    """Run the installed CLI shell without exposing development-only commands."""

    try:
        resolved_version = package_version or _installed_version()
    except PackageNotFoundError:
        print(
            "openclaw-media: error: installed package metadata unavailable",
            file=sys.stderr,
        )
        return 2

    arguments = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in arguments
    if json_output:
        arguments = [argument for argument in arguments if argument != "--json"]
    if arguments[:1] == ["doctor"]:
        parser = build_parser(resolved_version)
        try:
            parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_doctor_command()
    if len(arguments) >= 3 and arguments[:2] == ["config", "provider"]:
        return _run_provider_command(arguments, json_output=json_output)
    if arguments[:1] == ["run"]:
        return _run_pipeline_command(arguments, json_output=json_output)
    if arguments[:1] == ["pair"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_pair_command(opts, json_output=json_output)
    if arguments[:1] == ["agent"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_agent_command(opts, json_output=json_output)
    if arguments[:1] == ["archive"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_archive_command(opts, json_output=json_output)
    if arguments[:1] == ["gc"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_gc_command(opts, json_output=json_output)
    if arguments[:1] == ["session"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_session_command(opts, json_output=json_output)
    if arguments[:1] == ["device"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_device_command(opts, json_output=json_output)
    if arguments[:1] == ["launchd"]:
        parser = build_parser(resolved_version)
        try:
            opts = parser.parse_args(arguments)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return _run_launchd_command(opts, json_output=json_output)
    parser = build_parser(resolved_version)
    if not arguments:
        parser.print_help()
        return 0
    parser.parse_args(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
