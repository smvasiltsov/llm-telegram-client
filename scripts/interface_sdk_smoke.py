from __future__ import annotations

import sys

from interfaces_sdk.validator import validate_adapter_contract


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python3 -m scripts.interface_sdk_smoke <module_path> <interface_id>")
        return 2
    module_path = sys.argv[1].strip()
    interface_id = sys.argv[2].strip()
    errors = validate_adapter_contract(module_path, interface_id)
    if errors:
        print("ERROR")
        for item in errors:
            print(f"- {item}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
