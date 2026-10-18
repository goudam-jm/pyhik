# pyhik — maintenance work in progress

Experimental modernization of the 2014 Hikvision HCNetSDK binding, now with
a separate optional read-only ISAPI client. Neither backend has been tested
against a real device in this maintenance effort.

The maintenance branch supports Python 3.11+ for packaging/offline development.
Native execution is restricted to Windows x64 and is **hardware-unverified**.
Importing the package works without Windows or the vendor SDK.

## Install from this checkout

```console
python -m venv .venv
# Activate the environment, then:
python -m pip install .
```

The provisional distribution name is `pyhik-hcnetsdk`; the import is
`hikvision_native`, with optional HTTP functionality in `hikvision_isapi`.
No public release or name-availability claim is made.
The PyPI name `pyhik` does not install this repository; use the checkout
installation instructions above.

Vendor DLLs are excluded from distributions. Obtain a complete matching SDK
bundle from Hikvision under its terms, preserve the bundle's directory layout,
and pass its absolute `HCNetSDK.dll` path. The historical root DLL remains in Git
for provenance, but is never automatically selected or included in builds.

## Read-only ISAPI (no native SDK required)

```console
python -m pip install '.[isapi]'
```

```python
from getpass import getpass
from hikvision_isapi import ISAPIClient

with ISAPIClient("https://192.0.2.10", "admin", getpass("Device password: ")) as client:
    print(client.get_device_info())
    streams = client.get_streaming_channels()
    print(streams)  # Use an ID actually reported by your device.
    print(client.get_rtsp_url("101"))  # No credentials embedded in the URL.
```

This uses the device's HTTP(S) port, not native port 8000. HTTPS certificates
are verified by default; pass a CA bundle path through `verify` for a private CA.
HTTP must be selected explicitly with `http://` and does not encrypt traffic.
See [ISAPI usage and limits](docs/isapi.md) and [examples/isapi_snapshot.py](examples/isapi_snapshot.py).

## Native snapshot (Windows x64)

```python
from getpass import getpass
from hikvision_native import SDK

with SDK(r"C:\vendor\HCNetSDK\HCNetSDK.dll") as sdk:
    sdk.set_connect_time(3000, attempts=1)
    with sdk.login("192.0.2.10", 8000, "admin", getpass("Device password: ")) as device:
        print(device.channels)  # Reported slots/capacity, not online-camera discovery.
        device.capture_jpeg(channel=1, destination="snapshot.jpg")
```

`192.0.2.10` is an example address: supply your device address and valid channel.
Use the device's native service port (commonly 8000), not its HTTP port. Output
parent directories must exist. Narrow-character native strings use explicit
UTF-8 encoding by default; pass `encoding="..."` if your chosen SDK/device needs a
different encoding. Non-ASCII credentials and paths require real-device testing.
Alternatively set `HIKVISION_SDK_PATH` to the absolute DLL or bundle directory.

`SDKError` preserves `operation` and numeric `code`, including unknown codes.
Credentials are never included in SDK error messages. Applications own logging;
the library installs only a `NullHandler` and never creates log files on import.

## Resource ownership

One `SDK` instance owns the process runtime; share it across multiple device
sessions. Independent simultaneous owners are rejected. Calls are serialized so
close waits for in-progress synchronous calls. Closing stops previews before
logout, then cleans up the runtime. Close is idempotent after success. If a
native close operation fails, references/handles are retained and `close()` can
be retried; cleanup failure is logged without replacing an existing exception
from a context body. Do not mix these objects with unmanaged native consumers.
Do not nest contexts for the same SDK or device: each context owns its exit.
There is no automatic finalizer or forced thread cancellation.

Raw V30 preview is available through `Device.start_preview()` and
`stop_preview()`. Its callback receives **borrowed encoded-stream memory**, not
frames. Copy it within the callback if needed, return promptly, and never call
SDK methods from a native callback (doing so can deadlock against the serialized
native call). Implement your application's bounded queue/backpressure outside
the callback. The two native callback APIs have different user-data widths;
see [migration notes](docs/migration.md).

## Offline checks

```console
python -m pip install '.[dev,isapi]'
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
python -m twine check dist/*
```

Tests use a fake native boundary, ctypes callback trampolines, and an in-memory
HTTP adapter exercising real Requests authentication/preparation. Passing them
is not evidence of native/device compatibility. CI runs offline tests across
Linux and Windows; it never loads the vendor DLL. Run the
[ABI probe](docs/compatibility.md) and device checklist before advertising native
support.

## Scope and reuse

This pass maintains login/logout, timeouts/reconnect, JPEG capture, raw preview,
and legacy adapters. The separate read-only ISAPI client adds device information,
capabilities, reported streaming channels, JPEG snapshots and credential-free
RTSP URL construction. It does not add events, recordings/playback, PTZ,
configuration writes, Linux native support, or a decoder. These need their own
implementation and hardware validation path.

See [compatibility and validation](docs/compatibility.md),
[migration](docs/migration.md), [maintenance roadmap](docs/maintenance.md), and
[changelog](CHANGELOG.md).

No open-source license was present in the original tree. Source licensing and
vendor redistribution terms still need the owner's decision before a public
package release; this maintenance pass does not invent a license or grant rights
to the vendor binary.
