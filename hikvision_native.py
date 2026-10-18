"""Experimental maintenance of the Windows HCNetSDK V30 binding.

Importing this module never loads vendor binaries or contacts devices.
Native compatibility is unverified; see docs/compatibility.md.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import struct
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

__author__ = "gmuralit"
__version__ = "0.1.0.dev0"
log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

# Windows ABI types, even when imported on a non-Windows test host.
BOOL = ctypes.c_int32
INT = ctypes.c_int32
LONG = ctypes.c_int32
DWORD = ctypes.c_uint32
BYTE = ctypes.c_ubyte
WORD = ctypes.c_uint16
CHARP = ctypes.c_char_p
VOIDP = ctypes.c_void_p
HWND = ctypes.c_void_p
SERIALNO_LEN = 48
STREAM_ID_LEN = 32
_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
CMPFUNC = _CALLBACK(None, LONG, DWORD, ctypes.POINTER(BYTE), DWORD, VOIDP)
# SetRealDataCallBack uses DWORD user data, unlike RealPlay_V30's void *.
LEGACY_CMPFUNC = _CALLBACK(None, LONG, DWORD, ctypes.POINTER(BYTE), DWORD, DWORD)


class NET_DVR_DEVICEINFO_V30(ctypes.Structure):
    _fields_ = [
        ("sSerialNumber", BYTE * SERIALNO_LEN),
        ("byAlarmInPortNum", BYTE),
        ("byAlarmOutPortNum", BYTE),
        ("byDiskNum", BYTE),
        ("byDVRType", BYTE),
        ("byChanNum", BYTE),
        ("byStartChan", BYTE),
        ("byAudioChanNum", BYTE),
        ("byIPChanNum", BYTE),
        ("byZeroChanNum", BYTE),
        ("byMainProto", BYTE),
        ("bySubProto", BYTE),
        ("bySupport", BYTE),
        ("bySupport1", BYTE),
        ("bySupport2", BYTE),
        ("wDevType", WORD),
        ("bySupport3", BYTE),
        ("byMultiStreamProto", BYTE),
        ("byStartDChan", BYTE),
        ("byStartDTalkChan", BYTE),
        ("byHighDChanNum", BYTE),
        ("bySupport4", BYTE),
        ("byRes2", BYTE * 10),
    ]


LPNET_DVR_DEVICEINFO_V30 = ctypes.POINTER(NET_DVR_DEVICEINFO_V30)


class NET_DVR_CLIENTINFO(ctypes.Structure):
    _fields_ = [("lChannel", LONG), ("lLinkMode", LONG), ("hPlayWnd", HWND), ("sMultiCastIP", CHARP)]


LPNET_DVR_CLIENTINFO = ctypes.POINTER(NET_DVR_CLIENTINFO)


class NET_DVR_PREVIEWINFO(ctypes.Structure):
    _fields_ = [
        ("lChannel", LONG),
        ("dwStreamType", DWORD),
        ("dwLinkMode", DWORD),
        ("hPlayWnd", HWND),
        ("bBlocked", DWORD),
        ("bPassbackRecord", DWORD),
        ("byPreviewMode", BYTE),
        ("byStreamID", BYTE * STREAM_ID_LEN),
        ("byProtoType", BYTE),
        ("byRes", BYTE * 222),
    ]


LPNET_DVR_PREVIEWINFO = ctypes.POINTER(NET_DVR_PREVIEWINFO)


class NET_DVR_SDKLOCAL_CFG(ctypes.Structure):
    _fields_ = [
        ("byEnableAbilityParse", BYTE),
        ("byVoiceComMode", BYTE),
        ("byRes", BYTE * 382),
        ("byProtectKey", BYTE * 128),
    ]


LPNET_DVR_SDKLOCAL_CFG = ctypes.POINTER(NET_DVR_SDKLOCAL_CFG)


class NET_DVR_JPEGPARA(ctypes.Structure):
    _fields_ = [("wPicSize", WORD), ("wPicQuality", WORD)]


LPNET_DVR_JPEGPARA = ctypes.POINTER(NET_DVR_JPEGPARA)

_ERROR_CODES = {
    0: "No error",
    1: "Authentication failed",
    3: "SDK is not initialized",
    5: "Device connection limit exceeded",
    7: "Device connection failed",
    8: "Network send failed",
    9: "Network receive failed",
    10: "Receive timeout",
    12: "API calling order error",
    17: "Invalid SDK parameter",
    34: "Unable to create file",
    84: "Unable to load StreamTransClient",
}


class SDKError(RuntimeError):
    """A native failure with its original operation and numeric error code."""

    def __init__(self, operation: str, code: int):
        self.operation = operation
        self.code = int(code)
        super().__init__(f"{operation}: {getErrorMsg(self.code)} (code {self.code})")


class SDKLoadError(RuntimeError):
    """Unsupported host or missing/incompatible SDK bundle."""


class SDKStateError(RuntimeError):
    """An operation would violate resource ownership or lifecycle ordering."""


def getErrorMsg(errorCode: int) -> str:
    return _ERROR_CODES.get(errorCode, f"Unknown SDK error {errorCode}")


def _encoded(value: str | bytes, label: str, encoding: str) -> bytes:
    if isinstance(value, str):
        result = value.encode(encoding)
    elif isinstance(value, bytes):
        result = value
    else:
        raise TypeError(f"{label} must be str or bytes")
    if not result or b"\0" in result:
        raise ValueError(f"{label} must be nonempty and contain no NUL bytes")
    return result


def _integer(value: int, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _load_library(path: str | os.PathLike[str] | None):
    if sys.platform != "win32" or ctypes.sizeof(VOIDP) != 8:
        raise SDKLoadError("Native execution currently requires 64-bit Windows Python")
    selected = path if path is not None else os.environ.get("HIKVISION_SDK_PATH")
    if not selected:
        raise SDKLoadError("Set HIKVISION_SDK_PATH or pass an absolute SDK DLL path")
    dll = Path(selected)
    if not dll.is_absolute():
        raise SDKLoadError("SDK path must be absolute; ambient DLL lookup is disabled")
    dll = dll.resolve()
    if dll.is_dir():
        dll = dll / "HCNetSDK.dll"
    if not dll.is_file():
        raise SDKLoadError(f"SDK DLL does not exist: {dll}")
    # Reject an obviously wrong architecture before asking Windows to load it.
    try:
        with dll.open("rb") as binary:
            if binary.read(2) != b"MZ":
                raise ValueError("not a PE image")
            binary.seek(0x3C)
            pe_offset = struct.unpack("<I", binary.read(4))[0]
            binary.seek(pe_offset)
            if binary.read(4) != b"PE\0\0" or binary.read(2) != b"\x64\x86":
                raise ValueError("not an AMD64 PE image")
    except (OSError, ValueError, struct.error) as exc:
        raise SDKLoadError("Expected a Windows x64 HCNetSDK DLL") from exc
    directory = os.add_dll_directory(str(dll.parent))
    try:
        library = ctypes.WinDLL(str(dll), winmode=0x1100)
    except OSError as exc:
        directory.close()
        raise SDKLoadError("SDK load failed; supply the complete matching vendor bundle") from exc
    # Keep the dependency directory registered for lazy vendor component loads.
    return library, directory


_SIGNATURES = {
    "NET_DVR_Init": ([], BOOL),
    "NET_DVR_Cleanup": ([], BOOL),
    "NET_DVR_GetSDKVersion": ([], DWORD),
    "NET_DVR_GetLastError": ([], DWORD),
    "NET_DVR_SetConnectTime": ([DWORD, DWORD], BOOL),
    "NET_DVR_SetReconnect": ([DWORD, BOOL], BOOL),
    "NET_DVR_Login_V30": ([CHARP, WORD, CHARP, CHARP, LPNET_DVR_DEVICEINFO_V30], LONG),
    "NET_DVR_Logout": ([LONG], BOOL),
    "NET_DVR_RealPlay_V30": ([LONG, LPNET_DVR_CLIENTINFO, CMPFUNC, VOIDP, BOOL], LONG),
    "NET_DVR_StopRealPlay": ([LONG], BOOL),
    "NET_DVR_GetRealPlayerIndex": ([LONG], INT),
    "NET_DVR_CaptureJPEGPicture": ([LONG, LONG, LPNET_DVR_JPEGPARA, CHARP], BOOL),
    "NET_DVR_SetRealDataCallBack": ([LONG, LEGACY_CMPFUNC, DWORD], BOOL),
}


@dataclass(frozen=True)
class Channel:
    """Reported channel slot, not proof that an IP camera is online/configured."""

    number: int
    kind: str


def channel_slots(info: NET_DVR_DEVICEINFO_V30) -> tuple[Channel, ...]:
    analog = tuple(Channel(i, "analog") for i in range(info.byStartChan, info.byStartChan + info.byChanNum))
    digital_count = info.byIPChanNum + 256 * info.byHighDChanNum
    if digital_count and not info.byStartDChan:
        raise SDKStateError("Device reported digital channel capacity without a start channel")
    digital = tuple(Channel(i, "digital") for i in range(info.byStartDChan, info.byStartDChan + digital_count))
    return analog + digital


class SDK:
    """Owns one process-wide native runtime and all sessions opened through it.

    Multiple sessions are allowed; simultaneous SDK owners are deliberately
    rejected. Public operations are serialized. `_library` is a test seam.
    """

    _process_lock = threading.RLock()
    _active = None

    def __init__(self, path: str | os.PathLike[str] | None = None, *, encoding: str = "utf-8", _library: Any = None):
        self.path = path
        self.encoding = encoding
        self._library = _library
        self._directory = None
        self._functions: dict[str, Any] = {}
        self._sessions: dict[int, Device] = {}
        self._open = False

    def _fn(self, name: str):
        if self._library is None:
            self._library, self._directory = _load_library(self.path)
        if name not in self._functions:
            try:
                function = getattr(self._library, name)
            except AttributeError as exc:
                raise SDKLoadError(f"Vendor library does not export {name}") from exc
            function.argtypes, function.restype = _SIGNATURES[name]
            self._functions[name] = function
        return self._functions[name]

    def _require_open(self):
        if not self._open:
            raise SDKStateError("SDK is closed; use 'with SDK(...) as sdk'")

    def _failure(self, operation: str):
        # Read before logging/cleanup or another native call can overwrite it.
        return SDKError(operation, self._fn("NET_DVR_GetLastError")())

    def _check(self, operation: str, *args):
        if not self._fn(operation)(*args):
            raise self._failure(operation)

    def open(self) -> SDK:
        with SDK._process_lock:
            if self._open:
                return self
            if SDK._active is not None:
                raise SDKStateError("Another SDK owns the process runtime; share that instance")
            self._check("NET_DVR_Init")
            self._open = True
            SDK._active = self
            return self

    def close(self) -> None:
        with SDK._process_lock:
            if not self._open:
                return
            first_error = None
            for session in tuple(self._sessions.values()):
                try:
                    session.close()
                except Exception as exc:
                    first_error = first_error or exc
            if first_error:
                # Do not clean up a runtime still owning native handles.
                raise first_error
            self._check("NET_DVR_Cleanup")
            self._open = False
            SDK._active = None
            # DLL objects remain loaded, so retain their search directory too.

    def __enter__(self) -> SDK:
        return self.open()

    def __exit__(self, exc_type, exc, traceback):
        _exit_close(self, exc)

    def login(self, host: str | bytes, port: int, username: str | bytes, password: str | bytes) -> Device:
        host_bytes = _encoded(host, "host", self.encoding)
        user_bytes = _encoded(username, "username", self.encoding)
        password_bytes = _encoded(password, "password", self.encoding)
        _integer(port, "port", 1, 65535)
        with SDK._process_lock:
            self._require_open()
            info = NET_DVR_DEVICEINFO_V30()
            handle = self._fn("NET_DVR_Login_V30")(host_bytes, port, user_bytes, password_bytes, ctypes.byref(info))
            if handle == -1:
                raise self._failure("NET_DVR_Login_V30")
            device = Device(self, handle, info)
            self._sessions[handle] = device
            return device

    def set_connect_time(self, timeout_ms: int, attempts: int = 1) -> None:
        _integer(timeout_ms, "timeout_ms", 300, 75000)
        _integer(attempts, "attempts", 1, 0xFFFFFFFF)
        with SDK._process_lock:
            self._require_open()
            self._check("NET_DVR_SetConnectTime", timeout_ms, attempts)

    def set_reconnect(self, interval_ms: int, enabled: bool = True) -> None:
        _integer(interval_ms, "interval_ms", 1, 0xFFFFFFFF)
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        with SDK._process_lock:
            self._require_open()
            self._check("NET_DVR_SetReconnect", interval_ms, enabled)


def _exit_close(resource, original_error):
    try:
        resource.close()
    except Exception:
        if original_error is None:
            raise
        log.exception("Native resource cleanup failed; retaining handles for a retry")


class Device:
    """Logged-in device; owns previews and serializes native operations via SDK."""

    def __init__(self, sdk: SDK, handle: int, info: NET_DVR_DEVICEINFO_V30):
        self.sdk = sdk
        self.handle = handle
        self.info = info
        self._closed = False
        self._previews: dict[int, list[Any]] = {}

    def _require_open(self):
        self.sdk._require_open()
        if self._closed:
            raise SDKStateError("Device session is closed")

    @property
    def channels(self) -> tuple[Channel, ...]:
        return channel_slots(self.info)

    def capture_jpeg(
        self, channel: int, destination: str | bytes | os.PathLike[str], *, size: int = 2, quality: int = 2
    ) -> Path:
        """Save a JPEG or raise SDKError. Parent directory must already exist.

        The path is encoded with SDK.encoding for this legacy narrow-char API.
        Encoding acceptance and image parameters depend on device/SDK versions.
        """
        _integer(channel, "channel", 1, 0x7FFFFFFF)
        _integer(size, "size", 0, 65535)
        _integer(quality, "quality", 0, 2)
        raw_path = os.fspath(destination)
        path_bytes = _encoded(raw_path, "destination", self.sdk.encoding)
        result_path = Path(raw_path.decode(self.sdk.encoding) if isinstance(raw_path, bytes) else raw_path)
        params = NET_DVR_JPEGPARA(size, quality)
        with SDK._process_lock:
            self._require_open()
            self.sdk._check("NET_DVR_CaptureJPEGPicture", self.handle, channel, ctypes.byref(params), path_bytes)
            return result_path

    def start_preview(self, info: NET_DVR_CLIENTINFO, callback=None, user_data=None, blocked: bool = True) -> int:
        """Start raw native preview; callback receives borrowed buffer memory.

        Callback must return promptly, must not call this SDK, and must copy
        the buffer before retaining it. No decoded-frame API is provided.
        """
        if not isinstance(info, NET_DVR_CLIENTINFO):
            raise TypeError("info must be NET_DVR_CLIENTINFO")
        if isinstance(callback, LEGACY_CMPFUNC):
            raise TypeError("RealPlay_V30 requires CMPFUNC (pointer-sized user data)")
        callback_ref = (
            callback if isinstance(callback, CMPFUNC) else CMPFUNC(callback) if callback is not None else CMPFUNC()
        )
        with SDK._process_lock:
            self._require_open()
            handle = self.sdk._fn("NET_DVR_RealPlay_V30")(
                self.handle, ctypes.byref(info), callback_ref, user_data, blocked
            )
            if handle == -1:
                raise self.sdk._failure("NET_DVR_RealPlay_V30")
            # Keep callbacks and pointed-to multicast input alive through stop.
            self._previews[handle] = [callback_ref, info, user_data]
            return handle

    def stop_preview(self, handle: int) -> None:
        with SDK._process_lock:
            self._require_open()
            if handle not in self._previews:
                raise SDKStateError("Preview is not owned by this device")
            self.sdk._check("NET_DVR_StopRealPlay", handle)
            del self._previews[handle]

    def close(self) -> None:
        with SDK._process_lock:
            if self._closed:
                return
            first_error = None
            for handle in tuple(self._previews):
                try:
                    self.stop_preview(handle)
                except Exception as exc:
                    first_error = first_error or exc
            if first_error:
                raise first_error
            self.sdk._check("NET_DVR_Logout", self.handle)
            self._closed = True
            del self.sdk._sessions[self.handle]

    def __enter__(self) -> Device:
        self._require_open()
        return self

    def __exit__(self, exc_type, exc, traceback):
        _exit_close(self, exc)


# Source-checkout compatibility functions. New users should use SDK/Device.
_default = SDK()


def _message(file_ptr: TextIO | None, message: str):
    log.info(message)
    if file_ptr is not None:
        print(message, file=file_ptr)


def init(filePtr=None):
    _default.open()
    _message(filePtr, "SDK initialized")


def release(filePtr=None):
    _default.close()
    _message(filePtr, "SDK released")


def getSDKVersion():
    with SDK._process_lock:
        _default._require_open()
        return hex(_default._fn("NET_DVR_GetSDKVersion")())


def getLastError():
    with SDK._process_lock:
        _default._require_open()
        return _default._fn("NET_DVR_GetLastError")()


def setConnectTime(timeout, attemptCount, filePtr=None):
    _default.set_connect_time(timeout, attemptCount)


def setReconnect(interval, enableReconnect, filePtr=None):
    _default.set_reconnect(interval, bool(enableReconnect))


def login(dIP, dPort, username, password, filePtr=None):
    device = _default.login(dIP, dPort, username, password)
    _message(filePtr, "Device login succeeded")
    return device.handle, device.info


def _device(user_id):
    _default._require_open()
    try:
        return _default._sessions[user_id]
    except KeyError as exc:
        raise SDKStateError("Unknown or closed device session") from exc


def logout(userId, filePtr=None):
    with SDK._process_lock:
        _device(userId).close()


def captureJPEGPicture(userId, channelNo, jpegParam, fileName, filePtr=None):
    with SDK._process_lock:
        _device(userId).capture_jpeg(channelNo, fileName, size=jpegParam.wPicSize, quality=jpegParam.wPicQuality)
        _message(filePtr, "Picture captured successfully")
        return True


def startRealPlay(userId, ipClientInfo, realDataCbk, userData, blocked):
    with SDK._process_lock:
        return _device(userId).start_preview(ipClientInfo, realDataCbk, userData, bool(blocked))


def _preview_owner(handle):
    _default._require_open()
    for device in _default._sessions.values():
        if handle in device._previews:
            return device
    raise SDKStateError("Unknown or closed preview")


def stopRealPlay(realHandle):
    with SDK._process_lock:
        _preview_owner(realHandle).stop_preview(realHandle)
        return True


def getRealPlayerIndex(realHandle):
    with SDK._process_lock:
        _preview_owner(realHandle)
        index = _default._fn("NET_DVR_GetRealPlayerIndex")(realHandle)
        if index == -1:
            raise _default._failure("NET_DVR_GetRealPlayerIndex")
        return index


def setRealDataCallBack(lRealHandle, cbRealDataCbk, dwUser):
    _integer(dwUser, "dwUser", 0, 0xFFFFFFFF)
    if isinstance(cbRealDataCbk, CMPFUNC):
        raise TypeError("SetRealDataCallBack requires LEGACY_CMPFUNC (DWORD user data)")
    callback_ref = (
        cbRealDataCbk
        if isinstance(cbRealDataCbk, LEGACY_CMPFUNC)
        else LEGACY_CMPFUNC(cbRealDataCbk)
        if cbRealDataCbk is not None
        else LEGACY_CMPFUNC()
    )
    with SDK._process_lock:
        owner = _preview_owner(lRealHandle)
        _default._check("NET_DVR_SetRealDataCallBack", lRealHandle, callback_ref, dwUser)
        # Retain all replaced callbacks until StopRealPlay confirms shutdown.
        owner._previews[lRealHandle].append(callback_ref)
        return True


def struct2tuple(value):
    """Historical name: return a dict, copying arrays without C-string overreads."""
    if not isinstance(value, ctypes.Structure):
        raise TypeError("value must be a ctypes Structure")
    result = {}
    for field in value._fields_:
        name = field[0]
        item = getattr(value, name)
        result[name] = (
            bytes(item)
            if isinstance(item, ctypes.Array) and item._type_ is BYTE
            else tuple(item)
            if isinstance(item, ctypes.Array)
            else item
        )
    return result


def startCapture16(ip, port, username, password, duration):
    """Deprecated serial capture sample; duration retains its historical hours unit.

    Capture analog slots reported by the device. Digital capacity alone cannot
    establish which IP channels are configured; select those explicitly instead.
    """
    warnings.warn("Use SDK/Device.capture_jpeg; startCapture16 is a legacy example", DeprecationWarning, stacklevel=2)
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("duration must be finite, nonnegative hours")
    with SDK._process_lock:
        if _default._open:
            raise SDKStateError("The legacy capture sample requires its own runtime lifetime")
        init()
    try:
        user_id, info = login(ip, port, username, password)
        channels = [slot.number for slot in channel_slots(info) if slot.kind == "analog"]
        if not channels:
            raise SDKStateError("No analog channels reported; choose digital channels explicitly")
        root = Path.cwd() / "capture"
        for channel in channels:
            (root / str(channel)).mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + duration * 3600
        sequence = 0
        while time.monotonic() < deadline:
            for channel in channels:
                if time.monotonic() >= deadline:
                    break
                captureJPEGPicture(
                    user_id, channel, NET_DVR_JPEGPARA(2, 2), root / str(channel) / f"{channel}_{sequence % 2}.jpeg"
                )
            sequence += 1
            time.sleep(min(0.18, max(0, deadline - time.monotonic())))
    except BaseException as exc:
        _exit_close(_default, exc)
        raise
    else:
        release()


__all__ = [
    "SDK",
    "Device",
    "Channel",
    "SDKError",
    "SDKLoadError",
    "SDKStateError",
    "channel_slots",
    "BOOL",
    "INT",
    "LONG",
    "DWORD",
    "BYTE",
    "WORD",
    "CHARP",
    "VOIDP",
    "HWND",
    "CMPFUNC",
    "LEGACY_CMPFUNC",
    "NET_DVR_DEVICEINFO_V30",
    "NET_DVR_CLIENTINFO",
    "NET_DVR_PREVIEWINFO",
    "NET_DVR_SDKLOCAL_CFG",
    "NET_DVR_JPEGPARA",
    "LPNET_DVR_DEVICEINFO_V30",
    "LPNET_DVR_CLIENTINFO",
    "LPNET_DVR_PREVIEWINFO",
    "LPNET_DVR_SDKLOCAL_CFG",
    "LPNET_DVR_JPEGPARA",
    "init",
    "release",
    "getSDKVersion",
    "getLastError",
    "getErrorMsg",
    "setConnectTime",
    "setReconnect",
    "login",
    "logout",
    "captureJPEGPicture",
    "startRealPlay",
    "stopRealPlay",
    "getRealPlayerIndex",
    "setRealDataCallBack",
    "struct2tuple",
    "startCapture16",
]
