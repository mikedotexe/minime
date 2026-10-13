#!/usr/bin/env python3
"""Preview exact human-letter bytes; explicitly confirm their SHA-256 to submit.

Preview: python3 scripts/human_letter.py preview --source LETTER.txt \
    --sender mike --message-id ID --thread-id THREAD
Write: repeat with 'write', --confirm-sha256 DIGEST and --workspace WORKSPACE.
Preview stdout is exactly the proposed file; SHA-256 and byte count go to stderr.
The source is never converted, moved, deleted, or modified. There is no default
workspace, automatic sender inference, runtime import, or private-content log.
"""

import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minime_autonomy.human_letters import (  # noqa: E402
    HumanLetterError, preview_letter, submit_letter,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "write"):
        child = commands.add_parser(command)
        child.add_argument("--source", required=True, help="Existing plain UTF-8 regular file")
        child.add_argument("--sender", required=True, choices=("mike", "steward"))
        child.add_argument("--message-id", required=True)
        child.add_argument("--thread-id", required=True)
        if command == "write":
            child.add_argument("--workspace", required=True, help="Existing output workspace")
            child.add_argument("--confirm-sha256", required=True, help="SHA-256 from preview")
    args = parser.parse_args(argv)
    try:
        letter = preview_letter(args.source, sender=args.sender,
                                message_id=args.message_id, thread_id=args.thread_id)
        if args.command == "preview":
            sys.stdout.buffer.write(letter.content)
            sys.stdout.buffer.flush()
            print(f"SHA-256: {letter.sha256}\nBytes: {len(letter.content)}", file=sys.stderr)
        else:
            result = submit_letter(letter, workspace=args.workspace,
                                   confirm_sha256=args.confirm_sha256)
            status = "Created" if result.created else "Previously published (not republished; consumption unknown)"
            print(f"{status}: {result.path}\nSHA-256: {result.sha256}")
        return 0
    except HumanLetterError as exc:
        print(f"human_letter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
