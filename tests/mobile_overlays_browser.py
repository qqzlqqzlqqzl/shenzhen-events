"""Real combined comparison/feedback flows in an isolated Chromium fixture."""
from review_harness import Harness
from playwright.sync_api import expect

h=Harness('mobile-overlays-review');p=h.page
geometries={}
captures={}

def visual_state():
    return p.evaluate('''()=>({scrollY,innerWidth,innerHeight,dpr:devicePixelRatio,visualViewport:{width:visualViewport.width,height:visualViewport.height,offsetTop:visualViewport.offsetTop,pageTop:visualViewport.pageTop},bars:Object.fromEntries(['compare-bar','undo-bar'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return [id,{x:r.x,y:r.y,width:r.width,height:r.height}]}))})''')

def capture(label,filename):
    # Normal smooth motion remains enabled. Wait for layout AND scroll to settle
    # before pairing screenshot pixels with fixed-overlay geometry.
    frames=p.evaluate('''async()=>{await document.fonts.ready;return await new Promise((resolve,reject)=>{let last='',since=performance.now(),start=since,frames=[];function frame(){const state={time:performance.now()-start,scrollY,innerHeight,visualViewport:{pageTop:visualViewport.pageTop,offsetTop:visualViewport.offsetTop,height:visualViewport.height},bars:Object.fromEntries(['compare-bar','undo-bar'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return [id,{x:r.x,y:r.y,width:r.width,height:r.height}]}))};frames.push(state);const key=JSON.stringify([state.scrollY,state.visualViewport,state.bars]);if(key!==last){last=key;since=performance.now()}if(performance.now()-since>=300)return resolve(frames);if(performance.now()-start>3000)return reject(Error('Viewport did not settle'));requestAnimationFrame(frame)}requestAnimationFrame(frame)})}''')
    before=visual_state()
    valid=geometry(label)
    p.screenshot(path=str(h.out/filename))
    after=visual_state()
    captures[filename]={'successive_normal_motion_frames':frames,'before':before,'after':after}
    h.check('stable_capture_'+label,before==after)
    return valid
def geometry(label):
    bars={name:p.locator('#'+name).bounding_box() for name in ('compare-bar','undo-bar')}
    compare,undo=bars['compare-bar'],bars['undo-bar']
    overlap=max(0,min(compare['y']+compare['height'],undo['y']+undo['height'])-max(compare['y'],undo['y']))
    viewport=p.viewport_size
    visible=all(box['x']>=0 and box['y']>=0 and box['x']+box['width']<=viewport['width']+.5 and box['y']+box['height']<=viewport['height']+.5 for box in bars.values())
    reachable={selector:p.locator(selector).evaluate('(e)=>{const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return hit===e||e.contains(hit)}') for selector in ('#compare-open','#compare-clear','#undo-feedback','#dismiss-undo')}
    result={'viewport':viewport,'bars':bars,'overlap_px':overlap,'within_viewport':visible,'reachable':reachable}
    geometries[label]=result
    return overlap==0 and visible and all(reachable.values())
def event(id):return p.request.get(h.base+'/events/api/event/'+id).json()
def tab_to(selector):
    target=p.locator(selector)
    for _ in range(120):
        p.keyboard.press('Tab')
        if target.evaluate('(e)=>e===document.activeElement'):
            return target.evaluate('(e)=>{const s=getComputedStyle(e);return e.matches(":focus-visible")&&s.outlineWidth==="3px"&&s.outlineStyle==="solid"}')
    return False
