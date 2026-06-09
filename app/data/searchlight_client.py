"""SearchLight option discovery using the data exporter browser flow."""

from __future__ import annotations

import asyncio

BASE_URL = "https://searchlight.idex-hs.com"
CATEGORY_KEYS = ("fluorophores", "filters", "light_sources")


def fetch_searchlight_options(timeout: float = 30.0) -> tuple[dict[str, list[str]], str]:
    try:
        return asyncio.run(_fetch_with_exporter(timeout_ms=int(timeout * 1000)))
    except RuntimeError as exc:
        return {}, f"SearchLight unavailable; using local cache. ({exc})"
    except Exception as exc:
        return {}, f"SearchLight option discovery failed; using local cache. ({exc})"


async def _fetch_with_exporter(timeout_ms: int) -> tuple[dict[str, list[str]], str]:
    try:
        from playwright.async_api import (
            Error as ImportedPlaywrightError,
            TimeoutError as ImportedPlaywrightTimeoutError,
            async_playwright as imported_async_playwright,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("Playwright is not installed") from exc

    try:
        import data_exporter.data_exporter.exporter as exporter_module
        from data_exporter.data_exporter.exporter import BASE_URL as EXPORTER_BASE_URL
        from data_exporter.data_exporter.exporter import CATEGORIES, SearchLightExporter
    except ModuleNotFoundError:
        try:
            import data_exporter.exporter as exporter_module
            from data_exporter.exporter import BASE_URL as EXPORTER_BASE_URL
            from data_exporter.exporter import CATEGORIES, SearchLightExporter
        except ModuleNotFoundError as exc:
            raise RuntimeError("Data exporter package is not importable") from exc

    exporter_module.PlaywrightError = ImportedPlaywrightError
    exporter_module.PlaywrightTimeoutError = ImportedPlaywrightTimeoutError
    exporter_module.async_playwright = imported_async_playwright

    exporter = SearchLightExporter(headless=True, timeout_ms=timeout_ms)
    options: dict[str, list[str]] = {}

    async with imported_async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        await context.add_init_script(
            """
            (() => {
              const hideOneTrust = () => {
                for (const element of document.querySelectorAll('#onetrust-consent-sdk,.onetrust-pc-dark-filter')) {
                  element.remove();
                }
              };
              hideOneTrust();
              const startObserver = () => {
                if (document.documentElement) {
                  new MutationObserver(hideOneTrust).observe(document.documentElement, { childList: true, subtree: true });
                }
              };
              if (document.documentElement) startObserver();
              else document.addEventListener('DOMContentLoaded', startObserver, { once: true });
            })();
            """
        )
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            await page.goto(EXPORTER_BASE_URL or BASE_URL, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            await exporter.handle_cookie_consent(page)
            await exporter._wait_for_searchlight(page)
            for key in CATEGORY_KEYS:
                options[key] = await exporter.discover_items(page, CATEGORIES[key])
        finally:
            await context.close()
            await browser.close()

    options = {key: value for key, value in options.items() if value}
    if not options:
        raise RuntimeError("SearchLight did not return option names")
    return options, "Merged live SearchLight options with local CSV cache."
