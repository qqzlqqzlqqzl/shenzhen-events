"""Computed contrast and real keyboard focus, using the isolated API harness."""
import json,tempfile,struct,zlib,subprocess,base64
from urllib.parse import urlsplit
from pathlib import Path
from review_harness import Harness
from playwright.sync_api import expect

def rendered_chinese_fonts(fonts,text):
    points=[ord(c) for c in text if '\u4e00'<=c<='\u9fff'];proof=[]
    for font in fonts:
        if font['isCustomFont'] or font['glyphCount']<=0:continue
        match=subprocess.run(['fc-match','--format=%{family}\n%{file}\n%{index}',font['familyName']],check=True,capture_output=True,text=True,timeout=10).stdout.splitlines()
        assert font['familyName'] in match[0],match[0]
        charset=subprocess.run(['fc-query','-i',match[2],'--format=%{charset}',match[1]],check=True,capture_output=True,text=True,timeout=10).stdout
        ranges=[tuple(int(v,16) for v in token.split('-')) for token in charset.split()]
        covers=all(any(r[0]<=cp<=r[-1] for r in ranges) for cp in points)
        proof.append({'family':font['familyName'],'glyphs':font['glyphCount'],'font_file':Path(match[1]).name,'font_index':match[2],'covers_chinese_codepoints':covers})
    return sum(f['glyphs'] for f in proof if f['covers_chinese_codepoints'])>=len(points)>0,proof

