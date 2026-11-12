"""Generate a test profile from pinned upstream Docker rules plus pivot_root."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


SOURCE = (
    "https://raw.githubusercontent.com/moby/profiles/"
    "6049e40058759e8a1673ac1090ec6a7e36b9c9bd/seccomp/default.json"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow", action="append", default=[], help="Extra syscall")
    args = parser.parse_args()
    with urlopen(SOURCE, timeout=30) as response:
        source = response.read()
    profile = json.loads(source)
    profile["syscalls"].append(
        {"names": ["pivot_root", *args.allow], "action": "SCMP_ACT_ALLOW"}
    )
    # Exclusive creation prevents overwriting an existing policy.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(profile, output, indent=2)
        output.write("\n")
    print(f"Upstream SHA256: {hashlib.sha256(source).hexdigest()}")
    print(f"Profile: {args.output}")


if __name__ == "__main__":
    main()
