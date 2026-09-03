# passion-project-26
Passion Project Summer 2026

Working Deck for Passion Project: [Food for Thought](https://docs.google.com/presentation/d/1XBIuHYTtCYXlJKESTd2HzYoy4a99-x0bBDA_emFXVYQ/edit?usp=sharing)

Inductive Proximity Sensor for Wok docking detection: [Sensor](https://www.amazon.com/Haldzemo-Inductive-Proximity-Normally-Detection/dp/B0CLVBGT5P/ref=sr_1_2?crid=2UBGKX6LACQ1Q&dib=eyJ2IjoiMSJ9.Gjubu62P53iDcHwgkeAdtYYbNqUvxSWWoog5DB9grmYjBsZjVqvtxL4lDL-p6S3NpgGWJRPtfRN7DDF8_XArBIJBNafI4zicuwhuNsSfzd3k4jdNFjGb2sB9JLvKkndzNG_xqpAV9OX5NJv9nLebL8-Ie1MNO1JJAqQxd0LAhZaJe_X3CyxBW-tyCjP3cxIDl3UNOiLDpBBgPeiNwJ_AIV6CVDZwlqq11u4j5z6HA20.o2ATch9JANFj03Zw8mqdicduLN5WG9ITe_1aQq1OFt0&dib_tag=se&keywords=inductive+proximity+sensor+arduino&qid=1787590697&sprefix=inductive+proximity+sensor+arduino%2Caps%2C122&sr=8-2#customerReviews)

IR Sensor for visitor entering detection: [Sensor](https://www.amazon.com/Digital-Receiver-Transmitter-Electronic-Building/dp/B08X2MFS6S/ref=pd_bxgy_d_sccl_1/134-1341154-4390636?pd_rd_w=IlqpJ&content-id=amzn1.sym.9bef5913-5870-4504-8883-3ba89d7f8e39&pf_rd_p=9bef5913-5870-4504-8883-3ba89d7f8e39&pf_rd_r=M67XN7X84AVRQ2HAGQ43&pd_rd_wg=2H12w&pd_rd_r=b9a84c14-f5fa-4370-b31d-a8ae2348fcfc&pd_rd_i=B08X2MFS6S&th=1)


<img src="assets/Passion Project 2026 Summer - Food For Thought  Diagram" alt="Project physical mock up sketch" width="600">


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

### Project layout

```
wok_detection/
  state_machine.py   # debounce, polarity inversion, edges, busy/lockout -- no hardware/OSC deps
  firmata_input.py    # pyfirmata2 board/pin setup, feeds raw values into the state machine
  osc_output.py        # python-osc client wrapper
  main.py              # CLI, logging, wiring, signal handling (LOCKOUT_DURATION_SECONDS lives here)
tests/
  test_state_machine.py
```

`state_machine.py` has no Firmata or OSC imports, so it's unit-tested with
fake pin-state sequences, a fake OSC sender, and a fake clock/timer --  no
Arduino or MadMapper required.

### Install & run

```
pip install -r requirements.txt
python -m wok_detection.main --port COM3
```

(Use your actual serial port -- e.g. `COM3` on Windows, `/dev/ttyACM0` on
Linux.)

CLI options (all optional except `--port`):

| Flag | Default | Meaning |
|------|---------|---------|
| `--port` | *(required)* | Arduino serial port |
| `--pin` | `2` | Digital pin number |
| `--debounce-ms` | `50` | Debounce duration in ms |
| `--sampling-interval-ms` | `19` | Firmata sampling interval (pyfirmata2's own default) |
| `--osc-host` | `127.0.0.1` | MadMapper OSC listen host |
| `--osc-port` | `8000` | MadMapper OSC listen port |
| `--osc-address` | `/video` | OSC address |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

`LOCKOUT_DURATION_SECONDS` is **not** a CLI flag by design (see above) --
edit the constant at the top of `wok_detection/main.py` to change it.

**Defaults flagged for confirmation** -- these were chosen as sensible
MVP defaults, not confirmed against your actual MadMapper project:
- Debounce: 50ms
- OSC out port: 8000 (check MadMapper's Preferences > OSC listen port and
  match it, or pass `--osc-port`)
- OSC address: `/video`

### MadMapper setup

The bridge sends one OSC address with an integer payload: **1 = video on,
0 = video off**. On the MadMapper side:

1. Preferences > OSC: confirm the listen port matches `--osc-port`
   (default `8000`).
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
