"""OAuth 同意画面（オーナー確認）

/authorize から保留中の認可要求 ID 付きでリダイレクトされてくる。
オーナーが合言葉（OAUTH_OWNER_PASSWORD、未設定なら MCP_AUTH_TOKEN）を入力し、
CSRF トークンが一致した場合にだけ認可コードを発行して redirect_uri へ戻す。
"""

import html
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from src.oauth_provider import ConsentError, InMemoryOAuthProvider, PendingAuthorization

CONSENT_PATH = "/oauth/consent"

# 同意画面は機密操作なので、キャッシュ・埋め込み・Referer 送出を禁止する
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # form-action は付けない（承認後の外部 redirect_uri への遷移をブラウザが遮断するため）
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    ),
}

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Authorize access - Printify MCP Server</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #f6f6f4; color: #1d1d1b; margin: 0; }}
main {{ max-width: 440px; margin: 48px auto; padding: 24px; background: #fff;
        border: 1px solid #ddd; border-radius: 8px; }}
h1 {{ font-size: 1.2rem; margin-top: 0; }}
dl {{ font-size: 0.9rem; }} dt {{ font-weight: 600; margin-top: 8px; }}
dd {{ margin: 2px 0 0; word-break: break-all; }}
label {{ display: block; margin-top: 16px; font-weight: 600; }}
input[type=password] {{ width: 100%; box-sizing: border-box; padding: 8px; margin-top: 4px; }}
.actions {{ display: flex; gap: 8px; margin-top: 16px; }}
button {{ padding: 8px 16px; cursor: pointer; }}
.error {{ color: #a40000; font-weight: 600; }}
.warn {{ font-size: 0.85rem; color: #555; }}
</style>
</head>
<body>
<main>
<h1>Authorize access to Printify MCP Server</h1>
{error}
<p>An application is requesting full access to this server's Printify tools
(including order submission and product deletion).</p>
<dl>
<dt>Application name (self-declared)</dt><dd>{client_name}</dd>
<dt>Redirects to</dt><dd>{redirect_uri}</dd>
<dt>Redirect host</dt><dd>{redirect_host}</dd>
</dl>
<p class="warn">Approve only if you started this connection yourself just now.</p>
<form method="post" action="{action}">
<input type="hidden" name="req" value="{req}">
<input type="hidden" name="csrf_token" value="{csrf}">
<label for="owner_secret">Owner secret</label>
<input type="password" id="owner_secret" name="owner_secret" autocomplete="current-password"
       autofocus>
<div class="actions">
<button type="submit" name="action" value="approve">Approve</button>
<button type="submit" name="action" value="deny">Deny</button>
</div>
</form>
</main>
</body>
</html>
"""

_MESSAGE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>Authorization error - Printify MCP Server</title></head>
<body><p>{message}</p><p>Start the connection again from your MCP client.</p></body></html>
"""


def _render_form(request_id: str, pending: PendingAuthorization, error: str | None, status: int):
    redirect_uri = str(pending.params.redirect_uri)
    body = _PAGE.format(
        error=f'<p class="error">{html.escape(error)}</p>' if error else "",
        client_name=html.escape(pending.client.client_name or "(not provided)"),
        redirect_uri=html.escape(redirect_uri),
        redirect_host=html.escape(urlparse(redirect_uri).hostname or ""),
        action=CONSENT_PATH,
        req=html.escape(request_id, quote=True),
        csrf=html.escape(pending.csrf_token, quote=True),
    )
    return HTMLResponse(body, status_code=status, headers=_SECURITY_HEADERS)


def _render_message(message: str, status: int) -> Response:
    return HTMLResponse(
        _MESSAGE_PAGE.format(message=html.escape(message)),
        status_code=status,
        headers=_SECURITY_HEADERS,
    )


def make_consent_endpoint(provider: InMemoryOAuthProvider):
    """同意画面の Starlette エンドポイント（GET: フォーム表示 / POST: 承認・拒否）を作る"""

    async def consent(request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("req", "")
            pending = provider.get_pending(request_id)
            if pending is None:
                return _render_message("This authorization request is invalid or has expired.", 400)
            return _render_form(request_id, pending, None, 200)

        form = await request.form()
        request_id = str(form.get("req", ""))
        csrf_token = str(form.get("csrf_token", ""))
        try:
            if form.get("action") == "deny":
                location = provider.deny(request_id, csrf_token)
            else:
                location = provider.approve(
                    request_id, csrf_token, str(form.get("owner_secret", ""))
                )
        except ConsentError as e:
            pending = provider.get_pending(request_id)
            if e.status_code == 401 and pending is not None:
                # 合言葉違い: 残り回数があればフォームを再表示する
                return _render_form(request_id, pending, e.message, 401)
            return _render_message(e.message, e.status_code)

        return RedirectResponse(location, status_code=303, headers={"Cache-Control": "no-store"})

    return consent
