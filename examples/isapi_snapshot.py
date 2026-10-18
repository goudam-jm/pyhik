"""Read-only HTTP example. Install the isapi extra before running."""

import argparse
from getpass import getpass
from pathlib import Path

from hikvision_isapi import ISAPIClient


def main():
    parser = argparse.ArgumentParser(description="Fetch a JPEG using an explicit ISAPI streaming ID")
    parser.add_argument("--url", required=True, help="HTTP(S) origin, e.g. https://camera.example")
    parser.add_argument("--username", required=True)
    parser.add_argument("--stream-id", required=True, help="Device-reported streaming ID, e.g. 101")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ca-bundle", help="CA bundle file for a private device certificate")
    args = parser.parse_args()
    with ISAPIClient(args.url, args.username, getpass("Device password: "), verify=args.ca_bundle or True) as client:
        print(client.get_device_info())
        picture = client.get_snapshot(args.stream_id)
        # Refuse accidental overwrite of an existing application file.
        with args.output.open("xb") as output:
            output.write(picture)
        print(args.output)


if __name__ == "__main__":
    main()
