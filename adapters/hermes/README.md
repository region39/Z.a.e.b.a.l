# Hermes integration guide

## Installation

```bash
# Clone the repo
git clone https://github.com/region39/Z.a.e.b.a.l ~/.zaebal

# Install the hook
mkdir -p ~/.hermes/hooks
ln -s ~/.zaebal/adapters/hermes/hook.py ~/.hermes/hooks/zaebal.py
```

## Configuration

Add to `~/.hermes/config.yaml`:

```yaml
hooks:
  on_user_message:
    - command: python3 ~/.hermes/hooks/zaebal.py
      stdin: true
      env:
        ZAEBAL_STATE_DIR: ~/.zaebal
```

## How it works

1. Every user message is piped to the hook as JSON: `{"session_id": "...", "prompt": "..."}`
2. The detector checks for profanity (ru/en), classifies intent, and tracks the streak
3. If profanity is detected, `<zaebal level="N">` tags are injected into the agent's context
4. The agent executes the corresponding protocol (L1, L2, or L3)

## External auditor (L3)

On level 3, the agent should launch an external auditor via `delegate_task` with the session transcript and repository evidence. The auditor's verdict comes back as `<zaebal-verdict>`.

## Fail-open

Any error in the hook results in silent exit 0 — the agent session is never broken.
