"""Command-line data exporter for spectral CSV sources."""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

if TYPE_CHECKING:
    from playwright.async_api import Download, Page

PlaywrightError = Exception
PlaywrightTimeoutError = TimeoutError
async_playwright = None

from .utils import (
    calculate_aoi_values,
    ensure_directories,
    infer_standard_filter_aoi,
    looks_like_csv,
    safe_filename,
    searchlight_payload_to_csv,
    sanitize_csv_headers,
)

BASE_URL = "https://searchlight.idex-hs.com"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    singular: str
    output_dir: Path


@dataclass
class ExportRecord:
    category: str
    item_name: str
    output_path: str | None
    status: str
    aoi: int | None = None
    default_aoi: int | None = None
    message: str = ""


CATEGORIES = {
    "fluorophores": Category(
        key="fluorophores",
        label="Fluorophores",
        singular="fluorophore",
        output_dir=DATA_ROOT / "fluorophores",
    ),
    "filters": Category(
        key="filters",
        label="Filters",
        singular="filter",
        output_dir=DATA_ROOT / "filters",
    ),
    "light_sources": Category(
        key="light_sources",
        label="Light Sources",
        singular="light_source",
        output_dir=DATA_ROOT / "light_sources",
    ),
}

IGNORED_ITEM_NAMES = {"loading...", ""}


