# HUD, hand tracking and the confirmation button

The HUD (`/hud`, the default start page) is a full-screen command centre that
works on a PC, a phone or a TV browser.

## Hand tracking

Press the camera button. Hand tracking runs **in the browser** with MediaPipe;
camera frames never leave the device. The WASM runtime ships with the frontend
(`scripts/copy-mediapipe.mjs`) and the model is served by the Vortis server at
`/v1/hud/gesture-model` (downloaded once from Google, SHA-256 pinned, cached in
`~/.vortis/models/`). Offline machines: copy `gesture_recognizer.task`
into that folder.

Default bindings (change any of them in HUD, Gestovi; saved per device):

| Gesture | Default action |
|---|---|
| Open palm (hold) | start / stop listening |
| Fist (hold) | stop speaking / cancel the request |
| Grab (open palm closing into a fist) | expand the last answer full screen |
| Repulsor (open palm pushed at the camera) | send the last answer to the TV |
| Two hands moving apart | full screen |
| Two hands coming together | dismiss what is shown |
| Thumb up | confirm the pending action (off by default, enable with the shield button) |
| Thumb down | decline the pending action |
| V sign | toggle the air mouse (aim with the index finger) |
| Pinch | click (air mouse on) |
| Swipe left / right | switch the right-hand panel |
| Swipe up / down | send to the TV / dismiss |

## Hands-free voice

The HUD listens all the time once the microphone is allowed. Speech is cut
into short phrases in the browser and only those phrases are sent to the local
Vortis server for recognition. Nothing is sent while no one is talking.

- Say "Jarvis" (or "Džarvis", "hej Jarvis") followed by the question:
  "Jarvis, koliko je sati?".
- Saying only "Jarvis" plays a short tone and the next phrase within eight
  seconds is taken as the question.
- After a spoken answer Jarvis keeps listening for seven seconds, so a
  follow-up needs no wake word.
- The microphone button in the header turns continuous listening on or off;
  the button next to the input field, a click on the orb or an open palm
  starts a single question.

Recognition runs locally with faster-whisper (`small` model by default) and
needs the speech extra: `uv sync --extra speech`. Replies are spoken by the
browser with a Serbian or Croatian voice when one is installed (Microsoft Edge
includes natural Serbian voices), otherwise by the server's TTS backend.

## Voice commands

A short utterance that matches a command runs the same action as the gesture,
without asking the assistant. "Jarvis" in front is optional. Anything longer
than five words is always treated as a question.

| Say | Action |
|---|---|
| potvrdi, odobri / confirm | confirm |
| odbij, otkaži / cancel | decline |
| stani, stop, prekini, tišina | stop |
| pošalji na TV, prikaži na TV / show on TV | send to the TV |
| uvećaj / expand | expand |
| skloni, zatvori / dismiss | dismiss |
| ceo ekran / fullscreen | full screen |
| sledeći panel, nazad | switch panel |
| vazdušni miš / air mouse | air mouse |

Every recognised gesture is also published as a `gesture_detected` event
(`POST /v1/gestures`, WebSocket `/v1/agents/events`), so other devices and
agents can react to it.

## Confirmation button

Tools whose spec sets `requires_confirmation` (shell, git commit, sending
messages, plugins with `"confirm": True`...) now wait for a person to press
**Potvrdi** in the UI. The model cannot approve itself: the button posts a
one-time token that only the UI receives. No answer within 120 s means *no*.
Set `[security] enforce_tool_confirmation = false` to return to the old
auto-approve behaviour.

## Tool outcomes

Tool results carry `done`, `unverified` or `failed`. `unverified` results are
prefixed with an instruction so the model does not claim success, and the HUD
shows a coloured badge per call.

## Plugins

Drop a `.py` file with a `PLUGIN` dict and a `run(parameters, player=None)`
function into `~/.vortis/plugins/` (or `./plugins`, or
`$VORTIS_PLUGIN_DIRS`). It is enabled on the next start. Mark-LVII/Torvis
plugins in that format load unchanged. `GET /v1/plugins` lists what loaded and
why anything failed.

