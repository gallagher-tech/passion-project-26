# passion-project-26
Passion Project Summer 2026

Working Deck for Passion Project: [Food for Thought](https://docs.google.com/presentation/d/1XBIuHYTtCYXlJKESTd2HzYoy4a99-x0bBDA_emFXVYQ/edit?usp=sharing)

Inductive Proximity Sensor for Wok docking detection: [Sensor](https://www.amazon.com/dp/B0CLVBGT5P)

IR Sensor for visitor entering detection (optional): [Sensor](https://www.amazon.com/dp/B08X2MFS6S)


<img src="Assets/Passion Project 2026 Summer - Food For Thought  Diagram.png" alt="sketch" width="600">

## Repository layout

```
Arduino/
  Firmata/StandardFirmata/  # firmware flashed to the Arduino Uno
  sketch_LED_click/         # early LED test sketch
Assets/                     # diagram and installation photos
wok_detection/
  state_machine.py   # debounce, polarity inversion, edges, busy/lockout -- no hardware/OSC deps
  firmata_input.py    # pyfirmata2 board/pin setup, feeds raw values into the state machine
  osc_output.py        # python-osc client wrapper
  main.py              # CLI, logging, wiring, signal handling (LOCKOUT_DURATION_SECONDS lives here)
tests/
  test_state_machine.py
```

## Installation setup

<img src="Assets/Walk%28Wok%29%20In%20Kitchen.jpg" alt="Wok on the sensor burner in front of the projected cooking video" width="600">

<img src="Assets/PassionProject%202026%20Summer%20-%20Documentation.jpg" alt="Summer '26 interns Lia and Ellie playtesting the wok station" width="600">

*Our summer '26 interns, Lia and Ellie, playtesting the interaction before our presentation.*

Visitors lift the wok off the burner prop. The sensor inside the prop picks
up the change, and the projected cooking video plays on the wall behind the
G&A letters. Putting the wok back stops the video once the lockout window has
passed (see [State machine behavior](#state-machine-behavior)).

### What you need

- **MadMapper license.** Without a license, MadMapper's output is
  watermarked or limited, so an installation needs a licensed copy.
- **Computer** to run MadMapper and the Python bridge, with Python 3.12 and
  a free USB port for the Arduino.
- **Projector(s)** connected to that computer and mapped in MadMapper. The
  main one covers the wall behind the burner.
- **Arduino Uno** flashed with `Arduino/Firmata/StandardFirmata`, plus a USB
  cable to the computer.
- **Inductive proximity sensor** mounted inside the burner prop and wired to
  the Arduino (see [Wiring](#wiring)).
- **Physical props:** a table, a steel or iron wok, the wooden burner prop
  that holds the sensor, and the dimensional G&A letters on the projection
  wall.
- **IR sensor (optional).** It isn't built into this setup or the bridge
  code. It's a possible addition for detecting visitors as they walk up to
  the installation.

### Assumptions

- The room is indoors and can be darkened enough for projection.
- MadMapper and the bridge run on the **same computer** and talk over OSC on
  `127.0.0.1:8010`.
- The Arduino is powered over USB, with no separate power supply.
- The wok is **ferrous metal** (carbon steel or cast iron) so the inductive
  sensor can detect it. Aluminum or non-metal pans won't trigger it
  reliably.
- The projector(s) are already positioned and aligned with the wall and
  props in the MadMapper project.

### Startup order

1. Plug the Arduino into the computer over USB.
2. Find the Arduino's serial port. On Windows it shows up as a `COM`
   port, and the number depends on the machine and on which USB port you
   use, so it may be `COM3` on one setup and `COM7` on another. To check:
   - **Device Manager > Ports (COM & LPT)**: look for "Arduino Uno (COMx)".
   - **Arduino IDE > Tools > Port**: lists the board with its port.
   - **PowerShell**: `[System.IO.Ports.SerialPort]::GetPortNames()`
   
   If you move the cable to another USB port, check again, because the
   number can change. Close the Arduino IDE's Serial Monitor first, since
   only one program can hold the port at a time. On Linux the port is
   usually `/dev/ttyACM0`.
3. Open the MadMapper project and check that the OSC listen port matches
   (see [MadMapper setup](#madmapper-setup)).
4. Start the bridge with the port you found, e.g.
   `python -m wok_detection.main --port COM7`.
5. Lift the wok off the burner and confirm the video starts.


## WOK detection bridge (MVP)

A Python bridge for an interactive projection installation. A metal sensor
on the Arduino tells us whether a wok is present on a hot plate; the bridge
turns that into a single OSC message that drives playback in MadMapper.

```
Arduino Uno (StandardFirmata) --[Firmata/USB]--> Python bridge --[OSC out only]--> MadMapper
```

This script is the sole Firmata client on the serial port -- do not also
point MadMapper's own Firmata module at it. There is no OSC coming back in
from MadMapper in this version; it's one-directional, OSC out only.

### Wiring

- Sensor power: 5V pin on the Arduino Uno (no separate power supply).
- Sensor signal: digital pin **D2**.
- Raw electrical behavior: pin reads **LOW** when no metal is detected,
  **HIGH** when metal is detected.

The script inverts this once, at the input boundary, into the names used
everywhere else in the code:

| Raw pin state | Logical name  | Logical value |
|----------------|--------------|---------------|
| HIGH (metal)   | `WOK_PRESENT` | 0 |
| LOW (no metal) | `WOK_ABSENT`  | 1 |

### State machine behavior

1. The Firmata digital pin is read continuously and non-blockingly via
   pyfirmata2's sampling/callback mechanism (no polling loop, no
   `time.sleep()` on the sampling path).
2. The logical signal is debounced: it must be stable for a configurable
   duration (default **50ms**) before being treated as a real change.
3. A debounced transition to `WOK_ABSENT` (wok removed) or `WOK_PRESENT`
   (wok placed) is an edge.
4. A `busy` flag (playback lockout) starts `False`:
   - Not busy + transition to `WOK_ABSENT` -> send OSC `1` ("video on"),
     then `busy = True` and start the lockout timer.
   - Not busy + transition to `WOK_PRESENT` -> send OSC `0` ("video off").
   - While `busy` is `True`, *all* sensor transitions are ignored (no OSC
     sent), logged at debug level.
   - When the lockout timer elapses, `busy` becomes `False` again. The
     sensor's state is **not** re-checked at that point -- only the next
     fresh edge is acted on. This is a deliberate MVP simplification,
     worth revisiting if "wok already back on the burner when the lockout
     ends" turns out to matter in practice.
5. `LOCKOUT_DURATION_SECONDS` is a constant at the top of
   `wok_detection/main.py`, defaulting to **60** seconds. It is the sole
   thing driving `busy` in this version -- nothing clears it early.

### Code structure

See [Repository layout](#repository-layout) for the full file list.

`state_machine.py` has no Firmata or OSC imports, so it's unit-tested with
fake pin-state sequences, a fake OSC sender, and a fake clock/timer --  no
Arduino or MadMapper required.

### Install & run

```
pip install -r requirements.txt
python -m wok_detection.main --port COM3
```

(Use your actual serial port, e.g. `COM3` or `COM7` on Windows or
`/dev/ttyACM0` on Linux. See [Startup order](#startup-order) for how to
find it.)

CLI options (all optional except `--port`):

| Flag | Default | Meaning |
|------|---------|---------|
| `--port` | *(required)* | Arduino serial port |
| `--pin` | `2` | Digital pin number |
| `--debounce-ms` | `50` | Debounce duration in ms |
| `--sampling-interval-ms` | `19` | Firmata sampling interval (pyfirmata2's own default) |
| `--osc-host` | `127.0.0.1` | MadMapper OSC listen host |
| `--osc-port` | `8010` | MadMapper OSC listen port |
| `--osc-address` | `/video` | OSC address |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

`LOCKOUT_DURATION_SECONDS` is **not** a CLI flag by design (see above) --
edit the constant at the top of `wok_detection/main.py` to change it.

**Defaults flagged for confirmation** -- these were chosen as sensible
MVP defaults, not confirmed against your actual MadMapper project:
- Debounce: 50ms
- OSC out port: 8010 (check MadMapper's Preferences > OSC listen port and
  match it, or pass `--osc-port`)
- OSC address: `/video`

### MadMapper setup

The bridge sends one OSC address with an integer payload: **1 = video on,
0 = video off**. On the MadMapper side:

1. Preferences > OSC: confirm the listen port matches `--osc-port`
   (default `8010`).
2. Use **Learn Mode** on the parameter you want to drive (e.g. a cue's
   opacity, or a Logic/Trigger input) and trigger the bridge once (place/
   remove metal from the sensor) to bind `/video`.
3. If mapping to an opacity/fader-style parameter, set **Source Range**
   to `0-1` and map to whatever **Target Range** makes sense for on/off.
   If you'd rather drive two discrete cues, use **Map To Cue** with a
   condition on the value (0 vs 1) instead.

The OSC contract is deliberately simple -- one address, `1`/`0` -- so
either approach works; pick whichever fits your existing MadMapper
project.

### Testing

```
pip install -r requirements.txt
pytest
```

Covers: debounce/jitter rejection, `WOK_PRESENT`/`WOK_ABSENT` polarity
inversion, edge detection, suppressed transitions while busy, and the
timer-based unlock via `LOCKOUT_DURATION_SECONDS`. All tests run against
a fake clock and fake timer scheduler -- no real hardware, no waiting on
wall-clock time, no MadMapper instance.

### Notes

- `pip install -r requirements.txt && pytest` has been run against
  pyfirmata2 2.5.1 (all 9 state-machine tests pass), and the pyfirmata2
  API used here (`Arduino.samplingOn`, `board.get_pin('d:<pin>:i')`,
  `pin.register_callback`, `pin.enable_reporting`) was confirmed directly
  against that installed version's source: `get_pin` parses the
  `d:2:i` string into `INPUT` mode as expected, and the port's `_update`
  fires `pin.callback(pin.value)` with a `bool` on every sampling tick,
  which `firmata_input.py` converts with `int(value)`.
- Not yet tested against real hardware (no Arduino/sensor attached in
  this environment) -- confirm on-site that the actual serial port,
  wiring, and sensor polarity behave as documented above.
- Ctrl+C triggers a clean shutdown: the state machine cancels any pending
  lockout timer and the Firmata board connection is closed.
