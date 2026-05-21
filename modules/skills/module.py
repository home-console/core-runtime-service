"""SkillsModule — platform skill registry (plugin.json `skills` section)."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from core.http.models import EndpointAuthConfig, HttpEndpoint
from core.runtime.runtime_module import RuntimeModule
from modules.api.schemas import (
    ApiResponse,
    SkillDto,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillListDto,
)
from modules.skills.invoke_resolver import invoke_skill
from modules.skills.ingest import (
    load_manifest_for_plugin,
    rehydrate_registry_from_disk,
    skills_from_manifest,
)
from modules.skills.persist import (
    delete_plugin_skills,
    hydrate_registry_from_storage,
    persist_plugin_skills,
    reconcile_registry_with_disk,
    snapshot_registry_to_storage,
)
from modules.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_PLUGIN_LOADED = "internal.plugin.loaded"
_PLUGIN_UNLOADED = "internal.plugin.unloaded"


def _convention_invoke_service(plugin_name: str, skill_name: str) -> str:
    return f"{plugin_name}.skill.{skill_name}"


def _resolve_invoke_service(record) -> str:
    if record.service:
        return record.service.strip()
    return _convention_invoke_service(record.plugin_name, record.name)


class SkillsModule(RuntimeModule):
    """
    Registry for skills declared in plugin manifests.

    Not related to modules/agent (remote agent control plane).
    """

    def __init__(self, runtime: Any):
        super().__init__(runtime)
        self.registry = SkillRegistry()
        self._loaded_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._unloaded_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None

    @property
    def name(self) -> str:
        return "skills"

    async def register(self) -> None:
        setattr(self.runtime, "skills_registry", self.registry)

        async def _on_loaded(payload: Dict[str, Any]) -> None:
            plugin_name = str(payload.get("plugin_name") or "").strip()
            if not plugin_name:
                return
            version = str(payload.get("plugin_version") or "0.0.0")
            skills = payload.get("skills")
            if not isinstance(skills, list):
                manifest = load_manifest_for_plugin(self.runtime, plugin_name)
                skills = skills_from_manifest(manifest)
            self.registry.register_plugin_skills(plugin_name, version, skills)
            await persist_plugin_skills(self.runtime, plugin_name, version, skills)
            logger.debug("skills: registered %s for plugin %s", len(skills), plugin_name)

        async def _on_unloaded(payload: Dict[str, Any]) -> None:
            plugin_name = str(payload.get("plugin_name") or "").strip()
            if not plugin_name:
                return
            removed = self.registry.unregister_plugin(plugin_name)
            await delete_plugin_skills(self.runtime, plugin_name)
            logger.debug("skills: unregistered %s skills for plugin %s", removed, plugin_name)

        self._loaded_handler = _on_loaded
        self._unloaded_handler = _on_unloaded

        bus = getattr(self.runtime, "event_bus", None)
        if bus is not None:
            await bus.subscribe(_PLUGIN_LOADED, _on_loaded)
            await bus.subscribe(_PLUGIN_UNLOADED, _on_unloaded)

        await self.context.services.register("skills.list", self._service_list)
        await self.context.services.register("skills.get", self._service_get)
        await self.context.services.register("skills.invoke", self._service_invoke)

        auth = EndpointAuthConfig(required_scopes=["admin.read"])
        auth_write = EndpointAuthConfig(required_scopes=["admin.write"])
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/skills",
                service="skills.list",
                auth_config=auth,
                tags=["Skills"],
                response_model=ApiResponse[SkillListDto],
            )
        )
        self.context.http.register(
            HttpEndpoint(
                method="GET",
                path="/api/v1/skills/{skill_id}",
                service="skills.get",
                auth_config=auth,
                tags=["Skills"],
                response_model=ApiResponse[SkillDto],
            )
        )
        self.context.http.register(
            HttpEndpoint(
                method="POST",
                path="/api/v1/skills/{skill_id}/invoke",
                service="skills.invoke",
                auth_config=auth_write,
                tags=["Skills"],
                response_model=ApiResponse[SkillInvokeResult],
            )
        )

    async def start(self) -> None:
        try:
            from_storage = await hydrate_registry_from_storage(self.registry, self.runtime)
            if from_storage == 0:
                disk_count = await rehydrate_registry_from_disk(self.registry, self.runtime)
                if disk_count > 0:
                    await snapshot_registry_to_storage(self.registry, self.runtime)
            else:
                await reconcile_registry_with_disk(self.registry, self.runtime)
        except Exception:
            logger.warning("skills.start: registry bootstrap failed", exc_info=True)

    async def stop(self) -> None:
        bus = getattr(self.runtime, "event_bus", None)
        if bus is not None:
            if self._loaded_handler is not None:
                try:
                    await bus.unsubscribe(_PLUGIN_LOADED, self._loaded_handler)
                except Exception:
                    logger.debug("skills.stop: unsubscribe loaded failed", exc_info=True)
            if self._unloaded_handler is not None:
                try:
                    await bus.unsubscribe(_PLUGIN_UNLOADED, self._unloaded_handler)
                except Exception:
                    logger.debug("skills.stop: unsubscribe unloaded failed", exc_info=True)
        for svc in ("skills.list", "skills.get", "skills.invoke"):
            try:
                await self.context.services.unregister(svc)
            except Exception:
                logger.warning("skills.stop: service unregister failed", exc_info=True)
        try:
            self.context.http.clear(self.name)
        except Exception:
            logger.warning("skills.stop: http clear failed", exc_info=True)
        if hasattr(self.runtime, "skills_registry"):
            delattr(self.runtime, "skills_registry")

    async def _service_list(self, plugin: Optional[str] = None, **_: Any) -> dict[str, Any]:
        records = self.registry.list_skills(
            plugin_name=str(plugin).strip() if plugin else None
        )
        items = [SkillDto(**r.to_dict()) for r in records]
        return SkillListDto(items=items, total=len(items)).model_dump()

    async def _service_get(self, skill_id: str, **_: Any) -> dict[str, Any]:
        sid = str(skill_id or "").strip()
        record = self.registry.get(sid)
        if record is None:
            raise ValueError(f"Skill not found: {sid}")
        return SkillDto(**record.to_dict()).model_dump()

    async def _service_invoke(
        self,
        skill_id: str,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
        **_: Any,
    ) -> dict[str, Any]:
        sid = str(skill_id or "").strip()
        record = self.registry.get(sid)
        if record is None:
            raise ValueError(f"Skill not found: {sid}")

        call_params: Dict[str, Any] = dict(params or {})
        if not call_params and body is not None:
            if isinstance(body, dict):
                if "params" in body and isinstance(body.get("params"), dict):
                    call_params = dict(body["params"])
                else:
                    call_params = dict(body)
            elif hasattr(body, "model_dump"):
                dumped = body.model_dump()
                if isinstance(dumped.get("params"), dict):
                    call_params = dict(dumped["params"])

        service_name = _resolve_invoke_service(record)
        ok, payload, svc, code = await invoke_skill(
            self.runtime, record, service_name, call_params
        )
        if ok:
            return SkillInvokeResult(
                ok=True,
                skill_id=sid,
                service=svc,
                result=payload,
            ).model_dump()
        return SkillInvokeResult(
            ok=False,
            skill_id=sid,
            service=svc,
            error=str(payload),
            code=code or "invoke_not_configured",
        ).model_dump()
