with open('app/model_rotation.py','r',encoding='utf-8') as f: content=f.read()
logger_code = '''def _log_event(event_code: str, group_code: str, detail: str) -> None:
    try:
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f'{timestamp} | {event_code} | {group_code} | {detail}
'
        with open('C:/Users/Rezvan/work/codex/work-with-LLMs/data/rotation.log', 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
'''
content = content.replace('def select_next_model() -> dict[str, Any] | None:', logger_code + 'def select_next_model() -> dict[str, Any] | None:')
with open('app/model_rotation.py','w',encoding='utf-8') as f: f.write(content)
print('logger inserted')

