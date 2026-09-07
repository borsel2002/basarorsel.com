"""Optional local browser gate: pip install playwright; playwright install chromium.
Serves local artifacts only, blocks all off-server requests. No runtime dependency.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
import os
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

# Public site assets only — never serve data.json, FIT files, or list directories.
ALLOW = {'/', '/index.html', '/signature.svg', '/logo.svg', '/favicon.svg',
         '/favicon.ico', '/brand-logo-light.svg', '/brand-logo-dark.svg'}

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path not in ALLOW:
            self.send_error(404, 'Not Found')
            return
        super().do_GET()


def main():
    servers = []
    urls = []
    for site in ('basarorsel.com', 'basarorsel.me'):
        site_dir = Path(os.environ.get("BASAR_ME_PREVIEW", str(ROOT/site))) if site == "basarorsel.me" else ROOT/site
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(site_dir)))
        Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        urls.append(f'http://127.0.0.1:{server.server_port}/')
    evidence = []
    screenshots = Path(tempfile.mkdtemp(prefix='basar-site-qa-'))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                boxes = []
                for site, url in zip(('com','me'), urls):
                    page = browser.new_page(viewport={'width':width,'height':1000})
                    errors, remote = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    def guard(route):
                        if route.request.url.startswith(url): route.continue_()
                        else: remote.append(route.request.url); route.abort()
                    page.route('**/*', guard)
                    page.goto(url, wait_until='networkidle')
                    box = page.locator('.signature-name').bounding_box()
                    assert box and page.locator('.signature-name').evaluate('(e)=>e.complete && e.naturalWidth>0')
                    boxes.append(box)
                    for mode in ('light','dark'):
                        page.evaluate('(mode)=>document.documentElement.dataset.theme=mode',mode)
                        assert page.locator('.signature-name').evaluate('(e)=>getComputedStyle(e).filter') == ('invert(1)' if mode=='dark' else 'none')
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), (site,width,'hero overflow')
                    page.screenshot(path=str(screenshots/f'{site}-{width}-hero.png'))
                    if site=='com':
                        assert page.locator('#monChart rect').count()>0
                        assert page.locator('.break-point').count()>0
                        for category in ('strength','mobility'):
                            expected = page.evaluate('(c)=>Object.keys(D.muscle_load[c].all_time).sort()',category)
                            actual = page.locator('#muscles-'+category+' [data-muscle]').evaluate_all('(els)=>[...new Set(els.map(e=>e.dataset.muscle))].sort()')
                            assert actual==expected, (category,actual,expected)
                            assert page.locator('#muscles-'+category+' .body-outline').count()==2
                        for section in ('athlete','builder','identity','contact','data'):
                            page.evaluate('(s)=>location.hash=s', section)
                            page.wait_for_function('(s)=>document.documentElement.dataset.section===s', arg=section)
                            assert page.locator('section.active').get_attribute('id')==section
                        for tab in ('running','mountaineering','triathlon','strength','mobility'):
                            page.locator('#tab-'+tab).click()
                            assert page.locator('#data-'+tab).is_visible()
                            assert page.locator('[role=tabpanel]:visible').count()==1
                            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), (width,tab,'overflow')
                            if tab in ('strength','mobility'):
                                page.locator('#window-'+tab).select_option('recent_28d')
                                assert page.locator('#counts-'+tab).inner_text()
                        page.locator('#tab-strength').click()
                        page.screenshot(path=str(screenshots/f'{site}-{width}-strength.png'),full_page=True)
                        page.locator('#tab-strength').press('Home')
                        assert page.locator('#tab-running').get_attribute('aria-selected')=='true'
                    assert page.locator('nav a[href="https://basarorsel.'+('me' if site=='com' else 'com')+'"]').count()==1
                    assert page.locator('footer a[href="https://basarorsel.'+('me' if site=='com' else 'com')+'"]').count()==1
                    if site=='me' and page.locator('#about').count():
                        for name in ('principles','academic','hobbies'):
                            page.evaluate('(s)=>location.hash=s',name)
                            page.wait_for_function('(s)=>!document.getElementById(s).hidden',arg=name)
                            assert page.locator('#about').is_visible()
                            assert page.locator('#'+name).is_visible()
                            assert page.locator('#about [role=tabpanel]:visible').count()==1
                        page.locator('#about-tab-hobbies').press('Home')
                        page.wait_for_function("location.hash==='#principles'")
                    assert not errors, errors
                    assert not remote, remote
                    evidence.append({'site':site,'width':width,'signature':box,'js_errors':errors,'external_requests':remote})
                    page.close()
                assert boxes[0]==boxes[1], ('signature mismatch',width,boxes)
            browser.close()
        print(json.dumps({'passed':True,'checks':evidence,'screenshots':str(screenshots)},indent=2))
    finally:
        for server in servers: server.shutdown()

if __name__=='__main__': main()
