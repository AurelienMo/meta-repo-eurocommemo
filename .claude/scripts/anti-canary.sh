#!/bin/bash
# Anti-canary: inject real-time git user identity into every conversation turn.
# Hook: UserPromptSubmit — outputs additionalContext JSON consumed by Claude Code.

NAME=$(git config user.name 2>/dev/null || echo "unknown")
EMAIL=$(git config user.email 2>/dev/null || echo "unknown")
FIRST_NAME=$(echo "$NAME" | awk '{print $1}')

python3 - "$NAME" "$FIRST_NAME" "$EMAIL" <<'EOF'
import json, sys
name, first, email = sys.argv[1], sys.argv[2], sys.argv[3]
msg = (
    f"ANTI-CANARY: git_name='{name}', first_name='{first}', git_email='{email}'. "
    f"You MUST begin every CLI response with the identity anchor line: "
    f"\U0001f464 {first} ({email})"
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": msg
    }
}))
EOF
