"""Reliable packaged startup coordination with browser and instance detection."""
import json,os,socket,time,urllib.request,webbrowser
from pathlib import Path
from threading import Timer

from app.core.logging_utils import get_logger,log_event,log_failure

logger=get_logger('deployment.startup')
def port_available(host,port):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        try:sock.bind((host,int(port)));return True
        except OSError:return False
def instance_url(host,port):return f"http://{'127.0.0.1' if host in {'0.0.0.0','::'} else host}:{int(port)}"
def is_running(url,timeout=1.0):
    try:
        with urllib.request.urlopen(url+'/health/live',timeout=timeout) as response:return response.status==200
    except Exception:return False
def choose_port(host,preferred,fallback=None):
    if port_available(host,preferred):return int(preferred)
    if fallback and port_available(host,fallback):return int(fallback)
    raise RuntimeError(f'CBOS cannot start because ports {preferred}'+(f' and {fallback}' if fallback else '')+' are unavailable.')
def acquire_instance(lock_path,url):
    path=Path(lock_path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        try:state=json.loads(path.read_text(encoding='utf-8'))
        except Exception:state={}
        existing=state.get('url') or url
        if is_running(existing):return {'acquired':False,'url':existing,'already_running':True}
        path.unlink(missing_ok=True)
    try:
        handle=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(handle,json.dumps({'pid':os.getpid(),'url':url,'started_at':time.time()}).encode());os.close(handle)
    except FileExistsError:
        if is_running(url):return {'acquired':False,'url':url,'already_running':True}
        raise RuntimeError('Another CBOS startup is already in progress.')
    return {'acquired':True,'url':url,'lock_path':str(path),'already_running':False}
def release_instance(lock_path):Path(lock_path).unlink(missing_ok=True)
def schedule_browser(url,enabled=True,delay=1.5,opener=None):
    if not enabled:return None
    def launch():
        try:(opener or webbrowser.open)(url+'/dashboard/');log_event(logger,'startup_browser_opened',url=url)
        except Exception as exc:log_failure(logger,'startup_browser_failed',error_type=type(exc).__name__)
    timer=Timer(max(0,float(delay)),launch);timer.daemon=True;timer.start();return timer
def startup_plan(host,port,*,fallback_port=None,runtime_directory=None):
    url=instance_url(host,port)
    if is_running(url):return {'start':False,'url':url,'already_running':True,'port':int(port)}
    selected=choose_port(host,port,fallback_port);url=instance_url(host,selected)
    lock=Path(runtime_directory or Path.home()/'.cbos')/'cbos.instance.json';state=acquire_instance(lock,url)
    return {'start':state['acquired'],'url':state['url'],'already_running':state['already_running'],'port':selected,'lock_path':str(lock)}