def feedback_and_close(id,route='button'):
    p.locator('[data-open="'+id+'"]').first.click();expect(p.locator('#detail')).to_be_visible()
    p.locator('[data-feedback-signal="not_interested"]').click()
    expect(p.locator('#undo-bar')).to_be_visible()
    p.wait_for_function('!feedbackSaving.size')
    h.check('undo_inside_detail_'+str(p.viewport_size['width']),p.locator('#undo-bar').evaluate('(e)=>e.parentElement.id==="detail"'))
    if route=='escape':p.keyboard.press('Escape')
    elif route=='back':p.go_back()
    else:p.locator('#close-detail').click()
    expect(p.locator('#detail')).not_to_be_visible()
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    expect(p.locator('#compare-bar')).to_be_visible();expect(p.locator('#undo-bar')).to_be_visible()
try:
    with h.core.db() as db:
        for index,id in enumerate(h.ids):
            db.execute('UPDATE events SET title=? WHERE id=?',('Synthetic long comparison candidate '+str(index)+' / mobile wrapping verification / detailed event title',id))
    for width in (320,390,1440):
        p.set_viewport_size({'width':width,'height':640 if width==320 else 844});h.goto()
        candidates=p.locator('.event-card').evaluate_all('(cards)=>cards.slice(0,2).map(c=>c.dataset.event)')
        assert len(candidates)==2
        for id in candidates:p.locator('[data-compare="'+id+'"]').first.click()
        expect(p.locator('#compare-chips button')).to_have_count(2)
        target=candidates[0];before=event(target)
        feedback_and_close(target)
        valid=capture('two_candidates_'+str(width),f'combined-{width}.png')
        # Record every requested viewport before reporting any geometry failure.
        # A failure still fails the suite; blocked controls are never force-clicked.
        if not valid:continue
        h.check('compare_tab_focus_with_pending_undo_'+str(width),tab_to('#compare-open'))
        h.check('undo_tab_focus_with_comparison_'+str(width),tab_to('#undo-feedback'))
        p.locator('#compare-open').click();expect(p.locator('#compare-dialog')).to_be_visible()
        expect(p.locator('.compare-item')).to_have_count(2);p.locator('#close-compare').click()
        h.check('comparison_opens_with_pending_undo_'+str(width))
        third=p.locator('.event-card').evaluate_all('(cards)=>cards.find(c=>c.querySelector("[data-compare]")?.getAttribute("aria-pressed")==="false")?.dataset.event')
        assert third
        p.locator('[data-compare="'+third+'"]').first.click();expect(p.locator('#compare-chips button')).to_have_count(3)
        h.check('three_candidate_geometry_'+str(width),capture('three_candidates_'+str(width),f'combined-three-{width}.png'))
        p.locator('#compare-chips button').last.click();expect(p.locator('#compare-chips button')).to_have_count(2)
        h.check('removed_candidate_geometry_'+str(width),geometry('candidate_removed_'+str(width)))
        p.locator('#undo-feedback').click();expect(p.locator('#undo-bar')).not_to_be_visible()
        after=event(target)
        h.check('undo_restores_feedback_without_changing_favorite_'+str(width),all(after[key]==before[key] for key in ('id','feedback','feedback_tags','favorite')))
        expect(p.locator('#compare-chips button')).to_have_count(2)
        h.check('comparison_survives_undo_'+str(width),p.locator('#compare-bar').is_visible())
        feedback_and_close(target,route='escape')
        h.check('escape_close_geometry_'+str(width),geometry('escape_closed_'+str(width)))
        p.locator('#undo-feedback').click();expect(p.locator('#undo-bar')).not_to_be_visible()
        h.check('escape_undo_restores_feedback_'+str(width),event(target)['feedback']==before['feedback'])
        feedback_and_close(target,route='back')
        h.check('back_close_geometry_'+str(width),geometry('back_closed_'+str(width)))
        expect(p.locator('#compare-chips button')).to_have_count(2)
        h.check('comparison_survives_back_'+str(width),p.locator('#compare-bar').is_visible())
        p.locator('#compare-clear').click();expect(p.locator('#compare-bar')).not_to_be_visible()
        expect(p.locator('#undo-bar')).to_be_visible()
        h.check('undo_survives_comparison_clear_'+str(width),p.locator('#undo-feedback').evaluate('(e)=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}'))
        p.locator('#dismiss-undo').click();expect(p.locator('#undo-bar')).not_to_be_visible()
        h.check('dismiss_keeps_feedback_'+str(width),event(target)['feedback']==('' if before['feedback']=='not_interested' else 'not_interested'))
        h.check('dismiss_restores_unobstructed_page_'+str(width),p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    h.report['geometries']=geometries
    for label,result in geometries.items():
        h.check('no_overlap_'+label,result['overlap_px']==0)
        h.check('within_viewport_'+label,result['within_viewport'])
        h.check('actions_reachable_'+label,all(result['reachable'].values()))
except Exception as exc:
    h.report['geometries']=geometries;h.report['errors'].append(str(exc));raise
finally:
    h.report['captures']=captures
    h.close()
