"""Unofficial community provider for direct Mistral Vibe access."""
from providers.base import ProviderProfile

from agent import reasoning_effort as re_

MODEL = 'mistral-vibe-cli-latest'
BASE = 'https://api.mistral.ai/v1'
SLUG = 'mistral-vibe'
UA = 'hermes-mistral-vibe/1.0'

CONSOLE = 'https://console.mistral.ai'
_CATALOG_TTL = 3600
_catalog_cache = {}

# Reasoning vocabularies live-verified on the relay (2026-10-03): the top-level
# ``reasoning_effort`` field is validated per model — HTTP 400 code 3051 lists
# the supported set. GLM-5.3/5/latest accept low/high/max ('medium' 400s);
# GLM-5.2 additionally accepts 'medium'. 'none' cannot disable thinking on this
# wire, and the native z.ai scale differs (there GLM-5.3 takes 'medium'), so the
# plugin declares its own relay-verified sets instead of reusing core constants.
_VIBE_GLM_EFFORTS = ('low', 'high', 'max')
_VIBE_GLM_52_EFFORTS = ('low', 'medium', 'high', 'max')
_GLM_5_3_TOKENS = ('glm-5.3', 'glm-5-3', 'glm-5p3')
_GLM_5_2_TOKENS = ('glm-5.2', 'glm-5-2', 'glm-5p2')
_GLM_XHIGH_TO_MAX = {'xhigh': 'max'}  # vendor top-tier mapping, mirrors GLM53_OVERRIDES


def _glm_effort_set(model):
    """Relay-verified ``reasoning_effort`` vocabulary for *model*, or None.

    Fail-closed: any model whose GLM version was not verified on the relay
    returns None and keeps the relay's own default effort.
    """
    name = (model or '').strip().lower()
    if any(token in name for token in _GLM_5_3_TOKENS):
        return _VIBE_GLM_EFFORTS
    if any(token in name for token in _GLM_5_2_TOKENS):
        return _VIBE_GLM_52_EFFORTS
    if 'glm-5' in name or 'glm-latest' in name:
        # Verified on zai-glm-5 and zai-glm-latest; -900k style suffixes ride along.
        # Future 5.x point releases land here too — if the relay ever 400s the
        # level, Hermes' session-sticky rejection ladder drops the field.
        return _VIBE_GLM_EFFORTS
    return None


def _key_fingerprint(key):
    import hashlib
    return hashlib.blake2b(key.encode(), digest_size=16).hexdigest()


def _catalog_scope(key):
    from hermes_constants import get_hermes_home
    return (SLUG, str(get_hermes_home().resolve()), _key_fingerprint(key))


def _cached_catalog(key):
    import time
    row = _catalog_cache.get(_catalog_scope(key))
    if row and time.monotonic() - row[0] < _CATALOG_TTL:
        return list(row[1])
    return None


def _store_catalog(key, models):
    import time
    _catalog_cache[_catalog_scope(key)] = (time.monotonic(), tuple(models))


def dedicated_key():
    import os
    from hermes_cli.auth import read_credential_pool
    key = os.environ.get('MISTRAL_VIBE_API_KEY', '').strip()
    if key:
        return key
    for row in read_credential_pool(SLUG):
        if row.get('auth_type') == 'api_key' and row.get('access_token'):
            return row['access_token']
    return ''


def _json_request(http, method, url, **kwargs):
    response = http.request(method, url, **kwargs)
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f'Browser sign-in HTTP {response.status_code}; no retry or redirect')
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError('Invalid payload')
    return data


def login(*, open_browser):
    import httpx
    try:
        return _login(open_browser)
    except KeyboardInterrupt:
        raise RuntimeError('Browser sign-in cancelled') from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise RuntimeError('Browser sign-in failed: transport or invalid response') from None


