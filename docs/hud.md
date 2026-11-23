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
