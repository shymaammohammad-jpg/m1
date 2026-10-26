"""Two local synthetic structured requests; never reads or uploads contracts."""
from pathlib import Path
import json
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.ai_provider import AIClient, AIProviderError, AISettingsStore


def main():
    root = Path(os.environ.get('AUDIT_DATA_DIR') or Path(__file__).resolve().parents[1] / 'data')
    try:
        settings = AISettingsStore(root).settings_snapshot()
        if settings['provider'] != 'ollama':
            print('اختر Ollama المحلي في إعدادات رقيب أولاً. لم يُرسل أي طلب.')
            return 1
        client = AIClient(settings, max_attempts=1)
        print('قياس محلي بنص اصطناعي؛ لا تُقرأ ملفات العقود ولا يُنزّل نموذج.')
        print('النموذج:', settings['model'])
        schema = {'type': 'object', 'properties': {'contract_number': {'type': 'string'}},
                  'required': ['contract_number'], 'additionalProperties': False}
        for number in (1, 2):
            started = time.perf_counter()
            answer = client.complete('استخرج رقم العقد فقط بصيغة JSON حسب المخطط.',
                {'text': 'وثيقة اختبار وهمية. رقم العقد TEST-2026-001. مدة التنفيذ ثلاثون يوماً.'},
                schema, task='local_benchmark')
            elapsed = time.perf_counter() - started
            metrics = client.last_metrics
            duration = metrics.get('eval_duration', 0) / 1e9
            speed = metrics.get('eval_count', 0) / duration if duration else None
            print(json.dumps({'run': number, 'seconds': round(elapsed, 2),
                'load_seconds': round(metrics.get('load_duration', 0) / 1e9, 2),
                'tokens_per_second': round(speed, 2) if speed is not None else None,
                'synthetic_answer_correct': answer['contract_number'] == 'TEST-2026-001'}, ensure_ascii=False))
        print('هذا قياس قصير للاتصال والتوليد، وليس زمناً لتدقيق عقد أو اختبار دقة قانونية.')
        return 0
    except AIProviderError as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
