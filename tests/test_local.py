import json,threading,time,urllib.request,urllib.error,wave,io
from pathlib import Path
import pytest
from app.server import LocalServer,render_export
from app.store import Store
from app.engine import split_text,Engines,EngineError

class FakeEngine:
    def available(self):return {'asr_ready':True,'asr_model':'test','ai_model':'test','ai_models':['test']}
    def prepare_asr(self,p):pass
    def prepare_ai(self,p):pass
    def unload(self):pass
    def transcribe(self,path,language,progress,save):
        s=[{'start':0,'end':2,'text':'周五之前完成三条视频。'}];save(s,2);return s,2
    def generate(self,text,mode,question=None,progress=lambda *_:None):
        return '## 根据记录\n\n- 周五之前完成三条视频。'

@pytest.fixture
def client(tmp_path):
    server=LocalServer(('127.0.0.1',0),tmp_path,FakeEngine())
    t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def call(path,method='GET',data=None,headers=None):
        h={'X-EchoNote-Token':server.token,**(headers or {})}
        if isinstance(data,dict):data=json.dumps(data).encode();h['Content-Type']='application/json'
        req=urllib.request.Request(base+path,data=data,method=method,headers=h)
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=5) as r:return r.status,dict(r.headers),r.read()
        except urllib.error.HTTPError as e:return e.code,dict(e.headers),e.read()
    yield server,call
    server.shutdown();server.server_close()

def wait_done(server,job):
    for _ in range(100):
        state=server.store.job(job)
        if state['state'] not in ('queued','running'):return state
        time.sleep(.02)
    raise AssertionError('Task did not finish')

