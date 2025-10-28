import argparse
import logging
import os
import sys

from mod_root_zip import install_zip


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Install Sims 4 mods from a ZIP archive using deterministic mod-root rules.",
    )
    parser.add_argument("zip", help="Path to the .zip archive")
    parser.add_argument(
        "--mods-root",
        required=True,
        help="Destination Mods/ folder (absolute or relative)",
    )
    parser.add_argument(
        "--include-extras",
        action="store_true",
        help="Also copy non-essential files (readme/images/docs)",
    )
    parser.add_argument(
        "--log",
        default="INFO",
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO))

    z = os.path.abspath(args.zip)
    mods = os.path.abspath(args.mods_root)

    try:
        dest = install_zip(z, mods, include_extras=args.include_extras)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

