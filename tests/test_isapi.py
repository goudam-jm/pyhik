"""Synthetic protocol tests using real Requests preparation/auth, with no sockets."""

import builtins
import dataclasses
import hashlib
import io
import threading
import unittest
from unittest import mock

import hikvision_isapi as h

try:
    import requests
    import defusedxml  # noqa: F401
    from urllib3.response import HTTPResponse
except ImportError:
    requests = None

DEVICE = b"""<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">
<deviceName>Lab unit</deviceName><model>synthetic-model</model><serialNumber>private-serial</serialNumber>
<firmwareVersion>test-only</firmwareVersion><deviceType>camera</deviceType><futureField flag="true">extra</futureField>
</DeviceInfo>"""
STREAMS = b"""<StreamingChannelList xmlns="http://www.isapi.org/ver20/XMLSchema">
<StreamingChannel><id>101</id><channelName>North</channelName><enabled>true</enabled>
<Video><videoInputChannelID>1</videoInputChannelID></Video></StreamingChannel>
<StreamingChannel><id>3302</id><enabled>false</enabled></StreamingChannel></StreamingChannelList>"""
JPEG = b"\xff\xd8synthetic-envelope-only\xff\xd9"


class DependencyTests(unittest.TestCase):
    def test_missing_optional_dependencies_have_actionable_error(self):
        original_import = builtins.__import__

        def without_requests(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("simulated missing extra")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=without_requests):
            with self.assertRaisesRegex(h.ISAPIDependencyError, r"\[isapi\]"):
                h.ISAPIClient("https://example.invalid", "user", "password")

    def test_bad_origins_rejected_before_any_dependency_or_connection(self):
        for origin in (
            "camera",
            "ftp://camera",
            "https://u:password@camera",
            "http://camera/ISAPI",
            "http://camera?password=x",
            "http://camera#part",
            "http://camera:0",
            "http://camera:65536",
            "http://camera:bad",
            " http://camera",
            "http://camera\\other",
            "http://ca%6dera",
            "http://camera\n",
            None,
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                h.ISAPIClient(origin, "user", "password")


if requests is not None:

    class Adapter(requests.adapters.BaseAdapter):
        def __init__(self):
            self.calls = []
            self.responses = []
            self.handler = lambda request: (200, {"Content-Type": "application/xml"}, DEVICE)
            self.closed = False

        def send(self, request, **kwargs):
            self.calls.append((request, kwargs))
            result = self.handler(request)
            if isinstance(result, Exception):
                raise result
            status, headers, body = result
            response = requests.Response()
            response.status_code = status
            response.headers.update(headers)
            response.url = request.url
            response.request = request
            response.connection = self
            response.raw = HTTPResponse(
                body=body if hasattr(body, "read") else io.BytesIO(body),
                headers=headers,
                preload_content=False,
                status=status,
            )
            self.responses.append(response)
            return response

        def close(self):
            self.closed = True


@unittest.skipIf(requests is None, "Install the isapi extra to exercise HTTP/XML behavior")
class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = h.ISAPIClient("https://example.invalid:8443", "user", "secret-password")
        self.adapter = Adapter()
        self.client._session.mount("https://", self.adapter)
        self.client._session.mount("http://", self.adapter)

    def tearDown(self):
        self.client.close()

    def reply(self, body, content_type="application/xml", status=200, **headers):
        self.adapter.handler = lambda request: (status, {"Content-Type": content_type, **headers}, body)

    def test_device_info_namespaces_and_unknown_fields_are_preserved(self):
        info = self.client.get_device_info()
        self.assertEqual(info.name, "Lab unit")
        self.assertEqual(info.model, "synthetic-model")
        self.assertEqual(info.serial_number, "private-serial")
        self.assertNotIn("private-serial", repr(info))
        self.assertEqual(info.xml.tag, "{http://www.hikvision.com/ver20/XMLSchema}DeviceInfo")
        self.assertEqual(info.xml.child("futureField").attributes, (("flag", "true"),))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            info.name = "changed"

    def test_missing_device_fields_are_none_not_invented_values(self):
        self.reply(b"<DeviceInfo/>")
        info = self.client.get_device_info()
        self.assertIsNone(info.name)
        self.assertIsNone(info.firmware_version)

    def test_reads_are_not_silently_cached(self):
        self.client.get_device_info()
        self.reply(b"<DeviceInfo><deviceName>Updated</deviceName></DeviceInfo>")
        self.assertEqual(self.client.get_device_info().name, "Updated")
        self.assertEqual(len(self.adapter.calls), 2)

    def test_requests_use_timeouts_explicit_tls_and_no_environment(self):
        self.client.verify = "/explicit-ca.pem"
        self.client.get_device_info()
        request, kwargs = self.adapter.calls[-1]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.url, "https://example.invalid:8443/ISAPI/System/deviceInfo")
        self.assertEqual(kwargs["timeout"], (3.0, 15.0))
        self.assertEqual(kwargs["verify"], "/explicit-ca.pem")
        self.assertFalse(self.client._session.trust_env)
        self.assertEqual(kwargs["proxies"], {})
        self.assertNotIn("secret-password", request.url)

    def test_digest_challenge_is_answered_without_basic_fallback(self):
        def authenticate(request):
            auth = request.headers.get("Authorization", "")
            if not auth:
                return 401, {"WWW-Authenticate": 'Digest realm="lab", nonce="fixed", algorithm=MD5, qop="auth"'}, b""
            self.assertTrue(auth.startswith("Digest "))
            parts = requests.utils.parse_dict_header(auth[7:])
            md5 = lambda text: hashlib.md5(text.encode()).hexdigest()  # noqa: E731
            ha1 = md5("user:lab:secret-password")
            ha2 = md5("GET:" + parts["uri"])
            expected = md5(f"{ha1}:fixed:{parts['nc']}:{parts['cnonce']}:auth:{ha2}")
            self.assertEqual(parts["response"], expected)
            return 200, {"Content-Type": "application/xml"}, DEVICE

        self.adapter.handler = authenticate
        self.assertEqual(self.client.get_device_info().name, "Lab unit")
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertTrue(all(response.raw.closed for response in self.adapter.responses))

    def test_basic_only_device_is_reported_as_auth_failure(self):
        self.adapter.handler = lambda request: (401, {"WWW-Authenticate": 'Basic realm="lab"'}, b"")
        with self.assertRaises(h.ISAPIAuthError):
            self.client.get_device_info()
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertNotIn("Authorization", self.adapter.calls[0][0].headers)

    def test_capabilities_preserve_nested_attributes_without_boolean_guesses(self):
        self.reply(b'<DeviceCap xmlns="urn:test"><Streaming><channels opt="1,2">2</channels></Streaming></DeviceCap>')
        cap = self.client.get_capabilities()
        self.assertEqual(cap.child("Streaming").child("channels").attributes, (("opt", "1,2"),))
        self.assertIsNone(cap.child("UnreportedFeature"))

    def test_streams_preserve_ids_missing_flags_and_video_mapping(self):
        self.reply(STREAMS)
        streams = self.client.get_streaming_channels()
        self.assertEqual([stream.id for stream in streams], ["101", "3302"])
        self.assertEqual([stream.enabled for stream in streams], [True, False])
        self.assertEqual(streams[0].video_input_id, "1")
        self.assertIsNone(streams[1].name)
        self.reply(b"<StreamingChannel><id>201</id></StreamingChannel>")
        self.assertIsNone(self.client.get_streaming_channels()[0].enabled)
        self.reply(b"<StreamingChannelList/>")
        self.assertEqual(self.client.get_streaming_channels(), ())

    def test_invalid_streams_fail_instead_of_hiding_protocol_errors(self):
        for body in (
            b"<StreamingChannel><id>../secret</id></StreamingChannel>",
            b"<StreamingChannel/>",
            b"<StreamingChannel><id>101</id><enabled>maybe</enabled></StreamingChannel>",
        ):
            self.reply(body)
            with self.assertRaises(h.ISAPIProtocolError):
                self.client.get_streaming_channels()

    def test_snapshot_returns_bytes_for_explicit_stream_id(self):
        self.reply(JPEG, "image/jpeg; charset=binary")
        self.assertEqual(self.client.get_snapshot("3302"), JPEG)
        self.assertTrue(self.adapter.calls[-1][0].url.endswith("/3302/picture"))

    def test_snapshot_rejects_html_wrong_type_and_truncated_data(self):
        for body, kind in (
            (b"<html>login</html>", "text/html"),
            (JPEG, "application/octet-stream"),
            (b"\xff\xd8truncated", "image/jpeg"),
        ):
            self.reply(body, kind)
            with self.assertRaises(h.ISAPIProtocolError):
                self.client.get_snapshot(101)

    def test_device_errors_inside_http_200_are_not_images_or_empty_models(self):
        self.reply(
            b"<ResponseStatus><statusCode>4</statusCode><statusString>private-body</statusString></ResponseStatus>"
        )
        for operation in (self.client.get_device_info, lambda: self.client.get_snapshot(101)):
            with self.assertRaises(h.ISAPIDeviceError) as result:
                operation()
            self.assertEqual(result.exception.device_code, "4")
            self.assertNotIn("private-body", str(result.exception))

    def test_status_codes_keep_operation_and_do_not_include_body(self):
        for status, error in (
            (401, h.ISAPIAuthError),
            (403, h.ISAPIAuthError),
            (404, h.UnsupportedFeatureError),
            (405, h.UnsupportedFeatureError),
            (501, h.UnsupportedFeatureError),
            (500, h.ISAPIHTTPError),
            (302, h.ISAPIHTTPError),
        ):
            self.reply(b"private-body", status=status)
            with self.assertRaises(error) as result:
                self.client.get_device_info()
            self.assertEqual(result.exception.status_code, status)
            self.assertEqual(result.exception.endpoint, "/ISAPI/System/deviceInfo")
            self.assertNotIn("private-body", str(result.exception))
            self.assertTrue(self.adapter.responses[-1].raw.closed)

    def test_redirect_is_not_followed(self):
        self.reply(b"", status=302, Location="https://other.invalid/secret")
        with self.assertRaises(h.ISAPIHTTPError):
            self.client.get_device_info()
        self.assertEqual(len(self.adapter.calls), 1)

    def test_xml_rejects_dtd_entities_malformed_html_and_deep_nesting(self):
        for body in (
            b'<!DOCTYPE DeviceInfo [<!ENTITY x "secret">]><DeviceInfo>&x;</DeviceInfo>',
            b"<DeviceInfo>",
            b"<html/>",
            b"<a>" * 70 + b"</a>" * 70,
        ):
            self.reply(body)
            with self.assertRaises(h.ISAPIProtocolError):
                self.client.get_device_info()

    def test_limit_applies_without_content_length_and_before_read_when_declared(self):
        self.client.max_response_bytes = 16
        for headers in ({}, {"Content-Length": "2000"}, {"Content-Length": "-1"}, {"Content-Length": "invalid"}):
            self.reply(DEVICE, **headers)
            with self.assertRaises(h.ISAPIProtocolError):
                self.client.get_device_info()
            self.assertTrue(self.adapter.responses[-1].raw.closed)

    def test_transport_errors_are_typed_and_redacted(self):
        for exception, expected in (
            (requests.exceptions.Timeout("private-url"), h.ISAPITimeoutError),
            (requests.exceptions.SSLError("secret-password"), h.ISAPITLSError),
            (requests.exceptions.ConnectionError("secret-password"), h.ISAPIConnectionError),
        ):
            self.adapter.handler = lambda request, error=exception: error
            with self.assertRaises(expected) as result:
                self.client.get_device_info()
            self.assertNotIn("secret-password", str(result.exception))
            self.assertNotIn("private-url", str(result.exception))
            self.assertTrue(result.exception.__suppress_context__)

    def test_rtsp_url_is_credential_free_and_not_inferred_from_https(self):
        self.assertEqual(self.client.get_rtsp_url(101), "rtsp://example.invalid:554/Streaming/Channels/101")
        self.assertTrue(self.client.get_rtsp_url(101, secure=True, port=322).startswith("rtsps://example.invalid:322/"))
        with h.ISAPIClient("http://[::1]:8080", "u", "p") as ipv6:
            self.assertEqual(ipv6.base_url, "http://[::1]:8080")
            self.assertEqual(ipv6.get_rtsp_url(201), "rtsp://[::1]:554/Streaming/Channels/201")

    def test_timeout_during_streamed_body_is_typed_and_closes_response(self):
        from urllib3.exceptions import ReadTimeoutError

        class TimedOutBody(io.BytesIO):
            def read(self, *args, **kwargs):
                raise ReadTimeoutError(None, "private-url", "secret-password")

        self.reply(TimedOutBody(DEVICE))
        with self.assertRaises(h.ISAPITimeoutError) as result:
            self.client.get_device_info()
        self.assertNotIn("secret-password", str(result.exception))
        self.assertTrue(self.adapter.responses[-1].raw.closed)

    def test_success_status_without_requested_data_is_a_protocol_error(self):
        self.reply(b"<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        with self.assertRaises(h.ISAPIProtocolError):
            self.client.get_device_info()

    def test_close_waits_for_in_progress_read(self):
        entered, finish = threading.Event(), threading.Event()
        errors = []

        def delayed_response(request):
            entered.set()
            if not finish.wait(5):
                raise AssertionError("test synchronization timeout")
            return 200, {"Content-Type": "application/xml"}, DEVICE

        def read():
            try:
                self.client.get_device_info()
            except Exception as exc:
                errors.append(exc)

        self.adapter.handler = delayed_response
        worker = threading.Thread(target=read)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            closer = threading.Thread(target=self.client.close)
            closer.start()
            self.assertFalse(self.adapter.closed)
        finally:
            finish.set()
            worker.join(5)
        closer.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(self.adapter.closed)

    def test_invalid_ids_cannot_change_request_origin_or_path(self):
        for value in ("../1", "//other.invalid", "101?key=x", "01", "0", 0, True, None, "1" * 11):
            with self.assertRaises(ValueError):
                self.client.get_snapshot(value)
            with self.assertRaises(ValueError):
                self.client.get_rtsp_url(value)
        self.assertEqual(self.adapter.calls, [])

    def test_close_is_idempotent_and_all_operations_reject_reuse(self):
        self.client.close()
        self.client.close()
        for operation in (
            self.client.get_device_info,
            self.client.get_capabilities,
            self.client.get_streaming_channels,
            lambda: self.client.get_snapshot(101),
            lambda: self.client.get_rtsp_url(101),
            self.client.__enter__,
        ):
            with self.assertRaises(h.ISAPIStateError):
                operation()
        self.assertTrue(self.adapter.closed)

    def test_constructor_options_are_validated(self):
        for options in (
            {"timeout": (0, 1)},
            {"timeout": (1, float("inf"))},
            {"timeout": 3},
            {"timeout": (True, 2)},
            {"max_response_bytes": 0},
            {"verify": ""},
        ):
            with self.assertRaises(ValueError):
                h.ISAPIClient("https://example.invalid", "u", "p", **options)


if __name__ == "__main__":
    unittest.main()
