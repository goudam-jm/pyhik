# Read-only ISAPI client

`hikvision_isapi.ISAPIClient` provides synchronous HTTP access to device reads.
Native SDK functionality remains available through `hikvision_native.SDK`.

Install from this checkout with `python -m pip install '.[isapi]'`. The base
package still imports without Requests, defusedxml or vendor DLLs. Constructing
an ISAPI client without its extra raises `ISAPIDependencyError` with installation
instructions.

## Supported operations

- `get_device_info()` returns immutable `DeviceInfo` with optional identity
  fields and the original XML tree. Its repr excludes serial number/raw XML.
- `get_capabilities()` returns immutable `XMLNode` data from system capabilities.
  Namespaces, attributes, nested nodes and unknown fields are preserved.
  Missing fields do not imply that a feature is supported or unsupported.
- `get_streaming_channels()` returns immutable `StreamInfo` entries with reported
  IDs, optional name/enabled flag and explicit video-input mapping where present.
  An ID such as `3302` is preserved, not converted to a guessed native channel.
  An empty list is a device result; a failed request remains an exception.
- `get_snapshot(stream_id)` returns JPEG bytes from an explicit reported ID,
  e.g. `101`, not camera number `1`. The response must have `image/jpeg` media
  type and JPEG start/end markers. This is an envelope check, not a decoder.
- `get_rtsp_url(stream_id, port=554, secure=False)` constructs a URL without
  username/password. It performs no network request or support detection.
  HTTPS on the control plane does not imply RTSPS support; select it explicitly
  only when your device supports it. Supply player credentials separately.

The client uses standard ISAPI device paths. There is no
HTTP-to-native fallback, fabricated NVR stream enumeration, background thread,
implicit caching, raw arbitrary-endpoint method, or device-changing operation.

## Connection and lifecycle

Supply an explicit origin such as `https://camera.example:8443`, without URL
credentials, path, query or fragment. IPv6 literals use brackets. Default ports
follow the supplied scheme. Use HTTP port 80/HTTPS port 443 or your configured
HTTP(S) port, not HCNetSDK's service port.

Requests Digest authentication is used; Basic-only devices fail with an auth
error rather than receiving an automatic downgrade. HTTP remains unencrypted
even with Digest. HTTPS verification is on by default. `verify` accepts True,
False (explicit insecure opt-in) or a CA bundle filename. The client does not
suppress TLS warnings. Environment proxies/netrc/CA overrides are ignored; pass
CA configuration explicitly. Redirects are not followed.

Use a context manager or call `close()`; close is idempotent and reuse raises
`ISAPIStateError`. Network reads and close are serialized. Do not nest contexts
for the same client. The timeout tuple defaults to `(3.0, 15.0)` seconds for
connect/read inactivity; it is not a total operation deadline. Failed reads do
not retry automatically; Requests may exchange Digest challenges internally.

Successful response bodies are streamed with an 8 MiB default byte limit,
configurable through `max_response_bytes`. Limits apply to the final successful
response before parsing; Requests manages authentication challenge/redirect
response processing internally. XML parsing prohibits DTDs/entities and caps
nesting depth. Treat device data as untrusted application input even after parsing.

## Errors

`ISAPIAuthError` distinguishes HTTP 401/403; `UnsupportedFeatureError` represents
404/405/501. Both retain endpoint and HTTP `status_code`. Other unexpected HTTP
statuses, including redirects, raise `ISAPIHTTPError`. `ISAPIDeviceError` covers
XML error-status responses even when HTTP status is 200. Malformed, unexpected
or oversized data raises `ISAPIProtocolError`. Transport errors, timeouts and
TLS failures have separate exception types. Error messages omit response bodies,
credentials and underlying Requests error text. Native failures still use
`SDKError`; the backends are not silently substituted.

## Verification status

Tests use synthetic XML/JPEG envelopes and an in-memory Requests adapter. They
exercise request preparation, a complete Digest challenge exchange, explicit
TLS settings, XML variations, errors and lifecycle without sockets or a device.
They establish library behavior only. Model/firmware compatibility, image
validity and actual RTSP playback remain unverified. Before making support
claims, compare information/stream IDs with a physical device, retrieve and
open a real JPEG, test bad credentials/permissions and validate certificate
handling and firmware-specific capability responses.

Events, recording search/download, PTZ and configuration writes remain outside
this slice.
