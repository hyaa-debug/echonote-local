from __future__ import annotations
import argparse,json,logging,os,socket,threading,webbrowser
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.server import LocalServer

def instance_lock(root):
    f=(root/'instance.lock').open('a+b');f.seek(0)
    if os.name=='nt':
        import msvcrt
        try:
            if f.read(1)==b'':f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:f.close();return None
    else:
        import fcntl
        try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:f.close();return None
    return f

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765')));parser.add_argument('--no-browser',action='store_true');parser.add_argument('--data',default=str(Path(__file__).parent/'data'));args=parser.parse_args()
    root=Path(args.data).resolve();(root/'logs').mkdir(parents=True,exist_ok=True)
    lock=instance_lock(root)
    if lock is None:
        try:
            url=json.loads((root/'instance.json').read_text())['url']
            print('EchoNote is already running: '+url)
            if not args.no_browser:webbrowser.open(url)
        except (OSError,ValueError,KeyError):print('EchoNote is already starting. Wait a moment and retry.')
        return
    logging.basicConfig(level=logging.INFO,handlers=[RotatingFileHandler(root/'logs'/'app.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8'),logging.StreamHandler()],format='%(asctime)s %(levelname)s %(message)s')
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','180');os.environ.setdefault('HF_HUB_ETAG_TIMEOUT','30')
    server=None
    for port in range(args.port,args.port+20):
        with socket.socket() as sock:
            try:sock.bind(('127.0.0.1',port))
            except OSError:continue
        try:server=LocalServer(('127.0.0.1',port),root);break
        except OSError:continue
    if server is None:raise SystemExit('No free local port. Close another EchoNote window and retry.')
    url=f'http://127.0.0.1:{server.server_port}'
    (root/'instance.json').write_text(json.dumps({'url':url}),encoding='utf-8')
    print('\nEchoNote Local: '+url+'\nKeep this window open. Press Ctrl+C to stop.\n',flush=True)
    if not args.no_browser:threading.Timer(1,lambda:webbrowser.open(url)).start()
    try:server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:pass
    finally:server.server_close();lock.close()

if __name__=='__main__':main()