CONTRAST=r'''(element,pseudo=null)=>{
 const parse=c=>c.match(/[\d.]+/g).map(Number);
 const over=(f,b)=>f.slice(0,3).map((x,i)=>x*(f[3]??1)+b[i]*(1-(f[3]??1)));
 const ancestors=[];for(let n=element;n;n=n.parentElement)ancestors.unshift(n);if(pseudo==='outline')ancestors.pop();
 let bg=[255,255,255];for(const n of ancestors)bg=over(parse(getComputedStyle(n).backgroundColor),bg);
 const style=getComputedStyle(element,pseudo==='outline'?null:pseudo),color=parse(pseudo==='outline'?style.outlineColor:style.color);color[3]=(color[3]??1)*Number(style.opacity);
 const fg=over(color,bg),lum=c=>c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4}).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
 const l=[lum(fg),lum(bg)].sort((a,b)=>b-a);
 return {ratio:(l[0]+.05)/(l[1]+.05),foreground:fg,background:bg,color:pseudo==='outline'?style.outlineColor:style.color,opacity:style.opacity};
}'''
h=Harness('readability-review');p=h.page
try:
    # Only the fresh fixture database is changed.
    with h.core.db() as db:
        db.execute("UPDATE events SET cost_text='199元',cost_free=0,details=?",(json.dumps({'attendance':'hybrid','organizer_role':'publisher','publisher':'合成发布账号'}),))
    ratios={}
    def contrast(selector,pseudo=None,minimum=4.5):
        result=p.locator(selector).first.evaluate('(e)=>('+CONTRAST+')(e,'+json.dumps(pseudo)+')')
        ratios[selector+(pseudo or '')]=result
        h.check('contrast_'+selector+(pseudo or ''),result['ratio']>=minimum)
    def tab_to(selector):
        target=p.locator(selector).first
        for _ in range(120):
            p.keyboard.press('Tab')
            if target.evaluate('(e)=>e===document.activeElement'):
                style=target.evaluate('(e)=>{const s=getComputedStyle(e);return {visible:e.matches(":focus-visible"),width:s.outlineWidth,style:s.outlineStyle,color:s.outlineColor}}')
                h.check('tab_focus_'+selector,style['visible'] and style['width']=='3px' and style['style']=='solid')
                return style
        raise AssertionError('Tab did not reach '+selector)
    h.goto()
    for selector in ['.date-chip span','.event-meta span:last-child','.source-label','.card-summary','.tag.topic-tag','.tag.secondary-tag']:
        contrast(selector)
    # Exercise the existing warning style with synthetic content.
    p.locator('.card-tags').first.evaluate('(e)=>{const tag=document.createElement("span");tag.className="tag warn";tag.textContent="信息可能已变化";e.append(tag)}')
    contrast('.tag.warn');contrast('#search','::placeholder')
    p.locator('body').click(position={'x':1,'y':1});ring=tab_to('#search')
    h.check('search_green_outline',ring['color']=='rgb(36, 90, 69)')
    contrast('#search','outline',3)
    # Undo a fixture feedback action; use Tab to test the dark notification.
    p.locator('[data-open]').first.click();expect(p.locator('#detail')).to_be_visible()
    p.locator('[data-feedback-signal="not_interested"]').click()
    expect(p.locator('.undo-bar').first).to_be_visible()
    undo=tab_to('.undo-bar button');h.check('undo_lime_outline',undo['color']=='rgb(213, 238, 131)')
    contrast('.undo-bar button','outline',3)
    p.keyboard.press('Escape')
    for width in (320,390):
        p.set_viewport_size({'width':width,'height':844});h.goto()
        h.check('cards_no_overflow_'+str(width),p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        p.locator('.event-card').first.screenshot(path=str(h.out/f'card-{width}.png'))
        p.locator('[data-open]').first.click();expect(p.locator('#detail')).to_be_visible()
        h.check('detail_no_overflow_'+str(width),p.locator('#detail').evaluate('(e)=>e.scrollWidth<=e.clientWidth'))
        p.locator('#detail').evaluate('(e)=>e.scrollTop=e.scrollHeight')
        h.check('detail_scroll_'+str(width),p.locator('#detail').evaluate('(e)=>e.scrollHeight<=e.clientHeight||e.scrollTop>0'))
        p.screenshot(path=str(h.out/f'detail-{width}.png'));p.keyboard.press('Escape')
        p.locator('#open-filters').click();expect(p.locator('#filter-dialog')).to_be_visible()
        search=tab_to('#search');h.check('mobile_search_ring_'+str(width),search['color']=='rgb(36, 90, 69)')
        contrast('#search','::placeholder')
        h.check('filter_no_overflow_'+str(width),p.locator('#filter-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth'))
        p.locator('#filter-dialog').evaluate('(e)=>e.scrollTop=e.scrollHeight')
        h.check('filter_scroll_'+str(width),p.locator('#filter-dialog').evaluate('(e)=>e.scrollHeight<=e.clientHeight||e.scrollTop>0'))
        p.screenshot(path=str(h.out/f'filters-{width}.png'));p.keyboard.press('Escape')
        p.locator('.event-card').last.scroll_into_view_if_needed()
        h.check('page_scroll_'+str(width),p.evaluate('scrollY>0'))
    h.report['computed_contrasts']=ratios
    # Use Chromium's native tabs zoom API in a temporary test-only extension.
    # Verify zoom, DPR and CSS viewport; never emulate deviceScaleFactor.
    profile=Path(tempfile.mkdtemp(prefix='radar-native-zoom-'));browser=None
    try:
        extension=profile/'extension';extension.mkdir()
        (extension/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Isolated native zoom regression','version':'1.0','permissions':['tabs'],'background':{'service_worker':'worker.js'}}))
        (extension/'worker.js').write_text('globalThis.nativeZoom=async(url)=>{const tabs=await chrome.tabs.query({});const tab=tabs.find(t=>t.url===url);if(!tab)throw new Error("fixture tab not found");await chrome.tabs.setZoom(tab.id,2);return await chrome.tabs.getZoom(tab.id)};')
        browser=h.browser.browser_type.launch_persistent_context(str(profile/'browser'),executable_path=h.browser.browser_type.executable_path,headless=False,no_viewport=True,locale='zh-CN',ignore_default_args=['--disable-extensions'],args=['--window-size=1280,1000','--disable-extensions-except='+str(extension),'--load-extension='+str(extension)])
        browser.route(lambda url:urlsplit(url).netloc!=urlsplit(h.base).netloc,lambda r:r.abort())
        browser.add_cookies(h.ctx.cookies());zp=browser.new_page();zp.goto(h.base+'/events/?view=all');zp.locator('.event-card').first.wait_for();zp.bring_to_front()
        try:
            worker=browser.service_workers[0] if browser.service_workers else browser.wait_for_event('serviceworker',timeout=10000)
            native=worker.evaluate('(url)=>nativeZoom(url)',zp.url);zp.wait_for_timeout(200)
        except Exception as exc:
            native=None;h.report['native_zoom_unavailable_reason']=str(exc)[:400]
        actual=zp.evaluate('({dpr:devicePixelRatio,width:innerWidth,outer:outerWidth,overflow:document.documentElement.scrollWidth>innerWidth})')
        supported=native==2 and abs(actual['dpr']-2)<.05 and actual['width']<=actual['outer']/1.9
        h.report['native_zoom']={'supported':supported,'requested_percent':200,'reported_zoom':native,'observed':actual,'method':'chrome.tabs.setZoom/getZoom; deviceScaleFactor not used'}
        h.check('native_200_supported',supported)
        h.check('native_200_no_overflow',not actual['overflow']);zp.locator('[data-open]').first.click();expect(zp.locator('#detail')).to_be_visible()
        h.check('native_200_detail_no_overflow',zp.locator('#detail').evaluate('(e)=>e.scrollWidth<=e.clientWidth'))
        heading=zp.locator('.detail-title');expect(heading).to_contain_text('审阅活动')
        heading.scroll_into_view_if_needed();zp.evaluate('document.fonts.ready');zp.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        session=browser.new_cdp_session(zp);session.send('DOM.enable');session.send('CSS.enable')
        root=session.send('DOM.getDocument')['root']['nodeId'];node=session.send('DOM.querySelector',{'nodeId':root,'selector':'.detail-title'})['nodeId']
        fonts=session.send('CSS.getPlatformFontsForNode',{'nodeId':node})['fonts']
        h.report['native_zoom'].update(rendered_fonts=fonts,physical_android_ios=False,visual_capture='headed Chromium/Xvfb Page.captureScreenshot fromSurface=false native-200.png')
        (h.out/'native-metrics.json').write_text(json.dumps(h.report['native_zoom'],ensure_ascii=False,indent=2))
        zp.screenshot(path=str(h.out/'native-200-playwright.png'))
        session.send('Page.bringToFront');zp.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        shot=base64.b64decode(session.send('Page.captureScreenshot',{'format':'png','fromSurface':False,'captureBeyondViewport':False})['data'])
        (h.out/'native-200.png').write_bytes(shot);offset=8;compressed=b''
        while offset<len(shot):
            size=struct.unpack('>I',shot[offset:offset+4])[0];kind=shot[offset+4:offset+8]
            if kind==b'IDAT':compressed+=shot[offset+8:offset+8+size]
            offset+=size+12
        print('Native rendered fonts:',json.dumps(fonts,ensure_ascii=False),flush=True)
        chinese_ok,font_proof=rendered_chinese_fonts(fonts,heading.inner_text())
        (h.out/'native-font-coverage.json').write_text(json.dumps(font_proof,ensure_ascii=False,indent=2))
        h.check('native_200_actual_cjk_glyphs',chinese_ok)
        h.check('native_200_visual_capture_not_blank',len(set(zlib.decompress(compressed)))>8)
        h.check('native_200_capture_keeps_real_zoom',worker.evaluate('(url)=>chrome.tabs.query({}).then(t=>chrome.tabs.getZoom(t.find(x=>x.url===url).id))',zp.url)==2 and zp.evaluate('devicePixelRatio')==2)
        close=zp.locator('#close-detail');close.scroll_into_view_if_needed();close.click(trial=True);close.focus();expect(close).to_be_focused()
        h.check('native_200_close_reachable',close.evaluate('e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth}'))
    finally:
        if browser:browser.close()
        # Retain the isolated fixture profile outside uploaded artifacts; no pruning.
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
