"""Exercise the production build against the actual API without opening a port."""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'robinhood-server/src'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Test an existing server instead of the in-process API')
    parser.add_argument('--channel', default=None, help='For example: chrome')
    args = parser.parse_args()
    base = (args.url or 'http://robinhood.test').rstrip('/')
    output = ROOT / '.artifacts/implementation/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    errors, requests_failed = [], []
    api = None
    if not args.url:
        from fastapi.testclient import TestClient
        from robinhood_server.app import create_app
        api = TestClient(create_app())
        assert (ROOT / 'robinhood-web/dist/index.html').is_file(), 'Run npm run build first.'
        assert api.get('/api/health').status_code == 200, 'Run robinhood index first.'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        if api:
            def serve(route):
                request = urlsplit(route.request.url)
                if request.netloc != 'robinhood.test':
                    return route.abort()  # Fonts and third-party SDK aren't part of this test.
                response = api.get(request.path + ('?' + request.query if request.query else ''))
                if response.status_code >= 400:
                    requests_failed.append((request.path, response.status_code))
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get('content-type', 'application/octet-stream'))
            page.route('**/*', serve)

        def visit(path, title):
            page.goto(base + path)
            expect(page.get_by_role('heading', name=title, exact=True).first).to_be_visible()
            expect(page.locator('.loading')).to_have_count(0)

        def capture(name):
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), page.url
            page.screenshot(path=str(output / (name + '.png')), full_page=True)

        visit('/', '우리 지역의 기록을 한눈에')
        expect(page.locator('main')).to_contain_text('2명')
        capture('home-desktop')
        page.get_by_label('시·도', exact=True).select_option('부산')
        expect(page.locator('main')).to_contain_text('부산 국회의원 보고자료')
        visit('/members', '의원·정당 찾아보기')
        page.get_by_label('정당', exact=True).select_option('더불어민주당')
        expect(page.locator('.metrics')).to_contain_text('171명')
        page.get_by_label('정당', exact=True).select_option('')
        page.get_by_role('textbox').fill('정청래')
        page.get_by_role('button', name='검색', exact=True).click()
        expect(page.locator('tbody tr')).to_have_count(1)
        page.get_by_role('link', name='정청래', exact=True).click()
        expect(page.get_by_role('heading', name='정청래', exact=True)).to_be_visible()
        for tab in ['정치자금', '신고재산', '법안·표결', '출처']:
            page.get_by_role('tab', name=tab, exact=True).click()
            expect(page.get_by_role('tab', name=tab, exact=True)).to_have_attribute('aria-selected', 'true')
            assert len(page.locator('main').inner_text()) > 300

        visit('/members?month=2024-06', '의원·정당 찾아보기')
        expect(page.locator('.scope-bar')).to_contain_text('2024.06.01')
        visit('/rankings', '비교·랭킹')
        expect(page.locator('.metrics')).to_contain_text('171')
        page.get_by_role('tab', name='지방의회', exact=True).click()
        expect(page.locator('.scope-bar')).to_contain_text('의회운영업무추진비')
        page.get_by_role('tab', name='신고재산', exact=True).click()
        expect(page.locator('.scope-bar')).to_contain_text('2025-12-31')
        visit('/councils', '지방의회 · 직책 경비')
        expect(page.locator('.metrics')).to_contain_text('916')
        page.get_by_label('경비 재원').select_option('COUNCIL_COMMON')
        expect(page.locator('.scope-bar')).to_contain_text('의정운영공통경비')

        visit('/places', '자주 결제한 장소')
        expect(page.get_by_role('heading', name='가시리', exact=True)).to_be_visible()
        capture('places-desktop')
        page.get_by_role('link').filter(has=page.get_by_role('heading', name='가시리', exact=True)).click()
        expect(page.locator('.metrics')).to_contain_text('424건')
        capture('place-detail-desktop')
        page.get_by_role('tab', name='의회 경비', exact=True).click()
        expect(page.locator('.metrics')).to_contain_text('166,000원')
        visit('/transactions/ka22-24_163113', '거래 상세')
        expect(page.locator('main')).to_contain_text('취소·반환')
        expect(page.locator('main')).to_contain_text('90,000원')
        visit('/transactions/mapo-f0a850f38629-28', '거래 상세')
        expect(page.locator('.metrics')).to_contain_text('27,500원')
        visit('/fiscal?year=2024', '나라 살림')
        expect(page.locator('main')).to_contain_text('594.5조')
        page.get_by_role('tab', name='확정 예산', exact=True).click()
        expect(page.locator('.scope-bar')).to_contain_text('2026년 확정 예산')
        page.get_by_role('tab', name='예산안', exact=True).click()
        expect(page.locator('.scope-bar')).to_contain_text('2027년 예산안')
        visit('/sources?tab=methods', '데이터와 확인 방법')
        page.locator('details summary').first.click()
        expect(page.locator('details[open]')).to_have_count(1)
        page.get_by_role('tab', name='다시 볼 표시', exact=True).click()
        expect(page.get_by_role('link', name='근거 거래 →').first).to_be_visible()
        page.get_by_role('button', name='다음 페이지', exact=True).click()
        expect(page).to_have_url(re.compile(r'[?&]page=2(?:&|$)'))

        page.set_viewport_size({'width': 390, 'height': 844})
        for path, title, name in [('/', '우리 지역의 기록을 한눈에', 'home-mobile'),
                                   ('/places', '자주 결제한 장소', 'places-mobile'),
                                   ('/members/na-279', '정청래', 'profile-mobile'),
                                   ('/fiscal', '나라 살림', 'fiscal-mobile')]:
            visit(path, title)
            expect(page.locator('.scope-bar').first).to_be_visible()
            capture(name)
        page.get_by_role('button', name='메뉴 열기').click()
        expect(page.get_by_role('navigation', name='모바일 주 메뉴')).to_be_visible()
        assert not errors, errors
        assert not requests_failed, requests_failed
        browser.close()
    if api:
        api.close()
    print('Passed: navigation, filters, profiles, funding separation, sources and mobile layout.')


if __name__ == '__main__':
    main()
