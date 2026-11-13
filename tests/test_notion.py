import uuid

import pytest

from app import notion
from app.store import Store


def test_notion_sync_recovers_and_updates_one_page(tmp_path, monkeypatch):
    store = Store(tmp_path)
    note = store.create("测试记录", text="原文", summary="摘要")
    source, page, database = (str(uuid.uuid4()) for _ in range(3))
    drafts = []
    writes = []
    fail_once = True

    def request(token, method, path, body=None):
        nonlocal fail_once
        assert token == "example"
        if path == "databases/" + database:
            return {"data_sources": [{"id": source}]}
        if path == "data_sources/" + source:
            return {"properties": {"名称": {"type": "title"}}}
        if path.endswith("/query"):
            return {"results": drafts.copy()}
        if path == "pages":
            drafts.append({"id": page})
            if fail_once:
                fail_once = False
                raise ValueError("模拟服务创建页面后连接中断")
        writes.append((method, path, body))
        return {"id": page}

    monkeypatch.setattr(notion, "request", request)
    notion.configure(store, {"token": "example", "url": "https://www.notion.so/" + database + "?v=abc"})
    with pytest.raises(ValueError, match="连接中断"):
        notion.sync(store, note)
    assert notion.sync(store, note)["url"].endswith(uuid.UUID(page).hex)
    assert len(drafts) == 1
    assert "摘要" in writes[0][2]["replace_content"]["new_str"]
    previous = len(writes)
    notion.sync(store, note)
    assert len(writes) == previous
    store.update(note["id"], chat=[{"question": "何时完成？", "answer": "周五。"}])
    notion.sync(store, store.get(note["id"]))
    assert writes[-2][1] == "pages/" + page + "/markdown"
    assert "周五。" in writes[-2][2]["replace_content"]["new_str"]
    assert len(drafts) == 1
