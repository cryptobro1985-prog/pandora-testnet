"""Offline adapter contract/failure tests; no remote requests or paid inference."""
import copy
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

import requests

from research.hype_local_only.cortex_provider import (
    AdapterConfig, CortexProvider, ProviderError, MAX_RESPONSE_BYTES,
    validate_decision,
)


def decision():
    return {"verdict": "WAIT", "confidence": 0.3, "supporting_relationships": [],
            "contradicting_relationships": ["Book is unavailable"], "missing_live_evidence": ["L50"],
            "summary": "Insufficient independent evidence.", "hypotheses": []}


def envelope(value=None, **kwargs):
    return {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(decision() if value is None else value), **kwargs}}]}


class FakeResponse:
    def __init__(self, body, status=200, headers=None, chunks=None):
        self.status_code = status
        self.body = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.headers = headers or {}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=8192):
        yield from self.chunks if self.chunks is not None else [self.body]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        # Copy to preserve the first request when fallback mutates its body.
        self.calls.append((url, copy.deepcopy(kwargs)))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        config = AdapterConfig.from_env({})
        self.assertEqual(config.backend, "disabled")
        provider = CortexProvider(config, FakeSession())
        self.assertFalse(provider.available)
        with self.assertRaisesRegex(ProviderError, "provider_disabled"):
            provider.generate({})

    def test_openai_requires_explicit_model_and_key(self):
        provider = CortexProvider(AdapterConfig.from_env({"CORTEX_BACKEND": "openai"}), FakeSession())
        self.assertFalse(provider.available)
        self.assertEqual(provider.availability_reason, "missing_model")
        provider = CortexProvider(AdapterConfig.from_env({"CORTEX_BACKEND": "openai", "CORTEX_API_MODEL": "explicit-model"}), FakeSession())
        self.assertEqual(provider.availability_reason, "missing_api_key")

    def test_secret_excluded_from_repr_and_local_adapter(self):
        key = "sentinel-secret"
        config = AdapterConfig.from_env({"CORTEX_BACKEND": "openai", "OPENAI_API_KEY": key})
        self.assertNotIn(key, repr(config))
        local = AdapterConfig.from_env({"CORTEX_BACKEND": "local_llama", "OPENAI_API_KEY": key})
        self.assertEqual(local.api_key, "")

    def test_timeout_bounds(self):
        self.assertEqual(AdapterConfig.from_env({"CORTEX_TIMEOUT_SECONDS": "200"}).timeout_s, 30)
        self.assertEqual(AdapterConfig.from_env({"CORTEX_TIMEOUT_SECONDS": "0"}).timeout_s, 1)
        for value in ("nan", "inf", "oops"):
            with self.assertRaises(ProviderError):
                AdapterConfig.from_env({"CORTEX_TIMEOUT_SECONDS": value})

    def test_local_endpoint_is_loopback_without_credentials_or_paths(self):
        for url in ("https://example.com", "http://localhost@evil.example", "http://127.0.0.1/a",
                    "http://127.0.0.1?x=1", "http://user:secret@127.0.0.1"):
            with self.assertRaisesRegex(ProviderError, "invalid_local_url"):
                AdapterConfig.from_env({"CORTEX_BACKEND": "local_llama", "CORTEX_LOCAL_URL": url})
        for url in ("http://127.0.0.1:8081", "http://localhost:8081", "http://[::1]:8081"):
            self.assertEqual(AdapterConfig.from_env({"CORTEX_BACKEND": "local_llama", "CORTEX_LOCAL_URL": url}).local_url, url)


class ContractTests(unittest.TestCase):
    def test_valid_decision(self):
        self.assertEqual(validate_decision(decision()), decision())

    def test_rejects_extra_or_missing_fields(self):
        for change in ({"leverage": 100}, {"summary": None}, {"confidence": True},
                       {"confidence": math.nan}, {"confidence": 1.01}, {"verdict": "BUY"},
                       {"supporting_relationships": "flow"}, {"missing_live_evidence": ["x"] * 13}):
            obj = decision()
            obj.update(change)
            with self.assertRaises(ProviderError):
                validate_decision(obj)
        obj = decision()
        del obj["hypotheses"]
        with self.assertRaises(ProviderError):
            validate_decision(obj)

    def test_hypothesis_is_strict_and_rejects_targets(self):
        h = {"feature": "rev_flow_30s", "op": "ge", "threshold": 0.4,
             "side": "HIGH", "stage_s": 60, "rationale": "Test on held-out events."}
        obj = decision()
        obj["hypotheses"] = [h]
        self.assertEqual(validate_decision(obj)["hypotheses"], [h])
        for change in ({"feature": "future_return"}, {"feature": "strict_true"},
                       {"feature": "teacher_side"}, {"feature": "target"}, {"feature": "label_id"},
                       {"feature": "f083"}, {"feature": "110"}, {"feature": "point_94"},
                       {"feature": "evaluation_score"}, {"feature": "confirmed_side"},
                       {"threshold": math.inf}, {"stage_s": True}, {"stage_s": 600},
                       {"side": "BUY"}, {"op": "execute"}, {"rationale": "x" * 501}, {"extra": 3}):
            obj["hypotheses"] = [{**h, **change}]
            with self.assertRaises(ProviderError):
                validate_decision(obj)


