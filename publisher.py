import os
import json
import subprocess

from http_utils import request_with_retry

SQUARE_POST_URL = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"
OFFICIAL_SKILL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "skill-src", "skills", "binance", "square-post"
)


class PublishResult:
    def __init__(self, status, detail=None, post_url=None):
        self.status = status  # "published" | "failed" | "unknown"
        self.detail = detail
        self.post_url = post_url


def _find_official_entrypoint():
    if not os.path.isdir(OFFICIAL_SKILL_DIR):
        return None
    for candidate in ("post.py", "post-text.py", "index.js", "post-text.js"):
        path = os.path.join(OFFICIAL_SKILL_DIR, candidate)
        if os.path.exists(path):
            return path
    return None


def _publish_via_official_skill(entrypoint, text, api_key):
    try:
        env = os.environ.copy()
        env["SQUARE_OPENAPI_KEY"] = api_key
        if entrypoint.endswith(".py"):
            cmd = ["python3", entrypoint, "--text", text]
        else:
            cmd = ["node", entrypoint, "--text", text]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if proc.returncode != 0:
            return PublishResult("failed", detail=proc.stderr.strip()[:500])
        out = proc.stdout.strip()
        return PublishResult("published", detail=out, post_url=_extract_url(out))
    except Exception as e:
        return PublishResult("failed", detail=str(e))


def _extract_url(text):
    import re
    match = re.search(r"https?://\S+", text or "")
    return match.group(0) if match else None


def _publish_via_direct_api(text, api_key):
    headers = {
        "X-Square-OpenAPI-Key": api_key,
        "Content-Type": "application/json",
    }
    payload = {"content": text, "type": "text"}
    try:
        resp = request_with_retry("POST", SQUARE_POST_URL, headers=headers, json=payload)
        data = resp.json()
        return PublishResult("published", detail=json.dumps(data)[:500])
    except Exception as e:
        msg = str(e)
        if "504" in msg:
            return PublishResult("unknown", detail=msg)
        return PublishResult("failed", detail=msg)


def post_to_square(text, api_key):
    if not api_key:
        return PublishResult("failed", detail="missing_api_key")

    entrypoint = _find_official_entrypoint()
    if entrypoint:
        return _publish_via_official_skill(entrypoint, text, api_key)
    return _publish_via_direct_api(text, api_key)
