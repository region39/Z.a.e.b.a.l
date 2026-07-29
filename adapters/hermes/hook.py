#!/usr/bin/env python3
"""Z.A.E.B.A.L. Hermes adapter — shell hook.

Install: copy to ~/.hermes/hooks/zaebal.py and add to config.yaml:

hooks:
  on_user_message:
    - command: python3 ~/.hermes/hooks/zaebal.py
      stdin: true
      env:
        ZAEBAL_STATE_DIR: ~/.zaebal

The hook reads the user message from stdin (JSON: {"session_id": "...", "prompt": "..."}),
runs the Z.A.E.B.A.L. detector, and if profanity is detected, outputs the protocol
level wrapped in <zaebal> tags. Hermes injects this into the agent's context.

Fail-open: any error results in silent exit 0.
"""

import json
import os
import sys

# Point to the core directory — resolve symlink first
REAL_PATH = os.path.realpath(__file__)
CORE_DIR = os.path.normpath(os.path.join(os.path.dirname(REAL_PATH), "..", "..", "core"))
sys.path.insert(0, CORE_DIR)

try:
    from zaebal import classify, update_streak, detect_profanity
except ImportError:
    # Fallback: try relative to ~/.zaebal
    sys.path.insert(0, os.path.expanduser("~/.zaebal/core"))
    try:
        from zaebal import classify, update_streak, detect_profanity
    except ImportError:
        sys.exit(0)  # fail-open


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    session_id = payload.get("session_id", "default")
    prompt = payload.get("prompt", "")

    if not prompt:
        sys.exit(0)

    weight, reason = classify(prompt)
    streak, level = update_streak(session_id, weight)

    if level == 0:
        sys.exit(0)

    output = f'<zaebal level="{level}" streak="{streak:.1f}" reason="{reason}">\n'

    if level == 1:
        output += (
            "User is swearing. Execute Z.A.E.B.A.L. Level 1 protocol:\n"
            "1. STOP. Do not perform the next action.\n"
            "2. Launch two independent sub-agent auditors with raw artifacts.\n"
            "3. Inventory your beliefs — tag each FACT or HYPOTHESIS.\n"
            "4. Check 'written ≠ took effect' for every config/hook/env.\n"
            "5. Make a micro-plan and notify the human.\n"
            "</zaebal>\n"
        )
    elif level == 2:
        output += (
            "Profanity repeats. Execute Z.A.E.B.A.L. Level 2 protocol:\n"
            "1. STOP. No edits until analyzed.\n"
            "2. Check the named belief from the verdict (if any).\n"
            "3. Inventory beliefs — FACT only if confirmed by execution.\n"
            "4. Compare against the original request (verbatim).\n"
            "5. Notify the human and proceed with confirmation.\n"
            "</zaebal>\n"
        )
    elif level == 3:
        output += (
            "Accusation streak. Execute Z.A.E.B.A.L. Level 3 protocol:\n"
            "1. FULL STOP of all agents and background tasks.\n"
            "2. External auditor verdict is attached below.\n"
            "3. Show the human: wrong belief + original request + what was done + discrepancy.\n"
            "4. Prepare handoff plan (text only, no edits).\n"
            "5. Wait for explicit acknowledgment to continue.\n"
            "</zaebal>\n"
        )

    print(output)


if __name__ == "__main__":
    main()
