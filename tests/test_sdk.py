"""Offline boundary tests. No vendor binary or device is used."""

import ctypes
import gc
import importlib
import io
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock
import weakref

import hikvision_native as h


class Function:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.owner.calls.append((self.name, args))
        if self.name == "NET_DVR_GetLastError":
            return self.owner.error
        if self.name == "NET_DVR_Login_V30" and self.name not in self.owner.failures:
            info = ctypes.cast(args[-1], h.LPNET_DVR_DEVICEINFO_V30).contents
            info.byStartChan = 5
            info.byChanNum = 4
            info.byStartDChan = 33
            info.byIPChanNum = 2
            self.owner.user_id += 1
            return self.owner.user_id
        if self.name == "NET_DVR_RealPlay_V30" and self.name not in self.owner.failures:
            self.owner.preview_id += 1
            return self.owner.preview_id
        if self.name in self.owner.failures:
            return -1 if self.name in ("NET_DVR_Login_V30", "NET_DVR_RealPlay_V30", "NET_DVR_GetRealPlayerIndex") else 0
        if self.name in self.owner.hooks:
            return self.owner.hooks[self.name](*args)
        return 1


class Native:
    def __init__(self):
        self.calls = []
        self.failures = set()
        self.hooks = {}
        self.error = 9999
        self.user_id = -1  # A successful user handle of zero must be accepted.
        self.preview_id = -1
        for name in h._SIGNATURES:
            setattr(self, name, Function(self, name))

    def names(self):
        return [name for name, _ in self.calls]


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.native = Native()
        self.sdk = h.SDK(_library=self.native)
        self.previous_default = h._default
        h._default = self.sdk

    def tearDown(self):
        self.native.failures.clear()
        self.native.hooks.clear()
        self.sdk.close()
        h._default = self.previous_default
        self.assertIsNone(h.SDK._active)

    def login(self):
        self.sdk.open()
        return self.sdk.login("192.0.2.1", 8000, "admin", "secret")

    def test_import_does_not_load_vendor_sdk_or_make_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-c", "import hikvision_native; print(hikvision_native.__version__)"],
                cwd=tmp,
                env={**os.environ, "PYTHONPATH": str(Path(h.__file__).parent)},
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("0.1.0.dev0", result.stdout)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_windows_types_and_layouts(self):
        self.assertEqual(ctypes.sizeof(h.BOOL), 4)
        self.assertEqual(ctypes.sizeof(h.LONG), 4)
        self.assertEqual(ctypes.sizeof(h.DWORD), 4)
        self.assertEqual(ctypes.sizeof(h.HWND), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(h.NET_DVR_DEVICEINFO_V30), 80)
        if ctypes.sizeof(h.VOIDP) == 8:
            self.assertEqual(ctypes.sizeof(h.NET_DVR_CLIENTINFO), 24)
            self.assertEqual(h.NET_DVR_CLIENTINFO.hPlayWnd.offset, 8)
            self.assertEqual(h.NET_DVR_CLIENTINFO.sMultiCastIP.offset, 16)

    def test_callback_pointer_preserves_buffer_and_pointer_sized_user(self):
        seen = []
        callback = h.CMPFUNC(lambda handle, kind, buf, size, user: seen.append((ctypes.string_at(buf, size), user)))
        data = (h.BYTE * 4)(0, 255, 3, 4)
        user = 0x123456789 if ctypes.sizeof(h.VOIDP) == 8 else 123
        callback(0, 2, data, 4, user)
        self.assertEqual(seen, [(b"\x00\xff\x03\x04", user)])

    def test_distinct_callback_userdata_types(self):
        self.assertIs(h.CMPFUNC._argtypes_[-1], h.VOIDP)
        self.assertIs(h.LEGACY_CMPFUNC._argtypes_[-1], h.DWORD)

    def test_login_encodes_strings_and_accepts_zero(self):
        device = self.login()
        self.assertEqual(device.handle, 0)
        args = next(args for name, args in self.native.calls if name == "NET_DVR_Login_V30")
        self.assertEqual(args[:4], (b"192.0.2.1", 8000, b"admin", b"secret"))

    def test_encoding_is_explicit(self):
        self.sdk.encoding = "ascii"
        self.sdk.open()
        with self.assertRaises(UnicodeEncodeError):
            self.sdk.login("192.0.2.1", 8000, "caf\xe9", "secret")
        self.assertNotIn("NET_DVR_Login_V30", self.native.names())

    def test_invalid_inputs_never_reach_native_login(self):
        self.sdk.open()
        for port in (0, 65536, -1):
            with self.assertRaises(ValueError):
                self.sdk.login("host", port, "user", "password")
        for text in ("", "host\0suffix"):
            with self.assertRaises(ValueError):
                self.sdk.login(text, 8000, "user", "password")
        with self.assertRaises(TypeError):
            self.sdk.login("host", True, "user", "password")
        self.assertNotIn("NET_DVR_Login_V30", self.native.names())

    def test_failed_login_preserves_code_without_credentials(self):
        self.sdk.open()
        self.native.failures.add("NET_DVR_Login_V30")
        self.native.error = 1
        with self.assertRaises(h.SDKError) as result:
            self.sdk.login("host", 8000, "admin", "very-secret")
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(result.exception.operation, "NET_DVR_Login_V30")
        self.assertNotIn("very-secret", str(result.exception))
        self.assertEqual(self.sdk._sessions, {})

    def test_unknown_error_is_actionable(self):
        self.assertIn("9999", h.getErrorMsg(9999))
        self.native.failures.add("NET_DVR_Init")
        with self.assertRaises(h.SDKError) as result:
            self.sdk.open()
        self.assertEqual(result.exception.code, 9999)
        self.assertIsNone(h.SDK._active)

    def test_failed_enter_does_not_cleanup_uninitialized_runtime(self):
        self.native.failures.add("NET_DVR_Init")
        with self.assertRaises(h.SDKError):
            with self.sdk:
                self.fail("must not enter")
        self.assertNotIn("NET_DVR_Cleanup", self.native.names())

    def test_context_cleans_up_after_auth_failure(self):
        self.native.failures.add("NET_DVR_Login_V30")
        with self.assertRaises(h.SDKError):
            with self.sdk:
                self.sdk.login("host", 8000, "u", "p")
        self.assertEqual(self.native.names()[-1], "NET_DVR_Cleanup")

    def test_failed_cleanup_retains_runtime_for_retry(self):
        self.sdk.open()
        self.native.failures.add("NET_DVR_Cleanup")
        with self.assertRaises(h.SDKError):
            self.sdk.close()
        self.assertTrue(self.sdk._open)
        self.assertIs(h.SDK._active, self.sdk)
        self.native.failures.clear()
        self.sdk.close()

    def test_simultaneous_runtime_owners_are_rejected(self):
        self.sdk.open()
        other_native = Native()
        other = h.SDK(_library=other_native)
        with self.assertRaises(h.SDKStateError):
            other.open()
        self.assertEqual(other_native.calls, [])
        self.sdk.close()
        other.open()
        other.close()

    def test_multiple_sessions_and_idempotent_close(self):
        first = self.login()
        second = self.sdk.login("other", 8000, "u", "p")
        first.close()
        first.close()
        self.sdk.close()
        self.sdk.close()
        self.assertTrue(second._closed)
        self.assertEqual(self.native.names().count("NET_DVR_Init"), 1)
        self.assertEqual(self.native.names().count("NET_DVR_Logout"), 2)
        self.assertEqual(self.native.names().count("NET_DVR_Cleanup"), 1)

    def test_runtime_can_reopen(self):
        first = self.login()
        self.sdk.close()
        self.sdk.open()
        with self.assertRaises(h.SDKStateError):
            first.capture_jpeg(5, "out.jpg")
        self.assertEqual(self.native.names().count("NET_DVR_Init"), 2)

    def test_channel_slots_use_start_and_high_byte(self):
        device = self.login()
        self.assertEqual([c.number for c in device.channels], [5, 6, 7, 8, 33, 34])
        device.info.byHighDChanNum = 1
        self.assertEqual(len(device.channels), 262)
        device.info.byStartDChan = 0
        with self.assertRaises(h.SDKStateError):
            _ = device.channels

    def test_jpeg_accepts_path_str_and_bytes(self):
        device = self.login()
        for value in (Path("out.jpg"), "out.jpg", b"out.jpg"):
            self.assertEqual(device.capture_jpeg(5, value), Path("out.jpg"))
        args = next(args for name, args in self.native.calls if name == "NET_DVR_CaptureJPEGPicture")
        self.assertEqual(args[-1], b"out.jpg")
        self.assertEqual(args[:2], (0, 5))

    def test_capture_failure_raises_original_error(self):
        device = self.login()
        self.native.failures.add("NET_DVR_CaptureJPEGPicture")
        with self.assertRaises(h.SDKError) as result:
            device.capture_jpeg(5, "out.jpg")
        self.assertEqual(result.exception.code, 9999)

    def test_closed_session_never_calls_native_capture(self):
        device = self.login()
        device.close()
        with self.assertRaises(h.SDKStateError):
            device.capture_jpeg(5, "out.jpg")
        self.assertNotIn("NET_DVR_CaptureJPEGPicture", self.native.names())

    def test_preview_callback_is_retained_and_stopped_before_logout(self):
        device = self.login()
        callback = h.CMPFUNC(lambda *args: None)
        reference = weakref.ref(callback)
        handle = device.start_preview(h.NET_DVR_CLIENTINFO(5, 0, None, None), callback)
        # Fake call arguments themselves would otherwise retain the callback.
        self.native.calls.clear()
        del callback
        gc.collect()
        self.assertIsNotNone(reference())
        self.sdk.close()
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(self.native.names(), ["NET_DVR_StopRealPlay", "NET_DVR_Logout", "NET_DVR_Cleanup"])
        self.assertEqual(handle, 0)

    def test_failed_stop_retains_callback_and_blocks_logout_and_cleanup(self):
        device = self.login()
        handle = device.start_preview(h.NET_DVR_CLIENTINFO(5, 0, None, None))
        self.native.failures.add("NET_DVR_StopRealPlay")
        with self.assertRaises(h.SDKError):
            self.sdk.close()
        self.assertIn(handle, device._previews)
        self.assertNotIn("NET_DVR_Logout", self.native.names())
        self.assertNotIn("NET_DVR_Cleanup", self.native.names())
        self.native.failures.clear()
        self.sdk.close()

    def test_failure_in_one_session_still_closes_other_sessions(self):
        first = self.login()
        first.start_preview(h.NET_DVR_CLIENTINFO(5, 0, None, None))
        second = self.sdk.login("other", 8000, "u", "p")
        self.native.failures.add("NET_DVR_StopRealPlay")
        with self.assertRaises(h.SDKError):
            self.sdk.close()
        self.assertTrue(second._closed)
        self.assertFalse(first._closed)
        self.assertNotIn("NET_DVR_Cleanup", self.native.names())

    def test_failed_logout_prevents_runtime_cleanup(self):
        device = self.login()
        self.native.failures.add("NET_DVR_Logout")
        with self.assertRaises(h.SDKError):
            self.sdk.close()
        self.assertFalse(device._closed)
        self.assertNotIn("NET_DVR_Cleanup", self.native.names())

    def test_context_preserves_original_exception_when_cleanup_fails(self):
        with self.assertLogs(h.log, level="ERROR"):
            with self.assertRaisesRegex(ValueError, "original"):
                with self.sdk:
                    self.native.failures.add("NET_DVR_Cleanup")
                    raise ValueError("original")
        self.assertTrue(self.sdk._open)

    def test_serialized_capture_finishes_before_shutdown(self):
        device = self.login()
        entered, finish = threading.Event(), threading.Event()
        errors = []

        def capture_hook(*args):
            entered.set()
            if not finish.wait(5):
                raise AssertionError("test synchronization timeout")
            return 1

        def capture():
            try:
                device.capture_jpeg(5, "out.jpg")
            except Exception as exc:
                errors.append(exc)

        self.native.hooks["NET_DVR_CaptureJPEGPicture"] = capture_hook
        worker = threading.Thread(target=capture)
        worker.start()
        self.assertTrue(entered.wait(5))
        closer = threading.Thread(target=self.sdk.close)
        closer.start()
        try:
            self.assertNotIn("NET_DVR_Cleanup", self.native.names())
        finally:
            finish.set()
            worker.join(5)
            closer.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.native.names()[-2:], ["NET_DVR_Logout", "NET_DVR_Cleanup"])

    def test_legacy_capture_returns_true_or_raises(self):
        h.init(io.StringIO())
        handle, info = h.login("host", 8000, "u", "p")
        self.assertTrue(h.captureJPEGPicture(handle, 5, h.NET_DVR_JPEGPARA(2, 2), b"out.jpg", io.StringIO()))
        self.native.failures.add("NET_DVR_CaptureJPEGPicture")
        with self.assertRaises(h.SDKError):
            h.captureJPEGPicture(handle, 5, h.NET_DVR_JPEGPARA(2, 2), "out.jpg")

    def test_legacy_callback_variants_are_not_interchangeable(self):
        device = self.login()
        with self.assertRaises(TypeError):
            device.start_preview(h.NET_DVR_CLIENTINFO(5, 0, None, None), h.LEGACY_CMPFUNC(lambda *args: None))
        handle = h.startRealPlay(device.handle, h.NET_DVR_CLIENTINFO(5, 0, None, None), None, None, True)
        with self.assertRaises(TypeError):
            h.setRealDataCallBack(handle, h.CMPFUNC(lambda *args: None), 0)
        self.assertTrue(h.setRealDataCallBack(handle, lambda *args: None, 0xFFFFFFFF))
        self.assertTrue(h.setRealDataCallBack(handle, None, 0))
        self.assertEqual(len(device._previews[handle]), 5)

    def test_source_checkout_shim_points_to_the_same_api(self):
        # This compatibility shim deliberately does not ship in the wheel.
        shim_path = Path(h.__file__).with_name("pyhik.py")
        if not shim_path.exists():
            self.skipTest("Installed distribution correctly has no checkout shim")
        sys.modules.pop("pyhik", None)
        with self.assertWarns(DeprecationWarning):
            legacy = importlib.import_module("pyhik")
        self.assertIs(legacy.SDK, h.SDK)

    def test_sample_cannot_close_an_existing_runtime(self):
        self.sdk.open()
        with self.assertWarns(DeprecationWarning), self.assertRaises(h.SDKStateError):
            h.startCapture16("host", 8000, "u", "p", 0)
        self.assertTrue(self.sdk._open)
        self.assertNotIn("NET_DVR_Cleanup", self.native.names())

    def test_sample_preserves_capture_error_if_cleanup_also_fails(self):
        self.native.failures.update({"NET_DVR_Login_V30", "NET_DVR_Cleanup"})
        with self.assertLogs(h.log, level="ERROR"):
            with self.assertWarns(DeprecationWarning), self.assertRaises(h.SDKError) as result:
                h.startCapture16("host", 8000, "u", "p", 0)
        self.assertEqual(result.exception.operation, "NET_DVR_Login_V30")

    def test_struct_conversion_copies_full_binary_arrays(self):
        info = h.NET_DVR_DEVICEINFO_V30()
        for i in range(48):
            info.sSerialNumber[i] = 255
        info.sSerialNumber[1] = 0
        result = h.struct2tuple(info)
        self.assertEqual(len(result["sSerialNumber"]), 48)
        self.assertEqual(result["sSerialNumber"][:3], b"\xff\0\xff")
        self.assertEqual(h.struct2tuple(h.NET_DVR_JPEGPARA(2, 1)), {"wPicSize": 2, "wPicQuality": 1})

    def test_capture_sample_no_fixed_sixteen_workers_or_state_leak(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(h.Path, "cwd", return_value=Path(tmp)):
            for _ in range(2):
                with self.assertWarns(DeprecationWarning):
                    h.startCapture16("host", 8000, "u", "p", 0)
                self.assertEqual(sorted(p.name for p in (Path(tmp) / "capture").iterdir()), ["5", "6", "7", "8"])
        self.assertEqual(self.native.names().count("NET_DVR_Init"), 2)
        self.assertEqual(self.native.names().count("NET_DVR_Cleanup"), 2)
        self.assertNotIn("NET_DVR_CaptureJPEGPicture", self.native.names())

    def test_duration_rejects_invalid_values_before_init(self):
        for duration in (-1, float("nan"), float("inf"), True):
            with self.assertWarns(DeprecationWarning), self.assertRaises(ValueError):
                h.startCapture16("host", 8000, "u", "p", duration)
        self.assertEqual(self.native.calls, [])

    def test_setters_validate_and_raise(self):
        self.sdk.open()
        with self.assertRaises(ValueError):
            self.sdk.set_connect_time(100)
        self.native.failures.add("NET_DVR_SetReconnect")
        with self.assertRaises(h.SDKError):
            self.sdk.set_reconnect(5000)

    def test_non_windows_native_execution_is_explicitly_rejected(self):
        with mock.patch.object(h.sys, "platform", "darwin"):
            with self.assertRaisesRegex(h.SDKLoadError, "64-bit Windows"):
                h._load_library("/tmp/HCNetSDK.dll")

    def test_loader_requires_explicit_absolute_path(self):
        with mock.patch.object(h.sys, "platform", "win32"), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(h.SDKLoadError, "HIKVISION_SDK_PATH"):
                h._load_library(None)
            with self.assertRaisesRegex(h.SDKLoadError, "absolute"):
                h._load_library("HCNetSDK.dll")

    def test_missing_native_export_has_useful_error(self):
        del self.native.NET_DVR_Init
        with self.assertRaisesRegex(h.SDKLoadError, "NET_DVR_Init"):
            self.sdk.open()

    def test_loader_rejects_non_pe_and_wrong_architecture_without_loading(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(h.sys, "platform", "win32"):
            dll = Path(tmp) / "HCNetSDK.dll"
            for data in (b"not a DLL", b"MZ" + bytes(58) + struct.pack("<I", 64) + b"PE\0\0\x4c\x01"):
                dll.write_bytes(data)
                with self.assertRaisesRegex(h.SDKLoadError, "Windows x64"):
                    h._load_library(dll)

    def test_loader_uses_absolute_dll_and_closes_directory_on_load_failure(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(h.sys, "platform", "win32"):
            dll = Path(tmp) / "HCNetSDK.dll"
            dll.write_bytes(b"MZ" + bytes(58) + struct.pack("<I", 64) + b"PE\0\0\x64\x86")
            directory = mock.Mock()
            with mock.patch.object(h.os, "add_dll_directory", return_value=directory, create=True) as add_dir:
                with mock.patch.object(h.ctypes, "WinDLL", return_value=self.native, create=True) as load:
                    library, held_directory = h._load_library(Path(tmp))
                    self.assertIs(library, self.native)
                    self.assertIs(held_directory, directory)
                    load.assert_called_once_with(str(dll.resolve()), winmode=0x1100)
                    add_dir.assert_called_once_with(str(dll.resolve().parent))
                    directory.close.assert_not_called()
                with mock.patch.object(h.ctypes, "WinDLL", side_effect=OSError("missing dependency"), create=True):
                    with self.assertRaisesRegex(h.SDKLoadError, "complete matching vendor bundle"):
                        h._load_library(dll)
                    directory.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
