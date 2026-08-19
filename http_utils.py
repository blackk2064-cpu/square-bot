import time
import random
import requests

from config_loader import load_config

_provider_failures = {}
_provider_cooldown_until = {}


def request_with_retry(method, url, **kwargs):
    cfg = load_config()["http"]
    timeout = kwargs.pop("timeout", cfg["timeout_seconds"])
    max_retries = cfg["max_retries"]
    base = cfg["backoff_base_seconds"]

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                sleep_s = base * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_s)
    raise last_exc


def provider_available(name):
    cfg = load_config()["providers"]["circuit_breaker"]
    until = _provider_cooldown_until.get(name)
    if until and time.time() < until:
        return False
    return True


def record_provider_failure(name):
    cfg = load_config()["providers"]["circuit_breaker"]
    _provider_failures[name] = _provider_failures.get(name, 0) + 1
    if _provider_failures[name] >= cfg["failure_threshold"]:
        _provider_cooldown_until[name] = time.time() + cfg["cooldown_minutes"] * 60
        _provider_failures[name] = 0


def record_provider_success(name):
    _provider_failures[name] = 0