class ProviderTests(unittest.TestCase):
    def local(self, *responses):
        session = FakeSession(*responses)
        return CortexProvider(AdapterConfig(backend="local_llama", model="local-model"), session), session

    def test_local_strict_schema_and_metadata(self):
        response = FakeResponse(envelope())
        provider, session = self.local(response)
        self.assertEqual(provider.generate({"candidate": {}}), decision())
        request = session.calls[0][1]
        self.assertEqual(request["json"]["response_format"]["type"], "json_schema")
        self.assertEqual(request["json"]["response_format"]["schema"]["type"], "object")
        self.assertFalse(request["json"]["response_format"]["schema"]["additionalProperties"])
        self.assertTrue(request["stream"])
        self.assertFalse(request["allow_redirects"])
        self.assertLessEqual(request["timeout"][0], 3)
        self.assertLessEqual(request["timeout"][1], provider.config.timeout_s)
        self.assertEqual(request["headers"], {})
        self.assertTrue(response.closed)
        self.assertTrue(provider.last_response_metadata["connection_verified"])

    def test_explicit_schema_unsupported_gets_one_fallback(self):
        provider, session = self.local(
            FakeResponse({"error": {"message": "response_format json_schema is not supported"}}, status=400),
            FakeResponse(envelope()))
        provider.generate({})
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1][1]["json"]["response_format"], {"type": "json_object"})
        self.assertTrue(provider.last_response_metadata["schema_fallback"])

    def test_arbitrary_bad_request_is_not_retried(self):
        provider, session = self.local(FakeResponse({"error": {"message": "secret body invalid model"}}, status=400))
        with self.assertRaisesRegex(ProviderError, "^provider_http_400$"):
            provider.generate({})
        self.assertEqual(len(session.calls), 1)

    def test_http_failures_do_not_expose_remote_content(self):
        for status in (401, 403, 429, 500, 302):
            provider, session = self.local(FakeResponse({"error": "sensitive provider payload"}, status=status))
            with self.assertRaisesRegex(ProviderError, "^provider_http_" + str(status) + "$"):
                provider.generate({})
            self.assertEqual(len(session.calls), 1)

    def test_reasoning_content_is_not_salvaged(self):
        body = envelope()
        body["choices"][0]["message"] = {"content": None, "reasoning_content": json.dumps(decision())}
        provider, _ = self.local(FakeResponse(body))
        with self.assertRaisesRegex(ProviderError, "missing_final_content"):
            provider.generate({})

    def test_markdown_and_embedded_json_are_rejected(self):
        for text in ("```json\n" + json.dumps(decision()) + "\n```", "Explanation " + json.dumps(decision()),
                     '{"verdict":"WAIT","verdict":"FORMING_LOW"}'):
            body = envelope()
            body["choices"][0]["message"]["content"] = text
            provider, _ = self.local(FakeResponse(body))
            with self.assertRaisesRegex(ProviderError, "invalid_json"):
                provider.generate({})

    def test_incomplete_or_refusal_rejected(self):
        body = envelope()
        body["choices"][0]["finish_reason"] = "length"
        provider, _ = self.local(FakeResponse(body))
        with self.assertRaisesRegex(ProviderError, "incomplete_output"):
            provider.generate({})
        provider, _ = self.local(FakeResponse(envelope(refusal="no")))
        with self.assertRaisesRegex(ProviderError, "refusal"):
            provider.generate({})

    def test_response_and_prompt_size_limits(self):
        response = FakeResponse(b"{}", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
        provider, _ = self.local(response)
        with self.assertRaisesRegex(ProviderError, "response_too_large"):
            provider.generate({})
        self.assertTrue(response.closed)
        provider, _ = self.local(FakeResponse(b"{}", chunks=[b"x" * (MAX_RESPONSE_BYTES + 1)]))
        with self.assertRaisesRegex(ProviderError, "response_too_large"):
            provider.generate({})
        provider, session = self.local()
        with self.assertRaisesRegex(ProviderError, "prompt_too_large"):
            provider.generate({"data": "x" * (64 * 1024)})
        self.assertEqual(session.calls, [])

    def test_timeout_or_connection_failure_sanitized(self):
        for exc, code in ((requests.Timeout("secret"), "provider_timeout"),
                          (requests.ConnectionError("secret"), "provider_transport_error")):
            provider, session = self.local(exc)
            with self.assertRaisesRegex(ProviderError, "^" + code + "$"):
                provider.generate({})
            self.assertEqual(len(session.calls), 1)

    def test_openai_fixed_endpoint_and_structured_output(self):
        result = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(decision())}]}]}
        session = FakeSession(FakeResponse(result))
        provider = CortexProvider(AdapterConfig(backend="openai", model="explicit-model", api_key="fake-key"), session)
        self.assertEqual(provider.generate({}), decision())
        url, request = session.calls[0]
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(request["headers"]["Authorization"], "Bearer fake-key")
        self.assertTrue(request["json"]["text"]["format"]["strict"])
        self.assertEqual(provider.last_response_metadata["model"], "explicit-model")

    def test_hypotheses_require_feature_present_in_payload(self):
        obj = decision()
        obj["hypotheses"] = [{"feature": "flow_30s", "op": "ge", "threshold": 0.4,
                              "side": "LOW", "stage_s": 60, "rationale": "Test independently."}]
        provider, _ = self.local(FakeResponse(envelope(obj)))
        with self.assertRaisesRegex(ProviderError, "unknown_hypothesis_feature"):
            provider.generate({})
        provider, _ = self.local(FakeResponse(envelope(obj)))
        self.assertEqual(provider.generate({"allowed_features": ["flow_30s"]}), obj)

    def test_confirmed_verdict_requires_matured_matching_teacher(self):
        obj = decision()
        obj["verdict"] = "CONFIRMED_LOW"
        for payload in ({}, {"as_of_ms": 50, "teacher_confirmation": {"side": "LOW", "available_ms": 100}},
                        {"as_of_ms": 100, "teacher_confirmation": {"side": "HIGH", "available_ms": 50}}):
            provider, _ = self.local(FakeResponse(envelope(obj)))
            with self.assertRaisesRegex(ProviderError, "unverified_confirmation"):
                provider.generate(payload)
        provider, _ = self.local(FakeResponse(envelope(obj)))
        self.assertEqual(provider.generate({"as_of_ms": 100, "teacher_confirmation": {
            "side": "LOW", "available_ms": 50}}), obj)


