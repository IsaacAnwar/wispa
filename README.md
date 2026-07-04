# wispa

A local, free Wispr Flow: hold **Fn**, speak, release — polished text appears at your cursor in whatever app you're in. Everything runs on-device.

## How it works

```
hold Fn ──▶ record mic (16kHz)
release ──▶ Parakeet V3 ASR (MLX, on-device, ~100ms)
        ──▶ skip-gate: no fillers/corrections detected? insert raw (0ms)
        ──▶ else qwen3:4b-instruct via Ollama (strips "um"s, applies
            self-corrections, fixes domain terms from [dictionary]);
            long dictations split into parallel chunks, output streamed
        ──▶ streamed to the cursor via macOS Accessibility API as it
            generates (clipboard + Cmd+V fallback for non-AX apps)
```

First text appears ~300ms after you release the key. If Ollama isn't running you still get the raw Parakeet transcript (which already has punctuation) — cleanup just switches back on when Ollama is up.

For parallel chunk cleanup, the Ollama server needs `OLLAMA_NUM_PARALLEL=4`
(set via its launchd plist / environment; without it chunks serialize).

## Setup

```bash
cd ~/Desktop/tism/wispa
uv sync                      # creates .venv with Python 3.12 + all deps
brew install ollama          # if not already
brew services start ollama
ollama pull qwen3:4b-instruct
```

### Permissions (one-time)

1. **Accessibility** — System Settings → Privacy & Security → Accessibility → add your terminal app (Terminal/iTerm/Ghostty). Needed for the Fn event tap AND for inserting text.
2. **Microphone** — macOS will prompt on first recording; click Allow.
3. **Input Monitoring** — macOS may also prompt for this; allow it.

After granting Accessibility you must fully quit and reopen the terminal app.

### Recommended: free up the Fn key

System Settings → Keyboard → "Press 🌐 key to" → **Do Nothing** (otherwise macOS pops the emoji picker / its own dictation when you tap Fn).

## Run

```bash
uv run wispa
```

Hold Fn, talk, release. A pill at the bottom of the screen shows a live waveform while you speak and pulses while processing; the console shows the transcript and per-stage latency.

## Config

Edit `config.toml`:

- `hotkey`: `"fn"` | `"right_option"` | `"ctrl_option"` (use right_option/ctrl_option with external keyboards — they don't emit Apple's Fn signal)
- `[cleanup] enabled/model/timeout`: the Ollama pass
- `[injection] method`: `"ax"` (direct, default) or `"paste"` (always clipboard)

## Project layout

| file | job |
|---|---|
| `wispa/hotkey.py` | Quartz event tap watching the Fn modifier flag system-wide |
| `wispa/recorder.py` | sounddevice mic capture while key is held |
| `wispa/transcriber.py` | Parakeet V3 on MLX (`parakeet-mlx`) |
| `wispa/cleaner.py` | skip-gate, chunked-parallel + streaming Ollama cleanup, dictionary prompt, graceful fallback to raw |
| `wispa/injector.py` | AX `kAXSelectedTextAttribute` insertion, paste fallback |
| `wispa/appcontext.py` | frontmost app name → tone context for the LLM |
| `wispa/overlay.py` | Wispr-style pill at screen bottom: live waveform while recording, pulse while processing |
| `wispa/main.py` | wires it together, prints latency stats |
