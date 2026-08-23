import json
import urllib.error
import urllib.request

# OpenAI-compatible chat-completions providers. They all speak the same
# /chat/completions protocol; only the endpoint and default model differ.
# `base_url` already includes any path prefix (e.g. /v1); '/chat/completions'
# is appended by translate().
PROVIDERS = {
    'deepseek':   {'base_url': 'https://api.deepseek.com',       'model': 'deepseek-chat'},
    'openai':     {'base_url': 'https://api.openai.com/v1',      'model': 'gpt-4o-mini'},
    'moonshot':   {'base_url': 'https://api.moonshot.cn/v1',     'model': 'moonshot-v1-8k'},
    'openrouter': {'base_url': 'https://openrouter.ai/api/v1',   'model': 'openai/gpt-4o-mini'},
    'groq':       {'base_url': 'https://api.groq.com/openai/v1', 'model': 'llama-3.3-70b-versatile'},
    'ollama':     {'base_url': 'http://localhost:11434/v1',      'model': 'qwen2.5:7b'},
    'tencent':    {'base_url': 'https://tokenhub.tencentmaas.com/v1', 'model': 'hy3'},
    'custom':     {},  # user supplies base_url + model themselves
}

DEFAULTS = {
    'provider': 'deepseek',
    'model': 'deepseek-chat',
    'base_url': 'https://api.deepseek.com',
    'prompt': '將以下日文翻譯成台灣繁體中文，只輸出譯文，不要解釋。',
}

# providers that can run without an API key (local / self-hosted)
_NO_KEY = {'ollama'}


def resolve_config(cfg):
    """Merge the stored translate config with provider defaults.

    A stored config may set `provider`, `api_key`, `base_url`, `model`, `prompt`.
    Presets fill in base_url/model when they are not explicitly set, so older
    configs that only carry a DeepSeek key keep working.
    """
    cfg = cfg or {}
    provider = (cfg.get('provider') or DEFAULTS['provider']).strip().lower()
    if provider not in PROVIDERS:
        provider = 'custom'
    preset = PROVIDERS.get(provider) or {}
    return {
        'provider': provider,
        'api_key': (cfg.get('api_key') or '').strip(),
        'base_url': (cfg.get('base_url') or '').strip() or preset.get('base_url') or DEFAULTS['base_url'],
        'model': (cfg.get('model') or '').strip() or preset.get('model') or DEFAULTS['model'],
        'prompt': (cfg.get('prompt') or '').strip() or DEFAULTS['prompt'],
    }


def chat(messages, cfg, temperature=None, timeout=60):
    """Send a chat-completion request. `messages` is a list of {role, content}.
    Returns the assistant message text. Used by translate() and the review
    breakdown feature."""
    c = resolve_config(cfg)
    if not c['api_key'] and c['provider'] not in _NO_KEY:
        raise RuntimeError('未設定 API Key（請在 OCR 設定中填入）')

    url = c['base_url'].rstrip('/') + '/chat/completions'
    payload = {
        'model': c['model'],
        'messages': messages,
        # Some models (e.g. o1/o3) only accept temperature=1 or omit it;
        # only include when explicitly set.
        **(({'temperature': temperature} ) if temperature is not None else {}),
        # Some OpenAI-compatible gateways (e.g. Tencent TokenHub / hy3) stream
        # by default or reject non-streaming responses unless explicitly set.
        # The response parser expects a single JSON object, so force it off to
        # match the verified working curl.
        'stream': False,
    }
    headers = {'Content-Type': 'application/json'}
    if c['api_key']:
        headers['Authorization'] = 'Bearer ' + c['api_key']

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode('utf-8')
        except Exception:
            detail = ''
        raise RuntimeError(f'API 錯誤 {e.code}: {detail[:200]}')
    except Exception as e:
        raise RuntimeError(f'API 請求失敗: {e}')

    try:
        return data['choices'][0]['message']['content'].strip()
    except Exception:
        raise RuntimeError('API 回應格式異常')


def translate(text, cfg):
    """Translate `text` via an OpenAI-compatible chat API. `cfg` holds provider settings."""
    c = resolve_config(cfg)
    return chat([
        {'role': 'system', 'content': c['prompt']},
        {'role': 'user', 'content': text},
    ], cfg)
