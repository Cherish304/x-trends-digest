"""urllib 的小工具：不跟随重定向，避免把 Authorization 头转发到其他地址。"""

import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_no_redirect(req: urllib.request.Request, timeout: float):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)
