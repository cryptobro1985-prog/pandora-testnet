"""Route the pinned HyperData sidecar's public info calls through our shared budget."""
import aiohttp
from urllib.parse import urlsplit


def routed_url(url):
    parsed=urlsplit(str(url))
    if parsed.hostname == 'api.hyperliquid.xyz' and parsed.path == '/info':
        return 'http://127.0.0.1:8421/info'
    return url


def main():
    original=aiohttp.ClientSession._request
    async def budgeted_request(self, method, url, **kwargs):
        return await original(self, method, routed_url(url), **kwargs)
    aiohttp.ClientSession._request=budgeted_request
    from hyperdata_terminal.cli import main as run
    run(['api','--port','8420'])


if __name__=='__main__':
    main()
