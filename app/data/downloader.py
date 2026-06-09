"""Data downloads for GUI-selected configurations."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.data.catalog import default_data_root

DEFAULT_SOURCE = "searchlight"


def download_single_item(download_root: Path, category_key: str, item_name: str) -> Path:
    return asyncio.run(_download_single_item(download_root, category_key, item_name))


def download_filter_configuration(download_root: Path, filter_name: str, aoi: int | None) -> Path:
    return asyncio.run(_download_filter_configuration(download_root, filter_name, aoi))


async def _download_single_item(download_root: Path, category_key: str, item_name: str) -> Path:
    download_root = _target_download_root()
    resources = _load_exporter_resources()
    exporter_module, playwright_api, base_url, categories, exporter_cls, safe_filename = resources
    imported_async_playwright = playwright_api[2]
    category = categories[category_key]
    output_dir = download_root / category_key
    output_dir.mkdir(parents=True, exist_ok=True)
    category = type(category)(category.key, category.label, category.singular, output_dir)
    exporter = exporter_cls(headless=True, timeout_ms=30_000, retries=1, skip_existing=False)
    output_path = output_dir / f"{DEFAULT_SOURCE}_{category.singular}_{safe_filename(item_name)}.csv"

    async with imported_async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        await context.add_init_script(_cookie_hiding_script())
        page = await context.new_page()
        page.set_default_timeout(30_000)
        try:
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=30_000)
            await exporter.handle_cookie_consent(page)
            await exporter._wait_for_searchlight(page)
            await exporter.clear_plot(page)
            await exporter.select_item(page, category, item_name)
            await exporter.wait_for_plot_update(page)
            await exporter.export_csv(page, output_path, item_name)
            return output_path
        finally:
            await context.close()
            await browser.close()


async def _download_filter_configuration(download_root: Path, filter_name: str, aoi: int | None) -> Path:
    download_root = _target_download_root()
    _, playwright_api, base_url, _, category_cls, exporter_cls, safe_filename = _load_exporter_resources(filter_mode=True)
    imported_async_playwright = playwright_api[2]

    output_dir = download_root / "filters"
    output_dir.mkdir(parents=True, exist_ok=True)
    exporter = exporter_cls(headless=True, timeout_ms=30_000, retries=1, skip_existing=False)
    category = category_cls("filters", "Filters", "filter", output_dir)

    async with imported_async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        await context.add_init_script(_cookie_hiding_script())
        page = await context.new_page()
        page.set_default_timeout(30_000)
        try:
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=30_000)
            await exporter.handle_cookie_consent(page)
            await exporter._wait_for_searchlight(page)

            selected_name = await _select_filter_with_name_variants(exporter, page, category, filter_name)
            if aoi is None:
                output_path = output_dir / f"{DEFAULT_SOURCE}_filter_{safe_filename(selected_name)}_AOI_default.csv"
                legend_item_id = None
            else:
                output_path = output_dir / f"{DEFAULT_SOURCE}_filter_{safe_filename(selected_name)}_AOI_{aoi:02d}deg.csv"
                legend_item_id = await exporter.set_aoi(page, aoi)
                await exporter.wait_for_plot_update(page)
            await exporter.export_csv(page, output_path, selected_name, legend_item_id=legend_item_id)
            return output_path
        finally:
            await context.close()
            await browser.close()


def _load_exporter_resources(filter_mode: bool = False):
    try:
        from playwright.async_api import (
            Error as ImportedPlaywrightError,
            TimeoutError as ImportedPlaywrightTimeoutError,
            async_playwright as imported_async_playwright,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("Playwright is not installed. Run `pip install -r requirements.txt`.") from exc

    try:
        import data_exporter.data_exporter.exporter as exporter_module
        from data_exporter.data_exporter.exporter import BASE_URL, CATEGORIES, Category, SearchLightExporter
        from data_exporter.data_exporter.utils import safe_filename
    except ModuleNotFoundError:
        try:
            import data_exporter.exporter as exporter_module
            from data_exporter.exporter import BASE_URL, CATEGORIES, Category, SearchLightExporter
            from data_exporter.utils import safe_filename
        except ModuleNotFoundError as exc:
            raise RuntimeError("Data exporter package is not importable.") from exc

    exporter_module.PlaywrightError = ImportedPlaywrightError
    exporter_module.PlaywrightTimeoutError = ImportedPlaywrightTimeoutError
    exporter_module.async_playwright = imported_async_playwright

    playwright_api = (ImportedPlaywrightError, ImportedPlaywrightTimeoutError, imported_async_playwright)
    if filter_mode:
        return exporter_module, playwright_api, BASE_URL, CATEGORIES, Category, SearchLightExporter, safe_filename
    return exporter_module, playwright_api, BASE_URL, CATEGORIES, SearchLightExporter, safe_filename


async def _select_filter_with_name_variants(exporter, page, category, filter_name: str) -> str:
    errors: list[str] = []
    for candidate in _filter_name_candidates(filter_name):
        try:
            await exporter.clear_plot(page)
            await exporter.select_item(page, category, candidate)
            await exporter.wait_for_plot_update(page)
            return candidate
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError("Could not find filter on SearchLight. Tried " + "; ".join(errors))


def _filter_name_candidates(filter_name: str) -> list[str]:
    candidates = [filter_name]
    if " " in filter_name:
        candidates.append(filter_name.replace(" ", "/"))
        candidates.append(filter_name.replace(" ", "_"))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate.strip()))


def _target_download_root() -> Path:
    root = default_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cookie_hiding_script() -> str:
    return """
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