def test_automatic_pipeline_and_range(client):
    server,call=client
    wav=io.BytesIO()
    with wave.open(wav,'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000)
    payload=wav.getvalue()
    code,_,body=call('/api/upload?filename=hello.wav&mode=meeting','POST',payload)
    assert code==201
    result=json.loads(body);id=result['note']['id']
    assert wait_done(server,result['job_id'])['state']=='done'
    n=server.store.get(id)
    assert n['text']=='周五之前完成三条视频。' and '三条视频' in n['summary'] and n['state']=='ready'
    code,h,b=call('/api/notes/'+id+'/media',headers={'Range':'bytes=0-9'})
    assert code==206 and b==payload[:10] and h['Content-Length']=='10'
    code,h,b=call('/api/notes/'+id+'/media',headers={'Range':'bytes=-10'})
    assert code==206 and b==payload[-10:]
    assert call('/api/notes/'+id+'/media',headers={'Range':'bytes=999999-1000000'})[0]==416
    code,_,b=call('/api/notes/'+id+'/export?format=srt');assert code==200 and b'00:00:00,000 --> 00:00:02,000' in b

def test_text_persistence_edit_invalidation_and_ask(client):
    server,call=client
    code,_,b=call('/api/notes','POST',{'title':'笔记','text':'周五之前完成三条视频。'})
    assert code==201
    result=json.loads(b);id=result['note']['id'];assert wait_done(server,result['job_id'])['state']=='done'
    _,_,b=call('/api/notes/'+id+'/ask','POST',{'question':'何时完成？'});assert wait_done(server,json.loads(b)['job_id'])['state']=='done'
    assert server.store.get(id)['chat'][0]['question']=='何时完成？'
    assert call('/api/notes/'+id,'PATCH',{'text':'修改后的原文'})[0]==200
    n=server.store.get(id);assert n['summary']=='' and n['chat']==[] and n['segments']==[]
    other=Store(server.store.root);assert other.get(id)['text']=='修改后的原文'
    assert call('/api/notes/'+id+'/export?format=srt')[0]==400

def test_protect_local_server(client):
    server,call=client
    assert call('/api/notes','POST',{'text':'hello'},headers={'X-EchoNote-Token':'wrong'})[0]==403
    assert call('/api/session',headers={'Origin':'https://example.com'})[0]==403
    assert call('/api/session',headers={'Host':'evil.example'})[0]==403
    assert call('/../../run.py')[0]==404
    assert call('/api/upload?filename=test.exe','POST',b'bad')[0]==400
    assert call('/api/notes','POST',{'text':'hello','mode':'invalid'})[0]==400

def test_interrupted_jobs_are_recoverable(tmp_path):
    s=Store(tmp_path);n=s.create('record',text='已经完成的内容',state='transcribing');j=s.add_job(n['id'],'process')
    s.job_update(j,state='running')
    recovered=Store(tmp_path)
    assert recovered.job(j)['state']=='interrupted'
    assert recovered.get(n['id'])['text']=='已经完成的内容'
    assert recovered.get(n['id'])['state']=='interrupted'

def test_summary_failure_keeps_transcript(client):
    server,call=client
    def fail(*a,**k):raise EngineError('AI 未启动')
    server.engine.generate=fail
    _,_,b=call('/api/notes','POST',{'text':'务必保留原文'})
    d=json.loads(b);assert wait_done(server,d['job_id'])['state']=='error'
    n=server.store.get(d['note']['id'])
    assert n['text']=='务必保留原文' and n['state']=='partial' and n['error']=='AI 未启动'

def test_summary_chunking_no_silent_loss():
    s=('这是测试文本。\n'*3000)
    chunks=split_text(s,6500)
    assert ''.join(chunks)==s
    assert max(map(len,chunks))<=6500

def test_ollama_protocol_and_map_reduce(tmp_path,monkeypatch):
    engine=Engines(tmp_path,{'ai_model':'test'})
    calls=[]
    def request(path,payload=None,timeout=15):
        if path=='/api/tags':return {'models':[{'name':'test'}]}
        calls.append(payload)
        if payload.get('format'):return {'response':json.dumps({'summary':'已整理','key_points':[],'decisions':[],'actions':[],'uncertain':[]})}
        return {'response':'## 概要\n\n- 已根据资料整理。'}
    monkeypatch.setattr(engine,'request',request)
    result=engine.generate('会议记录。\n'*3000,'meeting')
    assert result.startswith('##') and len(calls)>1
    assert all(c['stream'] is False and c['keep_alive']==0 for c in calls)
    assert '<transcript>' in calls[0]['prompt']

def test_active_note_cannot_be_overwritten_or_queued_twice(client):
    server,call=client;entered=threading.Event();release=threading.Event()
    def slow(*a,**k):entered.set();release.wait(3);return '完成'
    server.engine.generate=slow
    _,_,b=call('/api/notes','POST',{'text':'处理中原文'})
    d=json.loads(b);id=d['note']['id'];assert entered.wait(1)
    assert call('/api/notes/'+id,'PATCH',{'text':'冲突修改'})[0]==400
    assert call('/api/notes/'+id+'/summary','POST',{})[0]==400
    release.set();assert wait_done(server,d['job_id'])['state']=='done'
    assert server.store.get(id)['text']=='处理中原文'

def test_action_owners_deadlines_and_quotes_are_grounded(tmp_path,monkeypatch):
    e=Engines(tmp_path,{'ai_model':'test'})
    data={'summary':'测试概要','key_points':[],'decisions':[],'uncertain':[],
          'actions':[{'task':'完成三条视频','owner':'虚构负责人','deadline':'下周一','evidence':'周五之前完成三条视频'},
                     {'task':'虚构任务','owner':'小明','deadline':'明天','evidence':'原文不存在这句话'}]}
    monkeypatch.setattr(e,'request',lambda *a,**k:{'response':json.dumps(data)})
    out=e._summarize('test','会议','周五之前完成三条视频','周五之前完成三条视频')
    assert '负责人：原文未指定' in out and '截止：原文未指定' in out
    assert '虚构负责人' not in out and '下周一' not in out and '虚构任务' not in out
