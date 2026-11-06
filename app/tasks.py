from __future__ import annotations
import logging, queue, threading
from .engine import EngineError

class Tasks:
    def __init__(self,store,engine):
        self.store=store;self.engine=engine
        self.queue=queue.Queue();self.lock=threading.Lock()
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def submit(self,note_id,kind,**options):
        with self.lock:
            active=self.store.active_jobs()
            if any(j['note_id']==note_id for j in active):
                raise ValueError('这条记录已有任务在进行，请等待结束。')
            job=self.store.add_job(note_id,kind)
            if note_id: self.store.update(note_id,state='queued',error='')
            self.queue.put((job,note_id,kind,options))
            return job
    def run(self):
        while True:
            job,note_id,kind,options=self.queue.get()
            try:
                self.store.job_update(job,state='running',message='正在准备…')
                progress=lambda p,m:self.store.job_update(job,progress=p,message=m)
                if kind=='prepare':
                    self.engine.prepare_asr(progress)
                    self.engine.prepare_ai(progress)
                else:
                    note=self.store.get(note_id)
                    if not note: raise EngineError('找不到这条记录。')
                    if kind=='process':
                        self.store.update(note_id,state='transcribing',error='',summary='',chat=[])
                        if not note['media']: raise EngineError('这条记录没有录音文件。')
                        def save(segments,duration):
                            self.store.update(note_id,text='\n'.join(s['text'] for s in segments),segments=segments,duration=duration)
                        self.engine.transcribe(self.store.root/'media'/note['media'],note['language'],progress,save)
                        note=self.store.get(note_id)
                    if kind in ('process','summary'):
                        if not note['text'].strip(): raise EngineError('没有可总结的文字。')
                        self.store.update(note_id,state='summarizing')
                        result=self.engine.generate(note['text'],note['mode'],progress=progress)
                        self.store.update(note_id,summary=result,state='ready',error='')
                    elif kind=='ask':
                        self.store.update(note_id,state='answering')
                        result=self.engine.generate(note['text'],note['mode'],question=options['question'],progress=progress)
                        chat=self.store.get(note_id)['chat']
                        chat.append({'question':options['question'],'answer':result})
                        self.store.update(note_id,chat=chat,state='ready',error='')
                self.store.job_update(job,state='done',progress=100,message='完成')
            except Exception as e:
                logging.exception('Task %s failed',job)
                if isinstance(e,EngineError): message=str(e)
                else: message='处理未完成：'+str(e)[:250]+ '。已保留文件与成功结果，可重试；详细记录见 data/logs。'
                self.store.job_update(job,state='error',message=message)
                if note_id:
                    note=self.store.get(note_id)
                    state='partial' if note and note['text'].strip() else 'error'
                    self.store.update(note_id,state=state,error=message)
                self.engine.unload()
            finally: self.queue.task_done()