class StartupTests(unittest.TestCase):
    """Exercise the launcher with inert binaries; do not download or serve a model."""
    script = Path(__file__).resolve().parents[1] / "src/research/hype_quant/start_local_cortex.sh"

    def test_missing_model_fails_without_install_or_launch(self):
        result = subprocess.run(["bash", str(self.script)], env={"PATH": os.environ["PATH"]},
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertIn("set_CORTEX_MODEL_PATH", result.stderr)

    def test_existing_binary_local_model_and_runner_temp_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / "llama-server"
            binary.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(60)\n")
            binary.chmod(0o700)
            curl = root / "curl"
            curl.write_text("#!/bin/sh\nexit 0\n")
            curl.chmod(0o700)
            model = root / "model.gguf"
            model.touch()
            pidfile = root / "server.pid"
            env = {"PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "CORTEX_LLAMA_BIN": str(binary), "CORTEX_MODEL_PATH": str(model),
                   "CORTEX_LOG": str(root / "server.log"), "CORTEX_PIDFILE": str(pidfile),
                   "CORTEX_READY_TIMEOUT_SECONDS": "2"}
            try:
                result = subprocess.run(["bash", str(self.script)], env=env, capture_output=True,
                                        text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("CORTEX_READY", result.stdout)
                self.assertTrue(pidfile.exists())
                # The second launch cannot create another writer/server.
                second = subprocess.run(["bash", str(self.script)], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(second.returncode, 2)
                self.assertTrue("lock" in second.stderr or "alive" in second.stderr)
            finally:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_startup_timeout_kills_own_child(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / "llama-server"
            binary.write_text("#!" + sys.executable + "\nimport time\ntime.sleep(60)\n")
            binary.chmod(0o700)
            curl = root / "curl"
            curl.write_text("#!/bin/sh\nexit 1\n")
            curl.chmod(0o700)
            model = root / "model.gguf"
            model.touch()
            pidfile = root / "server.pid"
            env = {"PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "CORTEX_LLAMA_BIN": str(binary), "CORTEX_MODEL_PATH": str(model),
                   "CORTEX_LOG": str(root / "server.log"), "CORTEX_PIDFILE": str(pidfile),
                   "CORTEX_READY_TIMEOUT_SECONDS": "1"}
            result = subprocess.run(["bash", str(self.script)], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertIn("health_timeout", result.stderr)
            self.assertFalse(pidfile.exists())


if __name__ == "__main__":
    unittest.main()