def _login(open_browser):
    import base64, hashlib, secrets, uuid, time, re
    from datetime import datetime
    from urllib.parse import urlsplit
    import httpx
    from agent.credential_pool import PooledCredential, load_pool
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    with httpx.Client(transport=httpx.HTTPTransport(), follow_redirects=False,
                      trust_env=False, timeout=15, headers={'User-Agent': UA}) as http:
        process = _json_request(http, 'POST', CONSOLE + '/api/vibe/sign-in', json={
            'code_challenge':challenge, 'code_challenge_method':'S256'})
        for field in ('sign_in_url', 'poll_url'):
            value = process.get(field, '')
            parsed = urlsplit(value)
            if (parsed.scheme != 'https' or parsed.netloc != 'console.mistral.ai'
                    or parsed.fragment or any(ord(c) < 33 for c in value) or chr(92) in value):
                raise RuntimeError('Unsafe browser or poll URL')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', process.get('process_id', '')):
            raise RuntimeError('Unsafe process identifier')
        expires = datetime.fromisoformat(process['expires_at'].replace('Z', '+00:00'))
        if expires.tzinfo is None:
            raise ValueError('Missing expiry timezone')
        deadline = time.monotonic() + min(300, expires.timestamp() - time.time())
        if time.monotonic() >= deadline:
            raise RuntimeError('Browser sign-in expired')
        open_browser(process['sign_in_url'])
        while time.monotonic() < deadline:
            result = _json_request(http, 'GET', process['poll_url'])
            if result.get('status') == 'completed':
                break
            if result.get('status') != 'pending':
                raise RuntimeError('Browser sign-in denied')
            time.sleep(min(2, max(0, deadline-time.monotonic())))
        else:
            raise RuntimeError('Browser sign-in expired')
        if time.monotonic() >= deadline:
            raise RuntimeError('Browser sign-in expired')
        token = result['exchange_token']
        if not isinstance(token, str) or not token:
            raise ValueError('Missing exchange token')
        key = _json_request(http, 'POST', CONSOLE + '/api/vibe/sign-in/' + process['process_id'] + '/exchange',
            json={'exchange_token':token, 'code_verifier':verifier})['api_key']
        if not isinstance(key, str) or not key.strip():
            raise ValueError('Missing API key')
        identity = _json_request(http, 'GET', CONSOLE + '/api/vibe/whoami', headers={'Authorization':'Bearer ' + key})
    load_pool(SLUG).add_entry(PooledCredential(provider=SLUG, id=uuid.uuid4().hex[:8],
        label='Vibe plan key', auth_type='api_key', priority=0, source='manual',
        access_token=key, base_url=BASE))
    return identity


def auth_handler(action, args):
    import webbrowser
    from agent.credential_pool import load_pool
    if action == 'add':
        def browser(url):
            print('Open this Mistral sign-in URL (do not share it): ' + url)
            if not getattr(args, 'no_browser', False):
                webbrowser.open(url)
        login(open_browser=browser)
        print('Mistral Vibe key stored; subscription billing is NOT guaranteed.')
        return True
    if action == 'status':
        print('mistral-vibe: ' + ('configured (not live-validated)' if dedicated_key() else 'not configured'))
        return True
    if action == 'logout':
        pool = load_pool(SLUG)
        for index in range(len(pool.entries()), 0, -1):
            pool.remove_index(index)
        print('Local Vibe pool cleared. Unset MISTRAL_VIBE_API_KEY separately; remote key is not revoked.')
        return True
    if action == 'refresh':
        raise RuntimeError('No refresh token: run hermes auth add mistral-vibe again')
    return False


