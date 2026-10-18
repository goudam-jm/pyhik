"""Experimental read-only ISAPI client; no native SDK is required.

No vendor device has been tested. See docs/isapi.md for supported scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import threading
from urllib.parse import urlsplit, urlunsplit
from xml.etree.ElementTree import ParseError


class ISAPIError(RuntimeError):
    """Base error. Messages exclude credentials and device response bodies."""


class ISAPIDependencyError(ISAPIError):
    """The optional ISAPI dependency group is not installed."""


class ISAPIStateError(ISAPIError):
    """The client has been closed."""


class ISAPIConnectionError(ISAPIError):
    """Connection or response-body transport failure."""


class ISAPITimeoutError(ISAPIConnectionError):
    """Connect/read timeout (not an overall operation deadline)."""


class ISAPITLSError(ISAPIConnectionError):
    """TLS verification or handshake failure."""


class ISAPIHTTPError(ISAPIError):
    def __init__(self, endpoint: str, status_code: int):
        self.endpoint = endpoint
        self.status_code = status_code
        super().__init__(f"GET {endpoint}: HTTP {status_code}")


class ISAPIAuthError(ISAPIHTTPError):
    """Authentication failed or permission was denied."""


class UnsupportedFeatureError(ISAPIHTTPError):
    """Device does not expose the requested endpoint (404/405/501)."""


class ISAPIProtocolError(ISAPIError):
    """Malformed, oversized, or unexpected protocol response."""


class ISAPIDeviceError(ISAPIError):
    def __init__(self, endpoint: str, device_code: str | None):
        self.endpoint = endpoint
        # A numeric code is safe to expose; arbitrary vendor text is not.
        self.device_code = (
            device_code
            if device_code and len(device_code) <= 10 and device_code.isascii() and device_code.isdecimal()
            else None
        )
        super().__init__(f"GET {endpoint}: device rejected request (code {self.device_code or 'unknown'})")


@dataclass(frozen=True)
class XMLNode:
    """Immutable XML tree preserving namespaces, attributes and unknown fields."""

    tag: str
    attributes: tuple[tuple[str, str], ...]
    text: str | None
    children: tuple[XMLNode, ...]

    @property
    def name(self) -> str:
        return self.tag.rsplit("}", 1)[-1]

    def child(self, name: str) -> XMLNode | None:
        return next((child for child in self.children if child.name == name), None)

    def value(self, name: str) -> str | None:
        child = self.child(name)
        return child.text if child else None


@dataclass(frozen=True)
class DeviceInfo:
    name: str | None
    model: str | None
    serial_number: str | None = field(repr=False)
    firmware_version: str | None
    device_type: str | None
    xml: XMLNode = field(repr=False)


@dataclass(frozen=True)
class StreamInfo:
    """A reported streaming ID; not an assertion that a camera is online."""

    id: str
    name: str | None
    enabled: bool | None
    video_input_id: str | None
    xml: XMLNode = field(repr=False)


def _timeout(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number of seconds")
    return float(value)


def _port(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    return value


def _stream_id(value: str | int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,9}", str(value)):
        raise ValueError("stream_id must be a positive numeric ID reported by the device")
    return str(value)


def _node(element, depth: int = 0) -> XMLNode:
    if depth > 64:
        raise ISAPIProtocolError("XML nesting exceeds 64 levels")
    return XMLNode(
        element.tag,
        tuple(element.attrib.items()),
        element.text.strip() if element.text and element.text.strip() else None,
        tuple(_node(child, depth + 1) for child in element),
    )


class ISAPIClient:
    """Synchronous GET-only client with explicit origin, Digest auth and TLS.

    URL must include http:// or https://; defaults follow that scheme. HTTP
    does not encrypt traffic. Requests and close are serialized; no automatic
    Basic-auth fallback, redirects, protocol/backend fallback, or cached reads.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: tuple[float, float] = (3.0, 15.0),
        verify: bool | str = True,
        max_response_bytes: int = 8 * 1024 * 1024,
    ):
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
            host = parsed.hostname
        except (TypeError, ValueError):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or a path") from None
        if (
            not isinstance(base_url, str)
            or any(char.isspace() or ord(char) < 32 for char in base_url)
            or parsed.scheme not in ("http", "https")
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or "\\" in parsed.netloc
            or "%" in parsed.netloc
        ):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or a path")
        if port is not None:
            _port(port)
        for value, label in ((username, "username"), (password, "password")):
            if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
                raise ValueError(f"{label} must be nonempty text without control characters")
        if not isinstance(timeout, tuple) or len(timeout) != 2:
            raise ValueError("timeout must be a (connect_seconds, read_seconds) tuple")
        self.timeout = (_timeout(timeout[0], "connect timeout"), _timeout(timeout[1], "read timeout"))
        if not isinstance(verify, (bool, str)) or verify == "":
            raise ValueError("verify must be bool or a nonempty CA bundle path")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")
        self.verify = verify
        self.max_response_bytes = max_response_bytes
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority += f":{port}"
        self.base_url = urlunsplit((parsed.scheme, authority, "", "", ""))
        self._host = host
        self._lock = threading.RLock()
        self._closed = False
        try:
            import requests
            from defusedxml import ElementTree
            from defusedxml.common import DefusedXmlException
            from urllib3.exceptions import ReadTimeoutError
        except ImportError:
            raise ISAPIDependencyError(
                "Install the optional dependencies: pip install 'pyhik-hcnetsdk[isapi]'"
            ) from None
        self._requests = requests
        self._xml = ElementTree
        self._xml_errors = (ParseError, DefusedXmlException)
        self._read_timeout_error = ReadTimeoutError
        self._session = requests.Session()
        # Ignore proxy/netrc/environment auth overrides; use explicit auth and CA.
        self._session.trust_env = False
        self._session.auth = requests.auth.HTTPDigestAuth(username, password)

    def _require_open(self):
        if self._closed:
            raise ISAPIStateError("ISAPI client is closed")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._session.close()
                self._closed = True

    def __enter__(self) -> ISAPIClient:
        with self._lock:
            self._require_open()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _get(self, endpoint: str) -> tuple[bytes, str]:
        # Only the fixed public read methods below construct endpoints.
        with self._lock:
            self._require_open()
            try:
                with self._session.get(
                    self.base_url + endpoint,
                    timeout=self.timeout,
                    verify=self.verify,
                    allow_redirects=False,
                    stream=True,
                    headers={"Accept": "application/xml, image/jpeg"},
                ) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise ISAPIAuthError(endpoint, status)
                    if status in (404, 405, 501):
                        raise UnsupportedFeatureError(endpoint, status)
                    if status != 200:
                        raise ISAPIHTTPError(endpoint, status)
                    length = response.headers.get("Content-Length")
                    if length:
                        try:
                            size = int(length)
                        except ValueError:
                            raise ISAPIProtocolError("Invalid Content-Length") from None
                        if size < 0 or size > self.max_response_bytes:
                            raise ISAPIProtocolError("Response exceeds configured byte limit")
                    content = bytearray()
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if len(content) + len(chunk) > self.max_response_bytes:
                            raise ISAPIProtocolError("Response exceeds configured byte limit")
                        content.extend(chunk)
                    return bytes(content), response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            except self._requests.exceptions.SSLError:
                raise ISAPITLSError(f"GET {endpoint}: TLS handshake or verification failed") from None
            except self._requests.exceptions.Timeout:
                raise ISAPITimeoutError(f"GET {endpoint}: connect/read timeout") from None
            except self._requests.exceptions.ConnectionError as exc:
                # Requests wraps streamed urllib3 read timeouts as ConnectionError.
                if exc.args and isinstance(exc.args[0], self._read_timeout_error):
                    raise ISAPITimeoutError(f"GET {endpoint}: response read timeout") from None
                raise ISAPIConnectionError(f"GET {endpoint}: transport failed") from None
            except self._requests.exceptions.RequestException:
                raise ISAPIConnectionError(f"GET {endpoint}: transport failed") from None

    def _parse_xml(self, body: bytes, endpoint: str) -> XMLNode:
        try:
            root = self._xml.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        except self._xml_errors:
            raise ISAPIProtocolError(f"GET {endpoint}: malformed or prohibited XML") from None
        node = _node(root)
        if node.name == "ResponseStatus":
            if node.value("statusCode") == "1":
                raise ISAPIProtocolError(f"GET {endpoint}: status response without requested data")
            raise ISAPIDeviceError(endpoint, node.value("statusCode"))
        return node

    def _get_xml(self, endpoint: str, expected: tuple[str, ...]) -> XMLNode:
        body, content_type = self._get(endpoint)
        node = self._parse_xml(body, endpoint)
        if node.name not in expected:
            raise ISAPIProtocolError(f"GET {endpoint}: unexpected XML root")
        return node

    def get_device_info(self) -> DeviceInfo:
        node = self._get_xml("/ISAPI/System/deviceInfo", ("DeviceInfo",))
        return DeviceInfo(
            node.value("deviceName"),
            node.value("model"),
            node.value("serialNumber"),
            node.value("firmwareVersion"),
            node.value("deviceType"),
            node,
        )

    def get_capabilities(self) -> XMLNode:
        """Return reported XML without guessing support from missing fields."""
        return self._get_xml("/ISAPI/System/capabilities", ("DeviceCap", "DeviceCapabilities"))

    def get_streaming_channels(self) -> tuple[StreamInfo, ...]:
        endpoint = "/ISAPI/Streaming/channels"
        node = self._get_xml(endpoint, ("StreamingChannelList", "StreamingChannel"))
        channels = (
            (node,)
            if node.name == "StreamingChannel"
            else tuple(c for c in node.children if c.name == "StreamingChannel")
        )
        result = []
        for channel in channels:
            try:
                identifier = _stream_id(channel.value("id"))
            except ValueError:
                raise ISAPIProtocolError(f"GET {endpoint}: missing or invalid streaming ID") from None
            enabled = channel.value("enabled")
            if enabled is not None and enabled.lower() not in ("true", "false", "1", "0"):
                raise ISAPIProtocolError(f"GET {endpoint}: invalid enabled value")
            video = channel.child("Video")
            result.append(
                StreamInfo(
                    identifier,
                    channel.value("channelName"),
                    None if enabled is None else enabled.lower() in ("true", "1"),
                    video.value("videoInputChannelID") if video else None,
                    channel,
                )
            )
        return tuple(result)

    def get_snapshot(self, stream_id: str | int) -> bytes:
        """Return JPEG bytes for an explicit reported stream ID (e.g. 101)."""
        endpoint = f"/ISAPI/Streaming/channels/{_stream_id(stream_id)}/picture"
        body, content_type = self._get(endpoint)
        if content_type != "image/jpeg" or not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
            if "xml" in content_type:
                self._parse_xml(body, endpoint)
            raise ISAPIProtocolError(f"GET {endpoint}: expected a complete JPEG response")
        return body

    def get_rtsp_url(self, stream_id: str | int, *, port: int = 554, secure: bool = False) -> str:
        """Build a credential-free URL; HTTPS does not imply RTSPS support."""
        identifier = _stream_id(stream_id)
        _port(port)
        if not isinstance(secure, bool):
            raise ValueError("secure must be bool")
        with self._lock:
            self._require_open()
        host = f"[{self._host}]" if ":" in self._host else self._host
        return f"{'rtsps' if secure else 'rtsp'}://{host}:{port}/Streaming/Channels/{identifier}"


__all__ = [
    "ISAPIClient",
    "DeviceInfo",
    "StreamInfo",
    "XMLNode",
    "ISAPIError",
    "ISAPIDependencyError",
    "ISAPIStateError",
    "ISAPIConnectionError",
    "ISAPITimeoutError",
    "ISAPITLSError",
    "ISAPIHTTPError",
    "ISAPIAuthError",
    "UnsupportedFeatureError",
    "ISAPIProtocolError",
    "ISAPIDeviceError",
]
