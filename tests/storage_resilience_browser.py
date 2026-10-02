"""Real Chromium with synthetic storage failures and a disposable local API."""
import json
from review_harness import Harness
from playwright.sync_api import expect

h=Harness('storage-resilience-review');p=h.page
try:
    p.add_init_script("""(() => {
      const native=window.localStorage;
      const saved='radar.saved.v1:review-owner',filters='radar.filters.v1:review-owner';
      native.setItem(saved,JSON.stringify([{name:'Preserved',query:'q=keep'}]));
      native.setItem(filters,JSON.stringify({version:1,query:'q=keep'}));
      window.storageProbe={blocked:true,native,saved,filters};
      Object.defineProperty(window,'localStorage',{get(){return {
        getItem(k){if(storageProbe.blocked)throw new DOMException('Synthetic read failure','SecurityError');return native.getItem(k)},
        setItem(k,v){native.setItem(k,v)}
      }}});
    })();""")
    h.goto('')
    h.check('failed_filter_read_preserves_valid_bytes',p.evaluate("JSON.parse(storageProbe.native.getItem(storageProbe.filters)).query==='q=keep'"))
    p.evaluate('storageProbe.blocked=false;rememberFilters()')
    h.check('recovered_read_does_not_authorize_default_overwrite',p.evaluate("JSON.parse(storageProbe.native.getItem(storageProbe.filters)).query==='q=keep'"))
    p.locator('#saved-views > summary').click()
    p.locator('#saved-view-name').fill('New');p.locator('#saved-view-name').press('Enter')
    expect(p.locator('#saved-view-choice')).to_have_count(1)
    h.check('named_save_reconciles_existing_list',p.evaluate("JSON.parse(storageProbe.native.getItem(storageProbe.saved)).map(x=>x.name).join(',')==='Preserved,New'"))
    p.locator('#saved-view-choice').select_option('1');p.locator('#delete-saved-view').click()
    expect(p.locator('#undo-saved-view')).to_be_visible()
    p.evaluate('storageProbe.blocked=true')
    p.locator('#undo-saved-view').focus();p.keyboard.press('Enter')
    expect(p.locator('#toast')).to_contain_text('未允许保存')
    expect(p.locator('#undo-saved-view')).to_be_visible()
    h.check('failed_undo_keeps_retry_record',p.evaluate("JSON.parse(storageProbe.native.getItem(storageProbe.saved)).length===1"))
    p.evaluate('storageProbe.blocked=false');p.locator('#undo-saved-view').click()
    expect(p.locator('#undo-saved-view')).to_be_hidden()
    h.check('undo_retry_restores_confirmed_list',p.evaluate("JSON.parse(storageProbe.native.getItem(storageProbe.saved)).length===2"))
    p.locator('#search').fill('chosen');p.locator('#search').press('Enter')
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    h.check('explicit_choice_persists_after_read_recovery',p.evaluate("new URLSearchParams(JSON.parse(storageProbe.native.getItem(storageProbe.filters)).query).get('q')==='chosen'"))
    p.screenshot(path=str(h.out/'storage-recovery.png'))
    h.report['qualification']='Storage failures are synthetic in real Chromium; API and cookies belong to a disposable local fixture. Owner-switch and persisted pageshow boundaries are covered by the isolated DOM suite, not a production multi-user claim.'
except Exception as exc:
    h.report['errors'].append(str(exc));raise
finally:h.close()
