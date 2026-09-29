#!/usr/bin/env python3
"""Install ONLY Shenzhen Radar resources; preserve existing server applications.
Run: sudo python3 deploy/install.py services|publish|rollback
Requires the project already cloned, dependencies installed and tests passed.
"""
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BACKUP=ROOT/'.private/deployment-backup'
NGINX=Path('/etc/nginx/conf.d/toolbox-https.conf')
PORTAL=Path('/var/www/server-portal/index.html')
SOURCE_PORTAL=Path('/home/ubuntu/server-portal/index.html')

def run(*cmd):return subprocess.run(cmd,check=True,text=True)
def write(path,content,mode=0o644):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.radar-new');tmp.write_text(content);os.chmod(tmp,mode);os.replace(tmp,p)
def backup(path):
    BACKUP.mkdir(parents=True,exist_ok=True);os.chmod(BACKUP,0o700)
    target=BACKUP/str(path).lstrip('/').replace('/','__')
    if not target.exists():shutil.copy2(path,target)
    return target

def services():
    for p in ['data','logs','.private']:
        (ROOT/p).mkdir(exist_ok=True);os.chown(ROOT/p,1000,1001)
    for job in ['collect','analyze']:
        logfile=ROOT/'logs'/(job+'.log');logfile.touch(exist_ok=True);os.chown(logfile,1000,1001);os.chmod(logfile,0o600)
    common=f'''User=ubuntu
Group=ubuntu
WorkingDirectory={ROOT}
Environment=TZ=Asia/Shanghai
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={ROOT}/data {ROOT}/logs {ROOT}/.private
MemoryHigh=160M
MemoryMax=224M
CPUQuota=50%
Nice=10
'''
    web=f'''[Unit]
Description=Shenzhen Events Radar (independent frontend)
After=network.target
[Service]
Type=simple
{common}ExecStart={ROOT}/.venv/bin/uvicorn radar.api:app --host 127.0.0.1 --port 8093 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=8
[Install]
WantedBy=multi-user.target
'''
    write('/etc/systemd/system/shenzhen-events.service',web)
    for job in ['collect','analyze']:
        environment='EnvironmentFile=/home/ubuntu/ai-news/.private/ai.env\n' if job=='analyze' else ''
        unit=f'''[Unit]
Description=Shenzhen Radar {job} (bounded independent worker)
After=network-online.target shenzhen-events.service
[Service]
Type=oneshot
{common}{environment}ExecStart={ROOT}/.venv/bin/python -m radar.worker {job} --limit 120
TimeoutStartSec=8min
StandardOutput=append:{ROOT}/logs/{job}.log
StandardError=append:{ROOT}/logs/{job}.log
'''
        write(f'/etc/systemd/system/shenzhen-events-{job}.service',unit)
        timer=f'''[Unit]
Description=Schedule Shenzhen Radar {job}
[Timer]
OnBootSec={'3min' if job=='collect' else '5min'}
OnUnitActiveSec={'1h' if job=='collect' else '15min'}
RandomizedDelaySec=90
Unit=shenzhen-events-{job}.service
[Install]
WantedBy=timers.target
'''
        write(f'/etc/systemd/system/shenzhen-events-{job}.timer',timer)
    run('systemctl','daemon-reload');run('systemctl','enable','--now','shenzhen-events.service')
    run('systemctl','enable','--now','shenzhen-events-collect.timer','shenzhen-events-analyze.timer')

def patched_portal(html):
    if 'class="card events"' in html:return html
    needle='<section class="meta"'
    card='''<a class="card events" href="/events/" data-health="/events/api/health" data-key="4">
<div class="card-top"><div class="icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="m12 12 7-7M12 1v2M1 12h2M21 12h2"/></svg></div><div class="state"><span class="dot"></span><span class="label">检测中</span></div></div>
<h3>深圳活动雷达</h3><p>发现创客、开源、机器人与本地好活动。独立筛选、收藏与日历，不用在多个平台来回翻。</p>
<div class="card-bottom"><span class="enter">发现线下活动 <span class="arrow">→</span></span><span class="key">4</span></div></a>
'''
    idx=html.find(needle)
    if idx<0:raise RuntimeError('Portal layout changed; refusing blind modification')
    close=html.rfind('</section>',0,idx)
    if close<0:raise RuntimeError('Card grid boundary missing')
    html=html[:close]+card+html[close:]
    css='''\n/* Shenzhen Radar: additive fourth card; original routes unchanged. */
.events .icon{background:linear-gradient(145deg,#ecf5e2,#dcecc8);color:#527741}.card.events:after{background:radial-gradient(circle,#9fc775,transparent 70%)}
@media(min-width:761px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
'''
    html=html.replace('</style>',css+'</style>',1).replace('1 信息箱 · 2 New API · 3 博客','1 信息箱 · 2 New API · 3 博客 · 4 活动')
    for route in ['/inbox/','/newapi','/blog']:
        if f'href="{route}"' not in html:raise RuntimeError('Existing link lost')
    return html

def publish():
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [NGINX,PORTAL,SOURCE_PORTAL]}
    for p in [NGINX,PORTAL,SOURCE_PORTAL]:backup(p)
    snippet='''location = /events { return 308 /events/; }
location ^~ /events/ {
    proxy_pass http://127.0.0.1:8093;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 30s;
    client_max_body_size 32k;
    access_log off;
}
'''
    write('/etc/nginx/toolbox/events.conf',snippet)
    original=NGINX.read_text();anchor='    include /etc/nginx/toolbox/inbox.conf;'
    if 'include /etc/nginx/toolbox/events.conf;' not in original:
        if anchor not in original:raise RuntimeError('Nginx anchor missing')
        write(NGINX,original.replace(anchor,anchor+'\n    include /etc/nginx/toolbox/events.conf;'))
    try:run('nginx','-t')
    except Exception:write(NGINX,original);raise
    for p in [PORTAL,SOURCE_PORTAL]:write(p,patched_portal(p.read_text()))
    os.chown(SOURCE_PORTAL,1000,1001)
    run('systemctl','reload','nginx')
    report={'before':before,'after':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [NGINX,PORTAL,SOURCE_PORTAL]},'routes_preserved':['/inbox/','/newapi','/blog'],'new_route':'/events/'}
    write(ROOT/'artifacts/publication.json',json.dumps(report,indent=2));os.chown(ROOT/'artifacts/publication.json',1000,1001)

def rollback():
    # Restore only files backed up by this deployment. Check concurrent edits first.
    report=json.loads((ROOT/'artifacts/publication.json').read_text())
    for path,expected in report['after'].items():
        p=Path(path)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise RuntimeError(f'{p} changed since publication; reconcile before restoring')
    for path in report['before']:
        p=Path(path);shutil.copy2(BACKUP/str(p).lstrip('/').replace('/','__'),p)
    run('nginx','-t');run('systemctl','reload','nginx')
    run('systemctl','disable','--now','shenzhen-events-collect.timer','shenzhen-events-analyze.timer','shenzhen-events.service')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['services','publish','rollback']);args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run with sudo; installer never touches other app services')
    {'services':services,'publish':publish,'rollback':rollback}[args.action]()
