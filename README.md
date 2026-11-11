# Binance Levels Monitor 1.1.0 (Windows)

Scans all Binance USDT-M perpetual futures (public endpoints only, no API keys) and warns when the price
comes close to a **cascade of levels**.

## Definitions
- **Extreme** - a swing high / swing low: a candle whose high (low) is the highest (lowest) among N candles
  on each side (default 3). Default: 5m candles, 288 of them (24 h); both are configurable.
- **Cascade** - at least 2 extremes (configurable) of the same kind close to each other. Highs form a
  *resistance* cascade, lows a *support* cascade. A cascade the price has already closed beyond is dropped.
- **Tolerance** (how close extremes must be to form a cascade): by default **3 average 1-minute candles**, so it
  adapts to the volatility of the coin (limited to 0.05 %...2 %). Mode "percent" = fixed % (default 0.2 %).
- **Score 0-100** of a cascade: up to 50 for the number of extremes (5+ = full), up to 20 for how long the cascade
  has existed, up to 30 for the volume on the extreme candles vs the usual candle (3x+ = full).
  "Minimum cascade score" (default 0 = off) hides weak cascades everywhere.
- **Average 1-minute candle** - mean (high - low) of the 1-minute candles of the last hour.
- **Approach** - distance from the price to the cascade <= 1 average 1-minute candle (configurable).
- **Trend** - the distance now vs 3 minutes ago: *Closing*, *Moving away* or *Flat* (a change smaller than
  0.25 average candles is Flat). With "Do not notify when moving away" (default on) a coin that is moving away
  is not put into list 1 and gives no notification. It is still shown in list 2.

## Window
1. **Approaching a cascade** - new entries trigger sound + popup + Windows toast (with score and trend).
   Cooldown 30 min per coin and side (saved on disk).
2. **Closest to a cascade** - the 5 nearest coins, whether or not they are close enough. No notifications.

Double-click a ticker -> opens it in Vataga.terminal. Click "Copy" -> copies the ticker.
Right-click a row (or select it and press **Chart**) -> **mini chart**: candles, cascade lines (R = resistance,
S = support, number = score) and the current price. It uses data the monitor already has (no extra traffic).

## Journal (button "Journal")
Every notification is recorded; 30 minutes later (configurable) its outcome is decided on 1-minute candles:
- **bounced** - the price reached the cascade and moved away from it by 2 average candles;
- **broke** - a candle closed beyond the cascade;
- **touched** - reached it, but neither bounced nor broke;
- **not_reached** - never got there.
Statistics per side and the bounce rate (bounced / (bounced + broke)) are shown; "Export to CSV" saves the list.
Use it to tune the settings (tolerance, minimum score, distance) instead of guessing.

## System tray
Settings > "Minimizing the window hides it to the system tray" (default on) and
"The X button hides the window to the tray instead of exiting" (default off). Monitoring continues in the tray;
the icon menu: Show window / Check now / Exit; the tooltip shows the status. Notifications and popups still appear.
(If the tray package is missing, the window is just minimized to the taskbar.)

## Settings (tabs)
Filters: 24h volume (30M USDT), NATR (0 = off), trades in the last 15 min (0 = off).
Cascades: candle size, history, swing strength, minimum extremes, tolerance, minimum score.
Approach: distance, trend, cooldown, check interval. Notifications and window: popups, tray, chart, journal.

## Vataga.terminal
Settings > General > "Application integration" on; link the window to the "Screener" group.
Partner id `BinanceLevelsMonitor`, port 5005 (Settings -> Test Vataga).

## Build
Upload the folder (including hidden `.github`) to GitHub -> Actions -> "Build Windows installer" ->
download `BinanceLevelsMonitor-Setup`. Or locally: `build.bat` (Python + Inno Setup 6).

## Traffic
REST only. Every check: 1 request for all tickers + a few new 1-minute candles per coin. Cascades are recalculated
every 5 minutes (1 request per coin with more than 30M volume, weight 2). The journal adds 1 small request per signal.

## Data
`%APPDATA%\BinanceLevelsMonitor\` : settings.json, alerts.log, alert_times.json, journal.json.

## Tests
`python -m unittest discover -s tests`
