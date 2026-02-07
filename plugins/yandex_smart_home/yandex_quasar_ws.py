"""Proxy to moved Quasar WebSocket client in clients package."""

from .clients.yandex_quasar_ws import YandexQuasarWS

__all__ = ["YandexQuasarWS"]
            external_id=device_id,
            state=state,
        )
        
        try:
            await self.runtime.event_bus.publish("external.device_state_reported", payload)
            await self._log(
                "debug",
                f"State update published successfully",
                external_id=device_id,
            )
        except Exception as e:
            await self._log(
                "error",
                f"Failed to publish state update: {e}",
                external_id=device_id,
                state=state,
            )
        
        # Вызываем подписчиков
        for cb in list(self._subscribers.get(device_id, [])):
            try:
                result = cb(payload)
                if inspect.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                continue

    def _cookie_jar_from(self, cookies: Optional[Dict[str, str]]) -> aiohttp.CookieJar:
        """Создает CookieJar с cookies для Quasar API.
        
        ВАЖНО: Cookies должны быть установлены для домена .yandex.ru
        чтобы работать с iot.quasar.yandex.ru
        """
        jar = aiohttp.CookieJar(unsafe=True)  # unsafe=True для cross-domain cookies
        if cookies:
            # Используем URL объект для правильной установки cookies
            base_url = URL("https://iot.quasar.yandex.ru")
            
            # Устанавливаем cookies используя SimpleCookie для правильного формата
            from http.cookies import SimpleCookie
            cookie_dict = SimpleCookie()
            for name, value in cookies.items():
                cookie_dict[name] = str(value)
                # Устанавливаем domain для работы со всеми поддоменами yandex.ru
                cookie_dict[name]["domain"] = ".yandex.ru"
                cookie_dict[name]["path"] = "/"
            
            # Обновляем jar с cookies
            jar.update_cookies(cookie_dict, response_url=base_url)
            
            # Также устанавливаем для yandex.ru напрямую (на всякий случай)
            yandex_url = URL("https://yandex.ru")
            jar.update_cookies(cookie_dict, response_url=yandex_url)
        
        return jar

    async def _load_cookies(self) -> Optional[Dict[str, str]]:
        """Получить cookies через capability yandex:session_cookies (фасад oauth_provider)."""
        cookies = await oauth_get_cookies(self.runtime)
        if cookies:
            await self._log("debug", "Loaded cookies via oauth_provider", cookie_count=len(cookies))
        return cookies

    async def _log(self, level: str, message: str, **context: Any) -> None:
        with contextlib.suppress(Exception):
            await self.runtime.service_registry.call(
                "logger.log",
                level=level,
                message=message,
                plugin=self.plugin_name,
                context=context or None,
            )