## Pairing a phone or TV

HUD → Uređaji → QR kod. Scan with the phone; it gets its own revocable token.
The server must listen on the LAN (`vortis serve --host 0.0.0.0` with
`VORTIS_API_KEY` set). Phones and TVs can use everything except pairing
new devices. Browsers only allow the camera on `https://` or `localhost`, so
hand tracking on a phone/TV needs HTTPS (e.g. Tailscale Serve or a reverse
proxy); the rest of the HUD works over plain HTTP.

## TV display

`/display?screen=tv` is a full-screen output page for a TV browser. It never
asks for the camera or microphone. Pair it once (open `/pair` on the TV, type
the code, tick "Ovo je TV"); afterwards it shows whatever is pushed to it:

- `POST /v1/display` with `title`, `markdown`, optional `chart`
  (`{type: line|bar|area|scatter|pie, x: [...], series: [{name, values}]}`)
  and `target` (`tv`, `pc` or `all`)
- the `show_on_screen` tool, so the assistant can put an answer or a chart on
  the TV by itself
- the "send to TV" gesture or voice command

`GET /v1/display/last?target=tv` returns the item currently on screen.

## Workspace windows

Everything the assistant shows on the PC opens as a window on the HUD
workspace instead of covering the screen. Windows can be dragged by their
title bar, resized from the corner, maximized (double-click the bar) and
closed. Each window has TV and phone buttons that mirror it to that screen.
While a request runs, a "Radim…" card in the corner lists every tool step and
its outcome. Camera, devices, gestures and the full activity log live in the
side panel (right-most header button).

## Simulations

Say "Jarvis, simuliraj kosi hitac" or "simuliraj otplatu kredita od
10.000 € na 5 godina". The assistant calls the `simulate` tool with a small
declarative model; a window opens with a slider for every parameter, a live
graph and the key numbers (peak, final value, where the peak happens).
"Zadrži za poređenje" freezes the current curve as a dashed line so a change
can be compared against it.

A model is one of three modes:

| mode | meaning |
|---|---|
| `function` | `series` are plain formulas of `x` and the parameters |
| `ode` | each `state` has a `rate` (its derivative); integrated with RK4 |
| `iterate` | each `state` has a `next` value; `x` counts the steps |

Expressions use numbers, parameter and variable names, `+ - * / ^ %`,
comparisons, `&& || !`, `pi`, `e` and a fixed set of math functions
(`sin`, `exp`, `ln`, `sqrt`, `min`, `max`, `clamp`, `if(cond, a, b)` and
others). Nothing else is accepted, so a model can never run code. The server
validates the model and computes the numbers the assistant explains; the
browser re-runs it on every slider move, and a mirrored TV follows the
sliders.

`POST /v1/display` accepts the same model as `simulation`, slider values as
`values`, and an `id`; pushing again with the same `id` updates the open
window instead of opening a new one.

## Claude on your own account

Set the server agent to `claude_account` to answer with Claude through the
Claude account that Claude Code is signed in with on this computer. No API
key is used; requests count against that account's plan, which is meant for
your personal use.

```toml
[server]
agent = "claude_account"

[claude]
model = "opus"
fallback_agent = "orchestrator"
max_turns = 20
timeout = 240
web = true
```

Requirements: Node.js 22 or newer and a signed-in Claude Code (`claude`,
then `/login`). Vortis tools reach Claude through a local endpoint bound to
`127.0.0.1` with a per-run token, and still pass through the normal
capability checks and confirmations. Claude's own file, shell and editing
tools are disabled; `web = true` allows web search and page fetches.

When Claude cannot be reached (offline, signed out, Node.js missing) the
request is answered by `fallback_agent` on the local engine, so Vortis keeps
working without internet. After a failure Claude is retried after 30 seconds,
or after 5 minutes when the sign-in failed.
