"""Explicit opt-in device example; install the checkout before running."""

import argparse
from getpass import getpass
from pathlib import Path

from hikvision_native import SDK


def main():
    parser = argparse.ArgumentParser(description="Capture one JPEG using a supplied native SDK")
    parser.add_argument("--sdk", required=True, type=Path, help="Absolute path to HCNetSDK.dll")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--username", required=True)
    parser.add_argument("--channel", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with SDK(args.sdk) as sdk:
        with sdk.login(args.host, args.port, args.username, getpass("Device password: ")) as device:
            print(device.capture_jpeg(args.channel, args.output))


if __name__ == "__main__":
    main()
