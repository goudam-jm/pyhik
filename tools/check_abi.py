"""Compare vendor-header probe JSON with the installed binding (no DLL load)."""

import argparse
import ctypes
import json

import hikvision_native as h


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe_json")
    args = parser.parse_args()
    with open(args.probe_json, encoding="utf-8") as file:
        actual = json.load(file)
    expected = {
        name: ctypes.sizeof(getattr(h, name))
        for name in (
            "BOOL",
            "LONG",
            "DWORD",
            "HWND",
            "NET_DVR_DEVICEINFO_V30",
            "NET_DVR_CLIENTINFO",
            "NET_DVR_JPEGPARA",
        )
    }
    for structure, fields in (
        ("NET_DVR_CLIENTINFO", ("lChannel", "lLinkMode", "hPlayWnd", "sMultiCastIP")),
        ("NET_DVR_DEVICEINFO_V30", ("byStartChan", "byStartDChan", "byHighDChanNum", "bySupport4")),
    ):
        for field in fields:
            expected[f"{structure}.{field}"] = getattr(getattr(h, structure), field).offset
    mismatches = [
        f"{key}: vendor={actual.get(key)!r}, binding={value}"
        for key, value in expected.items()
        if actual.get(key) != value
    ]
    if mismatches:
        raise SystemExit("ABI mismatch:\n" + "\n".join(mismatches))
    print("Sizes and offsets match. Native/device behavior still requires integration testing.")


if __name__ == "__main__":
    main()