class SearchLightExporter:

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30_000,
        retries: int = 2,
        sweep_degrees: int = 30,
        sweep_step: int = 1,
        limit: int | None = None,
        skip_existing: bool = True,
        source: str = "searchlight",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.sweep_degrees = sweep_degrees
        self.sweep_step = sweep_step
        self.limit = limit
        self.skip_existing = skip_existing
        self.source = safe_filename(source.lower()) or "source"
        self.records: list[ExportRecord] = []

    async def run(self, categories: Sequence[Category]) -> list[ExportRecord]:
        global PlaywrightError, PlaywrightTimeoutError, async_playwright
        try:
            from playwright.async_api import (
                Error as ImportedPlaywrightError,
                TimeoutError as ImportedPlaywrightTimeoutError,
                async_playwright as imported_async_playwright,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install -r requirements.txt` "
                "and `python -m playwright install chromium` first."
            ) from exc

        PlaywrightError = ImportedPlaywrightError
        PlaywrightTimeoutError = ImportedPlaywrightTimeoutError
        async_playwright = imported_async_playwright

        ensure_directories([category.output_dir for category in CATEGORIES.values()])

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
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
            page.set_default_timeout(self.timeout_ms)
            await page.goto(BASE_URL, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            await self.handle_cookie_consent(page)
            await self._wait_for_searchlight(page)

            for category in categories:
                await self.export_category(page, category)

            await context.close()
            await browser.close()

        return self.records

    async def export_category(self, page: Page, category: Category) -> None:
        items = await self.discover_items(page, category)
        if self.limit is not None:
            items = items[: self.limit]
        print(f"Discovered {len(items)} {category.label}", flush=True)

        for index, item_name in enumerate(items, start=1):
            print(f"[{index}/{len(items)}] Exporting {category.label}: {item_name}", flush=True)
            if category.key == "filters":
                await self.export_filter(page, category, item_name)
            else:
                await self.export_single_item(page, category, item_name)

    async def discover_items(self, page: Page, category: Category) -> list[str]:
        await self._open_category(page, category)

        # The rendered page exposes the category lists as numbered text. Prefer
        # this over DOM ancestor guessing, because generated app containers can
        # wrap multiple SearchLight categories and lead to massive overcounts.
        body_text = await page.locator("body").inner_text()
        static_items = self._extract_static_category_list(body_text, category.label)
        if static_items:
            return static_items

        names = await page.evaluate(
            """
            (label) => {
              const headings = [...document.querySelectorAll('h1,h2,h3,h4,summary,button,[role=tab],legend')];
              const heading = headings.find((el) => (el.innerText || '').trim().toLowerCase() === label.toLowerCase());
              if (!heading) return [];
              const root = heading.closest('section,fieldset,div') || heading.parentElement || document.body;
              const candidates = [
                ...root.querySelectorAll('option'),
                ...root.querySelectorAll('[role=option]'),
                ...root.querySelectorAll('li'),
                ...root.querySelectorAll('label'),
                ...root.querySelectorAll('button')
              ];
              return [...new Set(candidates.map((el) => (el.innerText || el.textContent || '').trim()).filter(Boolean))]
                .filter((text) => !['Open','Save','Save As','Share','Export','Print'].includes(text));
            }
            """,
            category.label,
        )
        cleaned = [self._strip_list_prefix(name) for name in names]
        cleaned = [
            name
            for name in cleaned
            if name and name.lower() != category.label.lower() and name.lower() not in IGNORED_ITEM_NAMES
        ]

        if cleaned:
            return list(dict.fromkeys(cleaned))

        return []

    async def export_single_item(self, page: Page, category: Category, item_name: str) -> None:
        output_path = self._single_item_output_path(category, item_name)
        if self.skip_existing and output_path.exists():
            print(f"Skipping existing {category.singular}: {output_path}", flush=True)
            self.records.append(
                ExportRecord(
                    category=category.key,
                    item_name=item_name,
                    output_path=str(output_path),
                    status="skipped",
                    message="file already exists",
                )
            )
            return

        record = ExportRecord(category=category.key, item_name=item_name, output_path=None, status="failed")
        try:
            await self._with_retries(lambda: self._export_single_item_once(page, category, item_name, output_path, record))
        except Exception as exc:
            record.message = str(exc)
            print(f"Failed {category.singular}: {item_name} ({exc})", flush=True)
        finally:
            self.records.append(record)

    async def _export_single_item_once(
        self,
        page: Page,
        category: Category,
        item_name: str,
        output_path: Path,
        record: ExportRecord,
    ) -> None:
        await self.clear_plot(page)
        await self.select_item(page, category, item_name)
        await self.wait_for_plot_update(page)

        await self.export_csv(page, output_path, item_name)
        record.status = "success"
        record.output_path = str(output_path)
        record.message = "exported"
        print(f"Saved {category.singular}: {output_path}", flush=True)

    async def export_filter(self, page: Page, category: Category, item_name: str) -> None:
        default_aoi = self._infer_default_aoi_from_name(item_name)
        if default_aoi is not None and self._filter_outputs_exist(category, item_name, default_aoi):
            expected_files = self._filter_expected_paths(category, item_name, default_aoi)
            print(f"Skipping existing complete filter: {item_name}", flush=True)
            for output_path in expected_files:
                self.records.append(
                    ExportRecord(
                        category=category.key,
                        item_name=item_name,
                        output_path=str(output_path),
                        status="skipped",
                        aoi=self._aoi_from_filter_output_path(output_path),
                        default_aoi=default_aoi,
                        message="file already exists",
                    )
                )
            return

        default_record = ExportRecord(
            category=category.key,
            item_name=item_name,
            output_path=None,
            status="failed",
        )
        try:
            await self._with_retries(lambda: self._prepare_filter(page, category, item_name))
            if default_aoi is None:
                default_aoi = await self.read_default_aoi(page, item_name)
            default_record.default_aoi = default_aoi
            default_record.aoi = default_aoi
            default_path = category.output_dir / f"{self.source}_filter_{safe_filename(item_name)}_AOI_default.csv"
            default_record.output_path = str(default_path)
            aoi_values = calculate_aoi_values(default_aoi, self.sweep_degrees, self.sweep_step)
            print(
                f"Filter {item_name}: default AOI {default_aoi}; "
                f"exporting {len(aoi_values)} AOI value(s) from {aoi_values[0]} to {aoi_values[-1]}",
                flush=True,
            )
            if self.skip_existing and default_path.exists():
                print(f"Skipping existing default AOI: {default_path}", flush=True)
                default_record.status = "skipped"
                default_record.message = "file already exists"
            else:
                await self.export_csv(page, default_path, item_name)
                default_record.status = "success"
                default_record.message = "exported default AOI"
                print(f"Saved default AOI: {default_path}", flush=True)
        except Exception as exc:
            default_record.message = str(exc)
            print(f"Failed default AOI for filter {item_name}: {exc}", flush=True)
        finally:
            self.records.append(default_record)

        if default_aoi is None:
            return

        for aoi in calculate_aoi_values(default_aoi, self.sweep_degrees, self.sweep_step):
            record = ExportRecord(
                category=category.key,
                item_name=item_name,
                output_path=None,
                status="failed",
                aoi=aoi,
                default_aoi=default_aoi,
            )
            output_path = self._filter_aoi_output_path(category, item_name, aoi)
            record.output_path = str(output_path)
            if self.skip_existing and output_path.exists():
                print(f"Skipping existing AOI {aoi}: {output_path}", flush=True)
                record.status = "skipped"
                record.message = "file already exists"
                self.records.append(record)
                continue

            try:
                await self._with_retries(
                    lambda aoi=aoi, output_path=output_path: self._export_filter_aoi_once(
                        page,
                        category,
                        item_name,
                        aoi,
                        output_path,
                        record,
                    )
                )
            except Exception as exc:
                record.message = str(exc)
                print(f"Failed AOI {aoi} for filter {item_name}: {exc}", flush=True)
            finally:
                self.records.append(record)

    async def _prepare_filter(self, page: Page, category: Category, item_name: str) -> None:
        await self.clear_plot(page)
        await self.select_item(page, category, item_name)
        await self.wait_for_plot_update(page)

    async def _export_filter_aoi_once(
        self,
        page: Page,
        category: Category,
        item_name: str,
        aoi: int,
        output_path: Path,
        record: ExportRecord,
    ) -> None:
        await self.clear_plot(page)
        await self.select_item(page, category, item_name)
        legend_item_id = await self.set_aoi(page, aoi)
        await self.wait_for_plot_update(page)

        await self.export_csv(page, output_path, item_name, legend_item_id=legend_item_id)
        record.status = "success"
        record.output_path = str(output_path)
        record.message = "exported AOI"
        print(f"Saved AOI {aoi}: {output_path}", flush=True)

    async def clear_plot(self, page: Page) -> None:
        await self.handle_cookie_consent(page)
        if not await self._legend_has_items(page):
            return

        if await self._clear_plot_with_legend_menu(page):
            return

    async def select_item(self, page: Page, category: Category, item_name: str) -> None:
        await self.handle_cookie_consent(page)
        await self._open_category(page, category)
        await self._wait_for_category_rows(page, category)

        if await self._select_item_with_visible_controls(page, item_name):
            await self._wait_for_legend_item(page, item_name)
            return

        if await self._select_item_with_dom(page, item_name):
            await self._wait_for_legend_item(page, item_name)
            return

        raise RuntimeError(f"Could not select and add {category.singular} to plot: {item_name}")

    async def _select_item_with_dom(self, page: Page, item_name: str) -> bool:
        row_clicked = await page.evaluate(
            """
            (itemName) => {
              const items = [...document.querySelectorAll('#selector li')];
              const item = items.find((candidate) => {
                const row = candidate.querySelector('.selector-item-row');
                const text = (row?.innerText || row?.textContent || '').trim().split('\\n')[0];
                return candidate.title === itemName || candidate.dataset.kw === itemName || row?.title === itemName || text === itemName;
              });
              if (!item) return false;
              const row = item.querySelector('.selector-item-row') || item;
              row.scrollIntoView({ block: 'center' });
              row.click();
              return true;
            }
            """,
            item_name,
        )
        if not row_clicked:
            return False

        try:
            await page.wait_for_function(
                """
                (itemName) => {
                  const legendHasItem = [...document.querySelectorAll('#legend .sl-composite, #legend .sl-component')]
                    .some((el) => ((el.innerText || el.textContent || el.title || '').includes(itemName)));
                  if (legendHasItem) return true;
                  const selected = document.querySelector('#selector .selector-item.ui-selected');
                  return !!(
                    selected?.querySelector('.big-play-button') ||
                    selected?.querySelector('.plot-button[title="Add to plot"]') ||
                    selected?.querySelector('.plot-button[title="Add to Plot"]') ||
                    selected?.querySelector('.ui-icon-play')
                  );
                }
                """,
                arg=item_name,
                timeout=min(self.timeout_ms, 5_000),
            )
        except PlaywrightTimeoutError:
            return False

        return await page.evaluate(
            """
            () => {
              const selected = document.querySelector('#selector .selector-item.ui-selected');
              const addButton =
                selected?.querySelector('.big-play-button') ||
                selected?.querySelector('.plot-button[title="Add to plot"]') ||
                selected?.querySelector('.plot-button[title="Add to Plot"]') ||
                selected?.querySelector('.ui-icon-play');
              if (!addButton) return false;
              addButton.click();
              return true;
            }
            """,
        )

    async def _select_item_with_visible_controls(self, page: Page, item_name: str) -> bool:
        row = page.locator("#selector .selector-item-row", has_text=item_name).first
        if not await row.count():
            return False

        await row.scroll_into_view_if_needed()
        await row.click(force=True)

        try:
            await page.locator("#selector .selector-item.ui-selected .big-play-button, #selector .selector-item.ui-selected .plot-button[title='Add to plot']").first.wait_for(
                state="visible",
                timeout=5_000,
            )
        except PlaywrightError:
            return False

        controls = [
            page.locator("#selector .selector-item.ui-selected .big-play-button").first,
            page.locator("#selector .selector-item.ui-selected .plot-button[title='Add to plot']").first,
        ]
        for control in controls:
            if await control.count():
                try:
                    await control.click(force=True, timeout=3_000)
                    return True
                except PlaywrightError:
                    continue
        return False

    async def export_csv(
        self,
        page: Page,
        output_path: Path,
        item_name: str,
        legend_item_id: str | None = None,
    ) -> None:
        await self.handle_cookie_consent(page)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            async with page.expect_download(timeout=self.timeout_ms) as download_info:
                await self._click_download(page, item_name, legend_item_id=legend_item_id)
            download = await download_info.value
            await self._save_download(download, output_path)
            return
        except PlaywrightTimeoutError:
            pass

        csv_response = await self._capture_csv_response(page, item_name, legend_item_id=legend_item_id)
        if csv_response:
            output_path.write_text(sanitize_csv_headers(csv_response), encoding="utf-8")
            return

        raise RuntimeError("CSV export did not produce a browser download or CSV response")

    async def read_default_aoi(self, page: Page, item_name: str | None = None) -> int:
        if item_name:
            inferred_aoi = infer_standard_filter_aoi(item_name)
            if inferred_aoi is not None:
                return inferred_aoi

        if await page.locator("#legend .sl-composite, #legend .sl-component").count():
            try:
                await self._open_filter_model_dialog(page)
                aoi_input = page.locator("#txtModelFilterAOI").first
                raw = await aoi_input.input_value()
                placeholder = await aoi_input.get_attribute("placeholder")
                await self._close_dialog(page, "modelFilterDialog")
                return self._parse_aoi(raw or placeholder or "0")
            except Exception:
                pass

        candidates = [
            "input[name*='aoi' i]",
            "input[id*='aoi' i]",
            "input[aria-label*='angle' i]",
            "input[aria-label*='AOI' i]",
        ]
        for selector in candidates:
            locator = page.locator(selector).first
            if await locator.count():
                raw = await locator.input_value()
                return self._parse_aoi(raw)

        body_text = await page.locator("body").inner_text()
        match = re.search(r"(?:AOI|Angle of Incidence)\D+(\d+(?:\.\d+)?)", body_text, re.IGNORECASE)
        if match:
            return int(round(float(match.group(1))))

        return 0

    async def set_aoi(self, page: Page, aoi: int) -> str | None:
        if aoi < 0:
            raise ValueError("AOI cannot be negative")

        if await page.locator("#legend .sl-composite, #legend .sl-component").count():
            before_ids = await self._legend_item_ids(page)
            original_id = before_ids[0] if before_ids else None
            await self._open_filter_model_dialog(page)
            aoi_input = page.locator("#txtModelFilterAOI").first
            await aoi_input.fill(str(aoi))
            cha_input = page.locator("#txtModelFilterCHA").first
            if await cha_input.count() and not await cha_input.input_value():
                await cha_input.fill("0")
            await page.locator("#btnModelFilterGenerate").click()
            await page.locator(".ui-dialog:has(#modelFilterDialog) .ui-dialog-buttonpane button", has_text="OK").wait_for(
                state="visible",
                timeout=self.timeout_ms,
            )
            ok_button = page.locator(".ui-dialog:has(#modelFilterDialog) .ui-dialog-buttonpane button", has_text="OK").first
            await page.wait_for_function(
                """
                () => {
                  const dialog = document.querySelector('.ui-dialog:has(#modelFilterDialog)');
                  const ok = [...(dialog?.querySelectorAll('.ui-dialog-buttonpane button') || [])]
                    .find((button) => (button.innerText || '').trim() === 'OK');
                  return !!ok && !ok.disabled && !ok.classList.contains('ui-button-disabled');
                }
                """,
                timeout=self.timeout_ms,
            )
            await ok_button.click()
            await page.locator("#modelFilterDialog").wait_for(state="hidden", timeout=self.timeout_ms)
            return await self._resolve_modeled_filter_legend_id(page, before_ids, original_id)

        selectors = [
            "input[name*='aoi' i]",
            "input[id*='aoi' i]",
            "input[aria-label*='angle' i]",
            "input[aria-label*='AOI' i]",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count():
                await locator.fill(str(aoi))
                await locator.press("Enter")
                return None

        label = page.get_by_text(re.compile(r"AOI|Angle of Incidence", re.IGNORECASE)).first
        if await label.count():
            parent = label.locator("xpath=ancestor::*[self::div or self::fieldset][1]")
            input_locator = parent.locator("input").first
            if await input_locator.count():
                await input_locator.fill(str(aoi))
                await input_locator.press("Enter")
                return None

        raise RuntimeError("Could not find AOI input")

    async def _open_filter_model_dialog(self, page: Page) -> None:
        if await page.locator("#modelFilterDialog").is_visible():
            return

        legend_item = page.locator("#legend .sl-composite, #legend .sl-component").first
        if not await legend_item.count():
            raise RuntimeError("Could not find plotted filter in legend")

        menu_icon = legend_item.locator(":scope > .control-icons .control-icon[title='More...']").first
        if not await menu_icon.count():
            menu_icon = legend_item.locator(".control-icon[title='More...']").first
        if not await menu_icon.count():
            raise RuntimeError("Could not find filter legend menu")

        await menu_icon.click()
        model_item = page.locator("#legendMenuModel").first
        await model_item.wait_for(state="visible", timeout=self.timeout_ms)
        await model_item.click()
        await page.locator("#txtModelFilterAOI").wait_for(state="visible", timeout=self.timeout_ms)

    async def _close_dialog(self, page: Page, dialog_id: str) -> None:
        dialog = page.locator(f".ui-dialog:has(#{dialog_id})").first
        if not await dialog.count():
            return
        close_button = dialog.locator(".ui-dialog-titlebar-close").first
        if await close_button.count():
            await close_button.click()
            await page.locator(f"#{dialog_id}").wait_for(state="hidden", timeout=self.timeout_ms)

    async def wait_for_plot_update(self, page: Page) -> None:
        await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        legend_component = page.locator("#legend .sl-component, #legend .sl-composite").first
        if await legend_component.count():
            await legend_component.wait_for(state="visible", timeout=self.timeout_ms)
            return
        for selector in ("canvas", "svg", "[class*='plot' i]", "[id*='plot' i]"):
            locator = page.locator(selector).first
            if await locator.count():
                await locator.wait_for(state="visible", timeout=self.timeout_ms)
                return

    async def _click_download(self, page: Page, item_name: str, legend_item_id: str | None = None) -> None:
        await self.handle_cookie_consent(page)
        legend_item_id = legend_item_id or await self._find_legend_item_id(page, item_name)
        if not legend_item_id:
            raise RuntimeError(f"Could not find plotted legend item for download: {item_name}")
        legend_item = page.locator(f"#{legend_item_id}")

        menu_icon = legend_item.locator(":scope > .control-icons .control-icon[title='More...']").first
        if not await menu_icon.count():
            menu_icon = legend_item.locator(".control-icon[title='More...']").first
        if not await menu_icon.count():
            raise RuntimeError(f"Could not find legend download menu for: {item_name}")

        await menu_icon.click()
        download_item = page.locator("#legendMenuDownload").first
        await download_item.wait_for(state="visible", timeout=self.timeout_ms)
        await download_item.click()

    async def _first_visible(self, locator):
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except PlaywrightError:
                continue
        return None

    async def _click_exact_text(self, page: Page, texts: Iterable[str], *, timeout: int = 3_000) -> bool:
        for text in texts:
            locator = await self._first_visible(page.get_by_text(text, exact=True))
            if locator:
                try:
                    await locator.click(timeout=timeout)
                    return True
                except PlaywrightError:
                    continue
        return False

    async def _capture_csv_response(self, page: Page, item_name: str, legend_item_id: str | None = None) -> str | None:
        csv_payload: str | None = None

        async def handle_response(response) -> None:
            nonlocal csv_payload
            if csv_payload is not None:
                return
            url = response.url.lower()
            content_type = (response.headers.get("content-type") or "").lower()
            if "csv" not in url and "csv" not in content_type:
                return
            try:
                text = await response.text()
            except PlaywrightError:
                return
            if looks_like_csv(text):
                csv_payload = text

        page.on("response", handle_response)
        try:
            await self._click_download(page, item_name, legend_item_id=legend_item_id)
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        finally:
            page.remove_listener("response", handle_response)
        return csv_payload

    async def _save_download(self, download: Download, output_path: Path) -> None:
        download_path = await download.path()
        if download_path is None:
            raise RuntimeError("Playwright did not provide a path for the downloaded file")
        payload = Path(download_path).read_bytes()
        csv_text = searchlight_payload_to_csv(payload, download.suggested_filename)
        output_path.write_text(sanitize_csv_headers(csv_text), encoding="utf-8", newline="")
        if output_path.stat().st_size == 0:
            raise RuntimeError(f"Converted CSV file is empty: {output_path}")

    def _single_item_output_path(self, category: Category, item_name: str) -> Path:
        return category.output_dir / f"{self.source}_{category.singular}_{safe_filename(item_name)}.csv"

    def _filter_aoi_output_path(self, category: Category, item_name: str, aoi: int) -> Path:
        return category.output_dir / f"{self.source}_filter_{safe_filename(item_name)}_AOI_{aoi:02d}deg.csv"

    def _filter_expected_paths(self, category: Category, item_name: str, default_aoi: int) -> list[Path]:
        default_path = category.output_dir / f"{self.source}_filter_{safe_filename(item_name)}_AOI_default.csv"
        aoi_paths = [
            self._filter_aoi_output_path(category, item_name, aoi)
            for aoi in calculate_aoi_values(default_aoi, self.sweep_degrees, self.sweep_step)
        ]
        return [default_path, *aoi_paths]

    def _filter_outputs_exist(self, category: Category, item_name: str, default_aoi: int) -> bool:
        if not self.skip_existing:
            return False
        return all(path.exists() for path in self._filter_expected_paths(category, item_name, default_aoi))

    @staticmethod
    def _infer_default_aoi_from_name(item_name: str) -> int | None:
        return infer_standard_filter_aoi(item_name)

    @staticmethod
    def _aoi_from_filter_output_path(output_path: Path) -> int | None:
        if output_path.name.endswith("_AOI_default.csv"):
            return None
        match = re.search(r"_AOI_(\d+)deg\.csv$", output_path.name)
        if not match:
            return None
        return int(match.group(1))

    async def _legend_has_items(self, page: Page) -> bool:
        return await page.evaluate(
            """
            () => !!document.querySelector('#legend .sl-composite, #legend .sl-component')
            """
        )

    async def _clear_plot_with_legend_menu(self, page: Page) -> bool:
        menu_icon = page.locator("#legendHeader .control-icon[title='Advanced...'], #legendHeader .control-icon[title='More...']").first
        if not await menu_icon.count():
            menu_icon = page.locator("#legend .control-icon[title='Advanced...'], #legend .control-icon[title='More...']").first
        if not await menu_icon.count():
            return False

        try:
            await menu_icon.click()
            remove_all = page.locator("#legendMenuRemoveAll").first
            await remove_all.wait_for(state="visible", timeout=3_000)
            await remove_all.click()
            await page.wait_for_function(
                """
                () => !document.querySelector('#legend .sl-composite, #legend .sl-component')
                """,
                timeout=5_000,
            )
            return True
        except PlaywrightError:
            return False

    async def handle_cookie_consent(self, page: Page) -> None:
        button_patterns = (
            re.compile(r"accept all", re.IGNORECASE),
            re.compile(r"allow all", re.IGNORECASE),
            re.compile(r"accept cookies", re.IGNORECASE),
            re.compile(r"close", re.IGNORECASE),
        )
        for pattern in button_patterns:
            locator = page.get_by_role("button", name=pattern).first
            if await locator.count():
                try:
                    await locator.click(timeout=2_000)
                    await page.wait_for_load_state("networkidle", timeout=5_000)
                    return
                except PlaywrightError:
                    continue

        await page.evaluate(
            """
            () => {
              const selectors = [
                '#onetrust-consent-sdk',
                '.onetrust-pc-dark-filter',
                '#onetrust-consent-sdk .ot-sdk-container',
                '#onetrust-consent-sdk .ot-fade-in'
              ];
              for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                  element.remove();
                  element.style.pointerEvents = 'none';
                  element.style.display = 'none';
                }
              }
            }
            """
        )

    async def _open_category(self, page: Page, category: Category) -> None:
        await self.handle_cookie_consent(page)
        header = page.locator("#selector h3", has_text=category.label).first
        if await header.count():
            expanded = await header.get_attribute("aria-expanded")
            if expanded == "true":
                return
            await header.scroll_into_view_if_needed()
            await header.click(timeout=3_000)
            return

        locator = page.get_by_text(category.label, exact=True).first
        if await locator.count():
            await locator.scroll_into_view_if_needed()
            try:
                await locator.click(timeout=3_000)
            except PlaywrightError:
                pass

    async def _wait_for_category_rows(self, page: Page, category: Category) -> None:
        await page.wait_for_function(
            """
            (label) => {
              const header = [...document.querySelectorAll('#selector h3')]
                .find((candidate) => (candidate.innerText || '').trim() === label);
              const panelId = header?.getAttribute('aria-controls');
              const panel = panelId ? document.getElementById(panelId) : document.querySelector('#selector .ui-accordion-content-active');
              return !!panel?.querySelector('li .selector-item-row');
            }
            """,
            arg=category.label,
            timeout=self.timeout_ms,
        )

    async def _click_add_to_plot(self, page: Page, item_name: str) -> None:
        candidates = [
            page.locator("#selector .selector-item.ui-selected").get_by_text("Add to Plot", exact=True).first,
            page.locator("#selector .selector-item.ui-selected .big-play-button").first,
            page.locator("#selector .selector-item.ui-selected .plot-button[title='Add to plot']").first,
            page.locator("#selector .selector-item.ui-selected [title='Add to Plot']").first,
            page.locator("#selector .selector-item.ui-selected .ui-icon-plus").first,
            page.get_by_text("Add to Plot", exact=True).first,
            page.locator(".big-play-button").first,
            page.locator(".plot-button[title='Add to plot']").first,
            page.locator("[title='Add to Plot']").first,
        ]
        for add_to_plot in candidates:
            if await add_to_plot.count():
                await add_to_plot.click(force=True)
                await self._wait_for_legend_item(page, item_name)
                return

        raise RuntimeError(f"Could not find Add to Plot action for: {item_name}")

    async def _wait_for_legend_item(self, page: Page, item_name: str) -> None:
        await page.wait_for_function(
            """
            (itemName) => {
              return [...document.querySelectorAll('#legend .sl-composite, #legend .sl-component')]
                .some((el) => ((el.innerText || el.textContent || el.title || '').includes(itemName)));
            }
            """,
            arg=item_name,
            timeout=self.timeout_ms,
        )

    async def _find_legend_item_id(self, page: Page, item_name: str) -> str | None:
        return await page.evaluate(
            """
            (itemName) => {
              const matches = [...document.querySelectorAll('#legend .sl-composite, #legend .sl-component')]
                .filter((el) => ((el.innerText || el.textContent || el.title || '').includes(itemName)));
              const composite = matches.find((el) => el.classList.contains('sl-composite'));
              return (composite || matches[0] || {}).id || null;
            }
            """,
            item_name,
        )

    async def _legend_item_ids(self, page: Page) -> list[str]:
        return await page.evaluate(
            """
            () => [...document.querySelectorAll('#legend .sl-composite, #legend .sl-component')]
              .map((el) => el.id)
              .filter(Boolean)
            """
        )

    async def _resolve_modeled_filter_legend_id(
        self,
        page: Page,
        before_ids: list[str],
        original_id: str | None,
    ) -> str | None:

        before = set(before_ids)
        try:
            await page.wait_for_function(
                """
                (beforeIds) => {
                  const before = new Set(beforeIds);
                  return [...document.querySelectorAll('#legend .sl-composite, #legend .sl-component')]
                    .some((el) => el.id && !before.has(el.id));
                }
                """,
                arg=before_ids,
                timeout=min(self.timeout_ms, 5_000),
            )
        except PlaywrightTimeoutError:
            pass

        after_ids = await self._legend_item_ids(page)
        new_ids = [legend_id for legend_id in after_ids if legend_id not in before]
        if new_ids:
            return new_ids[-1]
        if original_id and original_id in after_ids:
            return original_id
        return after_ids[-1] if after_ids else None

    async def _wait_for_searchlight(self, page: Page) -> None:
        await page.get_by_text("Fluorophores", exact=True).wait_for(timeout=self.timeout_ms)
        await page.get_by_text("Light Sources", exact=True).wait_for(timeout=self.timeout_ms)
        await page.locator("#selector li .selector-item-row").first.wait_for(state="visible", timeout=self.timeout_ms)
        await page.wait_for_function(
            """
            () => {
              const row = document.querySelector('#selector li .selector-item-row');
              return !!(window.jQuery && row);
            }
            """,
            timeout=self.timeout_ms,
        )

    async def _with_retries(self, operation) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                await operation()
                return
            except Exception as exc:
                last_error = exc
                print(f"Attempt {attempt} failed: {exc}", flush=True)
        if last_error:
            raise last_error

    @staticmethod
    def _strip_list_prefix(value: str) -> str:
        return re.sub(r"^\s*\d+[.)]\s*", "", value).strip()

    @staticmethod
    def _extract_static_category_list(body_text: str, label: str) -> list[str]:
        headings = {"fluorophores", "filters", "filter sets", "light sources", "detectors"}
        target = label.lower()
        in_category = False
        values: list[str] = []

        for raw_line in body_text.splitlines():
            line = raw_line.strip()
            normalized = re.sub(r"^#+\s*", "", line).strip().lower()
            if normalized == target:
                in_category = True
                continue
            if in_category and normalized in headings:
                break
            if not in_category:
                continue

            match = re.match(r"^\s*\d+[.)]\s+(.+?)\s*$", line)
            if match:
                item_name = match.group(1).strip()
                if item_name.lower() not in IGNORED_ITEM_NAMES:
                    values.append(item_name)
            elif line:
                if line.lower() not in IGNORED_ITEM_NAMES:
                    values.append(line)

        return list(dict.fromkeys(values))

    @staticmethod
    def _parse_aoi(value: str) -> int:
        match = re.search(r"\d+(?:\.\d+)?", value)
        if not match:
            raise RuntimeError(f"Could not parse AOI value: {value!r}")
        return int(round(float(match.group(0))))


def selected_categories(args: argparse.Namespace) -> list[Category]:
    if args.all or not (args.fluorophores or args.filters or args.light_sources):
        return [CATEGORIES["fluorophores"], CATEGORIES["filters"], CATEGORIES["light_sources"]]

    selected: list[Category] = []
    if args.fluorophores:
        selected.append(CATEGORIES["fluorophores"])
    if args.filters:
        selected.append(CATEGORIES["filters"])
    if args.light_sources:
        selected.append(CATEGORIES["light_sources"])
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export spectral CSV data.")
    parser.add_argument("--all", action="store_true", help="Export fluorophores, filters, and light sources.")
    parser.add_argument("--fluorophores", action="store_true", help="Export fluorophores only.")
    parser.add_argument("--filters", action="store_true", help="Export filters only.")
    parser.add_argument("--light-sources", action="store_true", help="Export light sources only.")
    parser.add_argument(
        "--aoi-sweep",
        nargs=2,
        type=int,
        metavar=("DEGREES", "STEP"),
        default=(30, 1),
        help="For filters, sweep +/- DEGREES around default AOI in STEP-degree increments.",
    )
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible browser window.")
    parser.add_argument("--timeout-ms", type=int, default=30_000, help="Playwright timeout in milliseconds.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per item/AOI after the first attempt.")
    parser.add_argument("--limit", type=int, help="Export only the first N discovered items per selected category.")
    parser.add_argument("--overwrite", action="store_true", help="Re-download files even when output CSVs already exist.")
    parser.add_argument(
        "--source",
        default="searchlight",
        choices=("searchlight",),
        help="Data source to export. Used as the output filename prefix.",
    )
    return parser


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sweep_degrees, sweep_step = args.aoi_sweep

    exporter = SearchLightExporter(
        headless=not args.headed,
        timeout_ms=args.timeout_ms,
        retries=args.retries,
        sweep_degrees=sweep_degrees,
        sweep_step=sweep_step,
        limit=args.limit,
        skip_existing=not args.overwrite,
        source=args.source,
    )
    records = await exporter.run(selected_categories(args))
    successes = sum(1 for record in records if record.status == "success")
    skipped = sum(1 for record in records if record.status == "skipped")
    failures = sum(1 for record in records if record.status == "failed")
    print(f"Finished: {successes} successful, {skipped} skipped, {failures} failed", flush=True)
    return 0 if failures == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
