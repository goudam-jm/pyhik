# Migrating from the 2014 module

The installed module is now `hikvision_native`. The root `pyhik.py` is a
source-checkout shim that emits a DeprecationWarning; it is intentionally
excluded from wheel and source distributions to avoid clashing with the
unrelated PyPI `pyHik` package. Original history remains in Git.

Core camelCase wrappers remain available from `hikvision_native`: init/release,
login/logout, timeouts/reconnect, preview, JPEG capture and error helpers. Prefer
`SDK` and `Device` contexts in new code. Set `HIKVISION_SDK_PATH` before using the
compatibility wrappers. No public `HC` global or bare-name DLL loading remains.
Initialization is idempotent, not reference-counted: wrappers and callers must
share an explicit lifetime rather than balancing nested init/release calls.

Behavior changes:

- Public text accepts str or bytes; native conversion happens at the boundary.
  NULs and empty strings are rejected. Output paths accept pathlib objects.
- Native failures consistently raise `SDKError` with the operation/code.
  `captureJPEGPicture`, `stopRealPlay` and `setRealDataCallBack` return True on
  success and raise on failure. Do not rely on False/-1/None error sentinels.
- Runtime-dependent helpers require initialization, including getSDKVersion and
  getLastError. Version is still returned as a hex string by getSDKVersion.
- BOOL/LONG/DWORD model the Windows ABI; HWND is pointer-sized. The preview
  CLIENTINFO structure has the four fields in Hikvision's V30 documentation.
- `CMPFUNC` is the RealPlay_V30 callback with pointer-sized user data.
  `LEGACY_CMPFUNC` is the SetRealDataCallBack callback with DWORD user data.
  Do not interchange them. A Python callable can be passed and wrapped by its
  corresponding API. A null callback is represented by None.
- Session/preview handles must be owned by this SDK; raw external handles are
  rejected. Callback objects are retained through successful stop. Raw callback
  pointers remain borrowed and cannot be retained as image buffers.
- struct2tuple keeps its historical dictionary return shape. Byte arrays are
  copied at their full fixed length, preserving embedded NULs. Trim the serial
  number explicitly if your application needs a C-string representation.
- `device.channels` describes reported analog slots and digital capacity.
  It does not discover which IP slots are configured or online.
- startCapture16 remains a deprecated sample name but captures reported analog
  channels serially, with a monotonic deadline and two rotating JPEG paths per
  channel. Duration is still hours. NVR/IP channels require explicit selection.
  It does not create sixteen workers or implement video health analysis.
- Application-specific helpers logger/createDirectory/checkVideoStatus/CThread
  and exitFlag are removed. Applications own logging, storage and scheduling.
- Running pyhik.py directly no longer connects using embedded demo credentials.
  Use examples/snapshot.py with explicit arguments and a password prompt.

This branch is intentionally not a drop-in claim for all old applications.