class GuardedClient:
    """Validation is deferred: Hermes swallows create_client hook exceptions."""
    # Preserve this guard instead of rebuilding an unguarded AsyncOpenAI client.
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, **kwargs):
        from types import SimpleNamespace
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._create(**kwargs)
        return self._async_create(**kwargs)

    async def _async_create(self, **kwargs):
        import asyncio
        result = await asyncio.to_thread(self._create, **kwargs)
        if not kwargs.get('stream'):
            return result
        async def chunks():
            sentinel = object()
            iterator = iter(result)
            try:
                while True:
                    item = await asyncio.to_thread(next, iterator, sentinel)
                    if item is sentinel:
                        break
                    yield item
            finally:
                await asyncio.to_thread(result.close)
        return chunks()

    def _create(self, **kwargs):
        import httpx
        from openai import OpenAI
        # Hermes auxiliary structured-output helpers put this SDK field in
        # extra_body. Promote only this allowlisted field; never let extra_body
        # replace model/messages or route/auth metadata.
        body = kwargs.get('extra_body') or {}
        if isinstance(body, dict) and set(body) <= {'response_format'}:
            kwargs.pop('extra_body', None)
            if 'response_format' in body:
                kwargs.setdefault('response_format', body['response_format'])
        if (str(self.kwargs.get('base_url') or BASE).rstrip('/') != BASE
                or any(kwargs.get(k) for k in ('extra_headers', 'extra_body', 'extra_query'))):
            raise RuntimeError('Provider restricted to its fixed origin and request headers')
        key = dedicated_key()
        if not key:
            raise RuntimeError('Missing dedicated MISTRAL_VIBE_API_KEY; run hermes auth add mistral-vibe')
        requested_model = kwargs.get('model')
        if requested_model != MODEL:
            catalog = profile.fetch_models(base_url=BASE)
            if not catalog or requested_model not in catalog:
                raise RuntimeError('Model is not in the current dedicated key catalog')
        key_fingerprint = _key_fingerprint(key)
        if getattr(self, '_client_key_fingerprint', None) != key_fingerprint:
            if hasattr(self, '_client'):
                self._client.close()
            self._client = OpenAI(api_key=key, base_url=BASE, max_retries=0,
                default_headers={'User-Agent': UA}, timeout=60,
                http_client=httpx.Client(transport=httpx.HTTPTransport(),
                    follow_redirects=False, trust_env=False, timeout=60))
            self._client_key_fingerprint = key_fingerprint
        return self._client.chat.completions.create(**kwargs)

    def close(self):
        if hasattr(self, '_client'):
            self._client.close()



class VibeProfile(ProviderProfile):
    def build_api_kwargs_extras(self, *, reasoning_config=None, model=None, **context):
        """Translate Hermes reasoning config to the relay's top-level ``reasoning_effort``.

        The wire field is top-level only: the guarded client rejects ``extra_body``.
        'none'/disabled emits nothing (the relay cannot disable thinking), and an
        unverified model keeps the relay's own default effort (fail-closed).
        """
        extra_body, top_level = {}, {}
        efforts = _glm_effort_set(model)
        if efforts is None:
            return extra_body, top_level
        effort = re_.requested_effort(reasoning_config)
        if effort in (None, 'none'):
            return extra_body, top_level
        clamped = re_.clamp_effort(effort, efforts, _GLM_XHIGH_TO_MAX)
        if clamped in efforts:
            top_level['reasoning_effort'] = clamped
        return extra_body, top_level

    def fetch_models(self, **kwargs):
        import httpx
        requested_base = str(kwargs.get('base_url') or BASE).rstrip('/')
        if requested_base != BASE:
            return None
        key = dedicated_key()
        if not key:
            return None
        cached = _cached_catalog(key)
        if cached is not None:
            return cached
        try:
            with httpx.Client(transport=httpx.HTTPTransport(), follow_redirects=False,
                    trust_env=False, timeout=8, headers={'Authorization':'Bearer ' + key,
                    'Accept':'application/json', 'User-Agent':UA}) as http:
                response = http.get(BASE + '/models')
                response.raise_for_status()
                data = response.json()
            items = data.get('data') if isinstance(data, dict) else None
            if not isinstance(items, list):
                return None
            models = []
            for item in items:
                if not isinstance(item, dict):
                    return None
                model_id = item.get('id')
                capabilities = item.get('capabilities')
                if (not isinstance(model_id, str) or not model_id.strip()
                        or model_id != model_id.strip()
                        or not isinstance(capabilities, dict)
                        or not isinstance(capabilities.get('completion_chat'), bool)):
                    return None
                if capabilities['completion_chat'] and model_id not in models:
                    models.append(model_id)
            if not models:
                return None
            _store_catalog(key, models)
            return models
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    def create_client(self, **kwargs):
        return GuardedClient(**kwargs)


profile = VibeProfile(
    name=SLUG, display_name='Mistral Vibe',
    description='Unofficial community plugin; subscription coverage not guaranteed',
    auth_type='api_key', auth_handler=auth_handler, env_vars=('MISTRAL_VIBE_API_KEY',),
    base_url=BASE, fallback_models=(MODEL,), default_aux_model=MODEL,
    supports_health_check=False, supports_model_listing=True,
    default_headers={'User-Agent': UA},
)
