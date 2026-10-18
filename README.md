# pyhik — maintenance work in progress

Experimental modernization of 2014 Python binding for
Hikvision's native HCNetSDK. This is the native **Device Network SDK**, not an
ISAPI HTTP client. Nothing in this branch has been tested against a real device.

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
`hikvision_native`. No public release or name-availability claim is made.
**Do not use `pip install pyhik` to install this repository**: that name belongs
to [another project](https://pypi.org/project/pyHik/).

Vendor DLLs are excluded from distributions. Obtain a complete matching SDK
bundle from Hikvision under its terms, preserve the bundle's directory layout,
and pass its absolute `HCNetSDK.dll` path. The historical root DLL remains in Git
for provenance, but is never automatically selected or included in builds.

## Capture a snapshot

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
python -m unittest discover -s tests -v
python -m pip install '.[dev]'
python -m ruff check .
python -m ruff format --check .
python -m build
python -m twine check dist/*
```

Tests use a fake native boundary and ctypes callback trampolines. Passing them
is not evidence of native/device compatibility. CI runs offline tests across
Linux and Windows; it never loads the vendor DLL. Run the
[ABI probe](docs/compatibility.md) and device checklist before advertising native
support.

## Scope and reuse

This pass maintains login/logout, timeouts/reconnect, JPEG capture, raw preview,
and legacy adapters. It does not add ISAPI, events, recordings/playback, PTZ,
Linux native support, or a decoder. These need a separate implementation and
hardware validation path.

See [compatibility and validation](docs/compatibility.md),
[migration](docs/migration.md), [maintenance roadmap](docs/maintenance.md), and
[changelog](CHANGELOG.md).

No open-source license was present in the original tree. Source licensing and
vendor redistribution terms still need the owner's decision before a public
package release; this maintenance pass does not invent a license or grant rights
to the vendor binary.
