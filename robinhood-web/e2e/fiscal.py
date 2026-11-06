"""Check fiscal comparisons against a collected-data index at desktop and mobile sizes."""

import argparse
from dataclasses import replace
from pathlib import Path
import sys
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "robinhood-server/src"))

from robinhood_server.app import create_app  # noqa: E402
from robinhood_server.config import Settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="A local collected-data SQLite index")
    parser.add_argument("--browser", help="An installed Chromium executable")
    args = parser.parse_args()
    config = replace(Settings(), database_url="", job_database_url="")
    if args.database:
        config = replace(config, database=args.database)
    output = ROOT / ".artifacts/implementation/screenshots"
    output.mkdir(parents=True, exist_ok=True)
    errors, failed = [], []
    with TestClient(create_app(config)) as api:
        budget = api.get("/api/v1/fiscal?basis=budget")
        assert budget.status_code == 200, "Prepare a collected fiscal index first"
        data = budget.json()
        years = data["availableYears"]["budget"]
        assert len(years) >= 2, "At least two collected budget years are needed"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=args.browser)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="ko-KR")
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                target = urlsplit(route.request.url)
                if target.netloc != "robinhood.test":
                    return route.abort()
                response = api.get(target.path + ("?" + target.query if target.query else ""))
                if response.status_code >= 400:
                    failed.append((target.path, response.status_code))
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get("content-type", "application/octet-stream"))

            page.route("**/*", serve)
            page.goto("http://robinhood.test/fiscal?basis=budget")
            expect(page.get_by_role("heading", name="얼마나 달라졌나", exact=True)).to_be_visible()
            expect(page.get_by_label("재정 연도")).to_have_value(str(years[0]))
            assert page.get_by_label("재정 연도").locator("option").count() == len(years)
            page.get_by_label("추세를 볼 항목").select_option("ministry:보건복지부")
            expect(page.get_by_role("img", name="보건복지부 연도별 금액 추세")).to_be_visible()
            expect(page.locator(".fiscal-change-story")).to_contain_text("보건복지부")
            page.get_by_text("연도별 금액과 비중 표로 보기", exact=True).click()
            expect(page.locator(".fiscal-trend-chart .chart-data table")).to_contain_text(str(years[0]))
            page.get_by_label("재정 연도").select_option(str(years[-1]))
            expect(page.locator(".scope-bar")).to_contain_text(str(years[-1]) + "년 확정 예산")
            page.get_by_role("tab", name="예산안", exact=True).click()
            expect(page.locator(".fiscal-trends")).to_contain_text("전년도 확정 예산")
            expect(page.locator(".fiscal-trends .stat-detail")).to_contain_text(["정부 예산안"])
            page.get_by_role("tab", name="부처별 변화", exact=True).click()
            expect(page.locator(".fiscal-change-table")).to_be_visible()
            page.screenshot(path=str(output / "fiscal-trends-desktop.png"), full_page=True)
            for width in (390, 768):
                page.set_viewport_size({"width": width, "height": 844})
                expect(page.get_by_label("추세를 볼 항목")).to_be_visible()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Page overflows horizontally"
                page.screenshot(path=str(output / f"fiscal-trends-{width}.png"), full_page=True)
            assert not errors, errors
            assert not failed, failed
            browser.close()
    print("Passed: collected years, ministry selection, source table, proposal comparison, desktop and mobile layouts")


if __name__ == "__main__":
    main()
