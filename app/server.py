from __future__ import annotations
import json, logging, mimetypes, os, re, secrets, sqlite3, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from . import notion
from .store import Store
from .engine import Engines
from .tasks import Tasks

WEB=Path(__file__).parent/'web'
MAX_UPLOAD=2*1024**3
DEFAULT_CONFIG={'asr_model':'small','ai_model':'qwen2.5:3b'}

def srt_time(seconds):
    ms=max(0,round(seconds*1000));h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def render_export(note,fmt):
    if fmt=='srt':
        if not note['segments']: raise ValueError('这条记录没有带时间戳的转写，无法导出字幕。')
        return '\n\n'.join(f'{i}\n{srt_time(s["start"])} --> {srt_time(s["end"])}\n{s["text"]}' for i,s in enumerate(note['segments'],1))+'\n'
    if fmt=='txt': return note['text']
    return '# '+note['title']+'\n\n## 摘要\n\n'+(note['summary'] or '尚未生成')+'\n\n## 原文\n\n'+note['text']+'\n'

class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,root,engine=None):
        self.store=Store(Path(root));self.token=secrets.token_urlsafe(32)
        config_file=Path(root)/'config.json'
        try: config={**DEFAULT_CONFIG,**json.loads(config_file.read_text('utf-8'))}
        except (FileNotFoundError,ValueError):config=DEFAULT_CONFIG.copy()
        self.engine=engine or Engines(Path(root),config)
        self.tasks=Tasks(self.store,self.engine)
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='EchoNoteLocal/1.0'
    def log_message(self,fmt,*args):logging.info(fmt,*args)
    def send(self,status=200,data=None,ctype='application/json; charset=utf-8',headers=None):
        body=json.dumps(data,ensure_ascii=False).encode() if ctype.startswith('application/json') else (data.encode() if isinstance(data,str) else data or b'')
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def json_body(self):
        length=int(self.headers.get('Content-Length',0))
        if not 0<=length<=3_000_000: raise ValueError('文字内容过大，请分段导入。')
        return json.loads(self.rfile.read(length) or b'{}')
    def check(self,write=False):
        # Loopback binding + Host validation block remote pages and DNS rebinding.
        host=self.headers.get('Host','').split(':')[0].lower()
        if host not in ('localhost','127.0.0.1'):
            self.send(403,{'error':'仅允许本机访问'});return False
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'):
            self.send(403,{'error':'不允许此来源'});return False
        if write and not secrets.compare_digest(self.headers.get('X-EchoNote-Token',''),self.server.token):
            self.send(403,{'error':'页面已过期，请刷新后重试'});return False
        return True
    def do_GET(self):
        if not self.check():return
        try:self.get()
        except (BrokenPipeError,ConnectionResetError):pass
        except ValueError as e:self.send(400,{'error':str(e)})
        except Exception:
            logging.exception('GET error');self.send(500,{'error':'读取失败，请查看日志。'})
    def get(self):
        path=urlparse(self.path).path;store=self.server.store
        if path=='/api/health':return self.send(data={'app':'echonote-local','version':'1.0'})
        if path=='/api/session':return self.send(data={'token':self.server.token})
        if path=='/api/status':return self.send(data={**self.server.engine.available(),'jobs':store.active_jobs(),'data_path':str(store.root)})
        if path=='/api/notes':return self.send(data=store.list())
        if re.fullmatch('/api/jobs/[a-f0-9]{32}',path):
            job=store.job(path.rsplit('/',1)[-1]);return self.send(200 if job else 404,job or {'error':'任务不存在'})
        m=re.fullmatch('/api/notes/([a-f0-9]{32})(?:/(media|export))?',path)
        if m:
            note=store.get(m[1])
            if not note:return self.send(404,{'error':'笔记不存在'})
            if m[2]=='media':return self.media(note)
            if m[2]=='export':
                fmt=parse_qs(urlparse(self.path).query).get('format',['md'])[0]
                if fmt not in ('md','txt','srt'):raise ValueError('不支持此导出格式')
                data=render_export(note,fmt)
                return self.send(data=data,ctype='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="EchoNote-{note["id"][:8]}.{fmt}"'})
            return self.send(data=note)
        if path.startswith('/api/'):return self.send(404,{'error':'接口不存在'})
        static={'/':'index.html','/style.css':'style.css','/app.js':'app.js'}
        file=static.get(path)
        if file:
            return self.send(data=(WEB/file).read_bytes(),ctype=mimetypes.guess_type(file)[0]+'; charset=utf-8',headers={'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"})
        return self.send(404,{'error':'页面不存在'})
    def media(self,note):
        path=self.server.store.root/'media'/note['media']
        if not note['media'] or not path.is_file():return self.send(404,{'error':'没有录音'})
        size=path.stat().st_size;start,end=0,size-1;status=200
        range_header=self.headers.get('Range')
        if range_header:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
            if not match or not any(match.groups()):return self.send(416,b'',ctype='text/plain',headers={'Content-Range':f'bytes */{size}'})
            if match[1]:
                start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1)
            else:start=max(0,size-int(match[2]))
            if start>=size or start>end:return self.send(416,b'',ctype='text/plain',headers={'Content-Range':f'bytes */{size}'})
            status=206
        self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining>0:
                chunk=f.read(min(1024*1024,remaining))
                if not chunk:break
                self.wfile.write(chunk);remaining-=len(chunk)
    def do_POST(self):self.mutate()
    def do_PATCH(self):self.mutate()
    def mutate(self):
        if not self.check(write=True):return
        try:self.write()
        except ValueError as e:self.send(400,{'error':str(e)})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            logging.exception('Mutation error');self.send(500,{'error':'操作未完成，请重试；详细原因已写入日志。'})
    def write(self):
        path=urlparse(self.path).path;store=self.server.store
        if path=='/api/upload' and self.command=='POST':
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<=MAX_UPLOAD:raise ValueError('请选择 2 GB 以内的文件。')
            params=parse_qs(urlparse(self.path).query);name=params.get('filename',['录音'])[0]
            mode=valid_mode(params.get('mode',['general'])[0]);language=valid_language(params.get('language',['auto'])[0])
            suffix=Path(name).suffix.lower()
            if suffix not in {'.mp3','.m4a','.wav','.mp4','.webm','.ogg','.flac','.aac','.mov','.mkv'}:raise ValueError('请导入音频或视频文件。')
            media=uuid.uuid4().hex+suffix;dest=store.root/'media'/media
            try:
                self.connection.settimeout(120)
                with dest.open('wb') as f:
                    remaining=length
                    while remaining:
                        chunk=self.rfile.read(min(1024*1024,remaining))
                        if not chunk:raise ValueError('文件传入未完成，请重新导入。')
                        f.write(chunk);remaining-=len(chunk)
            except BaseException:
                dest.unlink(missing_ok=True);raise
            note=store.create(Path(name).stem,media=media,mode=mode,language=language)
            job=self.server.tasks.submit(note['id'],'process')
            return self.send(201,{'note':note,'job_id':job})
        data=self.json_body()
        if self.command=='POST' and path=='/api/notion/config':
            return self.send(data=notion.configure(store,data))
        match=re.fullmatch('/api/notes/([a-f0-9]{32})/notion',path)
        if self.command=='POST' and match:
            note=store.get(match[1])
            if not note:return self.send(404,{'error':'笔记不存在'})
            return self.send(data=notion.sync(store,note))
        if path=='/api/notes' and self.command=='POST':
            text=str(data.get('text','')).strip()
            if not text:raise ValueError('请先填写内容。')
            note=store.create(str(data.get('title','文字笔记')),text=text,mode=valid_mode(data.get('mode','general')))
            job=self.server.tasks.submit(note['id'],'summary') if data.get('auto_summary',True) else None
            return self.send(201,{'note':note,'job_id':job})
        if path=='/api/prepare' and self.command=='POST':return self.send(202,{'job_id':self.server.tasks.submit('','prepare')})
        m=re.fullmatch('/api/notes/([a-f0-9]{32})(?:/(process|summary|ask))?',path)
        if not m:return self.send(404,{'error':'接口不存在'})
        id=m[1];note=store.get(id)
        if not note:return self.send(404,{'error':'笔记不存在'})
        if self.command=='PATCH' and not m[2]:
            with self.server.tasks.lock:
                if any(j['note_id']==id for j in store.active_jobs()):raise ValueError('处理中暂不能编辑，请等待任务结束。')
                fields={k:str(data[k]) for k in ('title','text') if k in data}
                if 'title' in fields:fields['title']=fields['title'][:160]
                if 'text' in fields and fields['text']!=note['text']:
                    fields.update(segments=[],summary='',chat=[])
                store.update(id,**fields)
            return self.send(data=store.get(id))
        if self.command!='POST' or not m[2]:return self.send(405,{'error':'不支持此操作'})
        options={}
        if m[2]=='ask':
            q=str(data.get('question','')).strip()
            if not q or len(q)>2000:raise ValueError('请输入 1–2000 字的问题。')
            if not note['text'].strip():raise ValueError('没有可供提问的原文。')
            options['question']=q
        job=self.server.tasks.submit(id,m[2],**options)
        return self.send(202,{'job_id':job})

def valid_mode(value):
    if value not in ('general','meeting','interview','study'):raise ValueError('未知整理方式')
    return value

def valid_language(value):
    if value not in ('auto','zh','en','ja','ko'):raise ValueError('未知语言')
    return value
