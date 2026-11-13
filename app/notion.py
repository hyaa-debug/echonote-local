"""Manual, text-only export to a user-selected Notion database."""
import hashlib
import json
import re
import threading
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

lock = threading.Lock()


def request(token, method, path, body=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    if payload and len(payload) > 490000:
        raise ValueError('本条文字超过 Notion 单次写入大小，请分成较短记录。')
    req = Request('https://api.notion.com/v1/' + path, data=payload, method=method,
                  headers={'Authorization': 'Bearer ' + token, 'Notion-Version': '2026-03-11',
                           'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=45) as response:
            return json.load(response)
    except HTTPError as exc:
        messages = {401: '密钥无效，请重新配置。', 403: '请开启读取、插入和更新内容权限。',
                    404: '找不到目标。请将数据库授权给 EchoNote，并复制数据库本身的链接。',
                    429: 'Notion 请求过多，请稍后再试。', 400: 'Notion 无法接受这次写入，请检查数据库链接、内容长度和必填属性。'}
        raise ValueError(messages.get(exc.code, f'Notion 暂未完成请求（{exc.code}），请稍后重试。')) from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('连接 Notion 失败，请检查网络后重试。') from None


def database_id(value):
    path = urlsplit(value.strip()).path.rstrip('/').split('/')[-1]
    match = re.search(r'([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$', path)
    if not match:
        raise ValueError('请粘贴数据库整页链接。')
    return str(uuid.UUID(match[1]))


def configure(store, data):
    key = data.get('token', '').strip()
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise ValueError('请填写有效的内部连接密钥。')
    db = request(key, 'GET', 'databases/' + database_id(data.get('url', '')))
    sources = db.get('data_sources', [])
    if len(sources) != 1:
        raise ValueError('请选择只包含一个数据源的数据库，或新建一个空白数据库。')
    source = sources[0]['id']
    props = request(key, 'GET', 'data_sources/' + source)['properties']
    title = next(name for name, prop in props.items() if prop['type'] == 'title')
    with lock, store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS notion_config (id INTEGER PRIMARY KEY, token TEXT, source TEXT, title TEXT)')
        c.execute('INSERT OR REPLACE INTO notion_config VALUES(1,?,?,?)', (key, source, title))
    return {'ok': True}


def sync(store, note):
    if not note['text'].strip():
        raise ValueError('请先完成转写或填写原文。')
    content = '## 摘要\n\n' + (note['summary'] or '尚未生成摘要') + '\n\n## 完整原文\n\n' + note['text']
    if note['chat']:
        content += '\n\n## 记录问答\n\n' + '\n\n'.join('### '+x['question']+'\n\n'+x['answer'] for x in note['chat'])
    title = note['title'] or '未命名记录'
    digest = hashlib.sha256(json.dumps([title, content]).encode()).hexdigest()
    with lock, store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='notion_config'").fetchone():
            raise ValueError('请先点「连接设置」，填写密钥和数据库链接。')
        key, source, prop = c.execute('SELECT token,source,title FROM notion_config WHERE id=1').fetchone()
        c.execute('CREATE TABLE IF NOT EXISTS notion_pages (note TEXT, source TEXT, page TEXT, digest TEXT, PRIMARY KEY(note,source))')
        row = c.execute('SELECT page,digest FROM notion_pages WHERE note=? AND source=?', (note['id'],source)).fetchone()
        marker = 'EchoNote-'+note['id']
        def properties(name):
            return {prop: {'title':[{'text':{'content':name}}]}}
        if row:
            page, previous = row
        else:
            # Recover a created draft if the connection failed before its ID was saved.
            query = {'filter':{'property':prop,'title':{'equals':marker}}}
            matches = request(key,'POST','data_sources/'+source+'/query',query)['results']
            draft = matches[0] if matches else request(key,'POST','pages',{
                'parent':{'type':'data_source_id','data_source_id':source}, 'properties':properties(marker)})
            page, previous = draft['id'], ''
            c.execute('INSERT INTO notion_pages VALUES(?,?,?,?)',(note['id'],source,page,''))
            c.commit()
        if previous != digest:
            request(key,'PATCH','pages/'+page+'/markdown',{'type':'replace_content','replace_content':{'new_str':content}})
            request(key,'PATCH','pages/'+page,{'properties':properties(title)})
            c.execute('UPDATE notion_pages SET digest=? WHERE note=? AND source=?',(digest,note['id'],source))
        return {'url':'https://www.notion.so/'+uuid.UUID(page).hex}
