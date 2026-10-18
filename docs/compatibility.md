# Compatibility and release evidence

## Current status

Python baseline: 3.11+. All operating systems can import and run offline tests.
Native execution is gated to Windows x64; **no SDK version, recorder, camera,
firmware, or operating-system combination has yet passed integration testing**.

The binding retains the V30 device-info layout from the historical repository
(including reserved tail bytes), models the Windows ABI explicitly, and corrects
CLIENTINFO and callback definitions against Hikvision's published declarations:

- https://open.hikvision.com/hardware/structures/NET_DVR_DEVICEINFO_V30.html
- https://open.hikvision.com/hardware/structures/NET_DVR_CLIENTINFO.html
- https://open.hikvision.com/hardware/definitions/NET_DVR_RealPlay_V30.html
- https://open.hikvision.com/hardware/definitions/NET_DVR_SetRealDataCallBack.html

These are references, not a version-pinned bundle certification. Historical
PREVIEWINFO/SDKLOCAL_CFG types remain for source compatibility but no operation
in this maintenance pass uses them or claims their compatibility with new SDKs.
Do not assume ctypes.c_long or this Windows HWND definition port directly to
Linux. Native Linux/macOS/ARM support is outside this pass.

## ABI probe before native use

Obtain vendor headers and DLLs from the **same approved SDK bundle**. In an x64
Visual Studio developer prompt, after installing this project into your Python
environment:

```console
cl /I C:\vendor\SDK\include tools\abi_probe.c /Fe:abi_probe.exe
abi_probe.exe > abi.json
python tools/check_abi.py abi.json
```

The checker compares native sizes and relevant field offsets to ctypes, exiting
nonzero on mismatch. It does not load a DLL or validate function behavior. A
passing probe is necessary, but not sufficient: record the exact SDK version,
DLL hash, platform, device model and firmware for the subsequent device tests.
No probe was compiled against vendor headers during this hardware-free pass.

## Device checklist (all pending)

1. Load the complete vendor bundle from an explicit absolute path; verify
   diagnostics for missing dependencies and wrong architecture.
2. Authenticate successfully, reject incorrect credentials, exercise timeouts,
   and check returned analog/digital channel mapping against device settings.
3. Capture JPEG on a valid channel and test unavailable channels, unsupported
   parameters, unwritable paths, non-ASCII paths/credentials and disk-full cases.
4. Receive a native preview callback with intact binary bytes and user data;
   confirm borrowed-buffer ownership and stop completion semantics.
5. Repeatedly open/close sessions and previews, including failures and device
   disconnects; verify stop → logout → cleanup and stable memory over a long run.
6. Verify callback replacement and disabling with the legacy DWORD API. Exercise
   a cleanup failure and retry without discarding handles or callbacks.
7. Publish observed results only for the tested model/firmware/OS/SDK combination.

A loaner or contributor with equipment can provide evidence. Do not commit
credentials, real camera addresses, serial numbers, images of people or
unredacted vendor logs. Use minimum-privilege test credentials and isolated
fixtures. The SDK has no claimed TLS/transport-security enhancement: it delegates
native transport behavior to the vendor bundle.
