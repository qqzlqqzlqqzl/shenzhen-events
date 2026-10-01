"""Isolated real browser/API harness. No live preferences or paid model calls."""
import importlib.util,json,os,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')

class Harness:
    def __init__(self, name):
        self.out=ROOT/'artifacts'/name;self.out.mkdir(parents=True,exist_ok=True)
        self.tmp=Path(tempfile.mkdtemp(prefix='radar-review-'));os.environ['RADAR_ROOT']=str(self.tmp)
        (self.tmp/'static').symlink_to(ROOT/'static',target_is_directory=True)
        (self.tmp/'sources.json').write_text('[{"id":"a","name":"测试来源","url":"https://example.com","priority":10}]')
        sys.path.insert(0,str(ROOT));sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')
        from radar import core,api
        self.core=core;self.api=api;api.initialize_settings();core.init()
        self.ids=[]
        for i in range(5):
            start=core.now()+timedelta(days=i+2)
            core.ingest({'id':'a','priority':10},{'title':f'审阅活动 {i+1}','url':f'https://example.com/e{i}', 'start_at':start.isoformat(),'end_at':(start+timedelta(hours=2)).isoformat(),'location':f'深圳南山地点 {i+1}','summary':'隔离环境的可重复审阅活动。','event_type':'ConferenceEvent','event_type_state':'done'})
            with core.db() as c:self.ids.append(c.execute('SELECT id FROM events WHERE url=?',(f'https://example.com/e{i}',)).fetchone()[0])
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.base=f'http://127.0.0.1:{port}'
        self.server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        import requests
        for _ in range(80):
            try:
                if requests.get(self.base+'/events/api/health',timeout=.3).ok:break
            except requests.RequestException:pass
            time.sleep(.1)
        else:raise RuntimeError('isolated API did not start')
        spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
        from playwright.sync_api import sync_playwright
        self.pw=sync_playwright().start();self.browser=self.pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
        self.ctx=self.browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
        self.ctx.add_cookies([{'name':api.COOKIE,'value':api.sign_session({'id':1,'username':'review-owner'}),'domain':'127.0.0.1','path':'/events','secure':False,'httpOnly':True,'sameSite':'Lax'}])
        self.page=self.ctx.new_page();self.page.set_default_timeout(10000)
        self.report={'checks':{},'errors':[],'isolated':True}
        self.page.on('pageerror',lambda e:self.report['errors'].append(str(e)))
    def goto(self,query='?view=all'):
        from playwright.sync_api import expect
        self.page.goto(self.base+'/events/'+query,wait_until='domcontentloaded');self.page.locator('#workspace').wait_for()
        if self.page.locator('#event-list').is_visible():expect(self.page.locator('#event-list')).to_have_attribute('aria-busy','false')
    def check(self,name,value=True):
        self.report['checks'][name]=bool(value)
        if not value:raise AssertionError(name)
        print('PASS',name,flush=True)
    def close(self):
        self.report['passed']=bool(self.report['checks']) and all(self.report['checks'].values()) and not self.report['errors']
        (self.out/'result.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2))
        self.browser.close();self.pw.stop();self.server.terminate()
        try:self.server.wait(timeout=5)
        except subprocess.TimeoutExpired:self.server.kill();self.server.wait(timeout=5)
        shutil.rmtree(self.tmp,ignore_errors=True)
        if not self.report['passed']:raise AssertionError(self.report)
