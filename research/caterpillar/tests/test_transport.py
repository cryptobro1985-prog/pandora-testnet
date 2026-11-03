"""Local HTTP/archive and WebSocket wire integration; no exchange or production access."""
import asyncio
from datetime import datetime, timezone
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from caterpillar.engine import ResearchEngine
from caterpillar.model import Config
from caterpillar.output import Output
from caterpillar.realtime import realtime
from caterpillar.sources import Archives


class WireTests(unittest.TestCase):
    def test_archive_download_and_verified_cache_over_local_http(self):
        day = datetime(2024, 1, 1, tzinfo=timezone.utc)
        content = gzip.compress(("timestamp,symbol,side,size,price,trdMatchID\n"
                                 f"{day.timestamp()},ZECUSDT,Buy,2,100,id1\n").encode())
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp, patch("caterpillar.sources.ARCHIVE_ROOT", f"http://127.0.0.1:{server.server_port}"):
                source = Archives(tmp)
                rows, meta = source.trades("ZEC", day)
                self.assertEqual(list(rows)[0].quantity, 2)
                self.assertEqual(meta["bytes"], len(content))
                rows, _ = source.trades("ZEC", day)
                self.assertEqual(len(list(rows)), 1)
                self.assertEqual(len(requests), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(3)

    def test_real_websocket_wire_uses_same_ingress(self):
        from aiohttp import web
        ready = threading.Event()
        stop = threading.Event()
        address = []
        errors = []
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            message = await ws.receive_json()
            if message["args"] != ["publicTrade.ZECUSDT"]:
                errors.append("bad subscription")
            await ws.send_json({"op": "subscribe", "success": True})
            now = int(time.time()*1000)
            await ws.send_json({"topic": "publicTrade.ZECUSDT", "data": [
                {"T": now+i, "s": "ZECUSDT", "p": str(100+i/100), "v": "1", "S": "Buy", "i": str(i)}
                for i in range(32)]})
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT and json.loads(msg.data).get("op") == "ping":
                    await ws.send_json({"op": "pong"})
            return ws
        async def serve():
            app = web.Application(); app.router.add_get("/", handler)
            runner = web.AppRunner(app); await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
            address.append(site._server.sockets[0].getsockname()[1]); ready.set()
            while not stop.is_set(): await asyncio.sleep(.01)
            await runner.cleanup()
        thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True); thread.start()
        self.assertTrue(ready.wait(5))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfg = Config(block_trades=16)
                out = Output(Path(tmp)/"run", cfg, ("ZEC",), "local_wire_test")
                engine = ResearchEngine(out, cfg, ("ZEC",))
                with patch("caterpillar.realtime.WS_URL", f"ws://127.0.0.1:{address[0]}/"), patch("caterpillar.realtime.proxy_options", return_value={"http_no_proxy": ["127.0.0.1"]}):
                    status = realtime(engine, duration=1.3, reorder_seconds=0, max_lag_seconds=15)
                engine.finish(status)
                self.assertEqual(status, "completed")
                self.assertEqual(engine.states["ZEC"].seq, 32)
                self.assertEqual(engine.profiles["ZEC"].counts["flow_blocks"], 2)
                self.assertFalse(errors)
        finally:
            stop.set(); thread.join(5)


if __name__ == "__main__": unittest.main()
