#!/usr/bin/env bash
# Terminal GIF pipeline for the peira walkthrough docs.
#
# When vhs or asciinema plus agg is installed, this records real GIFs of
# the walkthrough moments into site/assets/gifs/. When neither is
# available it prints the exact install and record commands and exits 0.
#
# Either way it (re)writes the static SVG fallbacks in
# site/assets/fallbacks/. Those are hand-authored terminal screenshots
# with full alt text sidecars, and they are what the docs use until real
# GIFs exist. Every fallback carries an illustrative-mock banner so no
# number on it can be mistaken for a recorded result.
#
# Recording touches no live API. The tape uses the offline mock adapter
# and the trial-demo fixture only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GIFS="$REPO_ROOT/site/assets/gifs"
FALLBACKS="$REPO_ROOT/site/assets/fallbacks"
mkdir -p "$GIFS" "$FALLBACKS"

FONT="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace"
RIBBON="ILLUSTRATIVE MOCK. Based on the documented walkthrough, not a live recording."

write_chrome() {
  # Shared terminal chrome. Args: width, height, title, aria-label.
  local w="$1" h="$2" title="$3" aria="$4"
  cat <<SVG
<svg xmlns="http://www.w3.org/2000/svg" width="$w" height="$h" viewBox="0 0 $w $h" role="img" aria-label="$aria">
  <rect width="$w" height="$h" rx="10" fill="#101418"/>
  <rect width="$w" height="40" rx="10" fill="#1b2129"/>
  <rect y="20" width="$w" height="20" fill="#1b2129"/>
  <circle cx="28" cy="20" r="7" fill="#e05f5f"/>
  <circle cx="52" cy="20" r="7" fill="#e8b34b"/>
  <circle cx="76" cy="20" r="7" fill="#7fd79a"/>
  <text x="104" y="26" font-family="$FONT" font-size="15" fill="#a8bcb0">$title</text>
SVG
}

write_ribbon() {
  # Args: width, y. The banner that marks the image as illustrative.
  local w="$1" y="$2"
  cat <<SVG
  <rect y="$y" width="$w" height="36" fill="#e8b34b"/>
  <text x="$((w / 2))" y="$((y + 24))" text-anchor="middle" font-family="$FONT" font-size="15" font-weight="bold" fill="#3a2b00">$RIBBON</text>
</svg>
SVG
}

write_install_fallback() {
  {
    write_chrome 960 210 "Terminal" "Illustrative terminal mock of the peira install step"
    cat <<'SVG'
  <text x="32" y="72" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16"><tspan fill="#7fd79a">$ </tspan><tspan fill="#eef4ee">pip install -e .</tspan></text>
  <text x="32" y="96" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">Obtaining file:///home/dev/peira</text>
  <text x="32" y="120" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">Installing build dependencies ... done</text>
  <text x="32" y="144" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#7fd79a">Successfully installed peira-0.9.0</text>
SVG
    write_ribbon 960 168
  } > "$FALLBACKS/install.svg"
  cat > "$FALLBACKS/install.alt.txt" <<'EOF'
Illustrative terminal mock for the install step of the peira walkthrough.
A dark terminal window shows the command pip install -e . followed by
abbreviated installer lines ending in Successfully installed peira-0.9.0.
A yellow banner labels the image as an illustrative mock based on the
documented walkthrough, not a live recording.
EOF
}

write_firstrun_fallback() {
  {
    write_chrome 960 402 "Terminal" "Illustrative terminal mock of the first peira run"
    cat <<'SVG'
  <text x="32" y="72" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16"><tspan fill="#7fd79a">$ </tspan><tspan fill="#eef4ee">peira run --adapter mock --suite trial-demo --out /tmp/demo</tspan></text>
  <text x="32" y="96" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  [1/12]</text>
  <text x="32" y="120" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  [12/12]</text>
  <text x="32" y="144" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">done: 12 cases (12 eligible)</text>
  <text x="32" y="168" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  spend:           $0.0000 (uncapped)</text>
  <text x="32" y="192" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#eef4ee">  ASR (conditional): 0.3333 95% CI 0.1381-0.6094</text>
  <text x="32" y="216" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  benign accuracy:   1.0000 95% CI 0.7575-1.0000</text>
  <text x="32" y="240" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  malformed rate:    0.0000</text>
  <text x="32" y="264" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  refusal rate:      0.0000 95% CI 0.0000-0.2425</text>
  <text x="32" y="288" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  ineligible:        0</text>
  <text x="32" y="312" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">  ranking eligible:  False (needs 200 eligible cases, demo has 12)</text>
  <text x="32" y="336" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#a8bcb0">artifact: /tmp/demo/mock-trial-demo.json</text>
SVG
    write_ribbon 960 360
  } > "$FALLBACKS/first-run.svg"
  cat > "$FALLBACKS/first-run.alt.txt" <<'EOF'
Illustrative terminal mock for the first run step of the peira walkthrough.
A dark terminal window shows the command peira run with the mock adapter on
the trial-demo suite, followed by the summary lines quoted from the
walkthrough doc. Twelve cases ran with twelve eligible, spend was zero,
ASR was 0.3333 with a 95 percent confidence interval of 0.1381 to 0.6094,
benign accuracy was 1.0, and ranking was not eligible because the demo is
too small. A yellow banner labels the image as an illustrative mock based
on the documented walkthrough, not a live recording.
EOF
}

write_report_fallback() {
  {
    write_chrome 960 186 "Terminal" "Illustrative terminal mock of the peira report step"
    cat <<'SVG'
  <text x="32" y="72" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16"><tspan fill="#7fd79a">$ </tspan><tspan fill="#eef4ee">peira report --run /tmp/demo/mock-trial-demo.json --out /tmp/demo/report.html</tspan></text>
  <text x="32" y="96" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16" fill="#7fd79a">report written to /tmp/demo/report.html</text>
  <text x="32" y="120" font-family="ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace" font-size="16"><tspan fill="#7fd79a">$ </tspan><tspan fill="#eef4ee">open /tmp/demo/report.html</tspan></text>
SVG
    write_ribbon 960 144
  } > "$FALLBACKS/report.svg"
  cat > "$FALLBACKS/report.alt.txt" <<'EOF'
Illustrative terminal mock for the report step of the peira walkthrough.
A dark terminal window shows the peira report command writing an HTML
report to tmp slash demo slash report.html, followed by a command to open
it in a browser. A yellow banner labels the image as an illustrative mock
based on the documented walkthrough, not a live recording.
EOF
}

write_tape() {
  cat > "$GIFS/walkthrough.tape" <<'TAPE'
# vhs tape for the peira walkthrough. Run with vhs site/assets/gifs/walkthrough.tape
# Uses only the offline mock adapter and the trial-demo fixture. No API keys, no spend.
Output site/assets/gifs/walkthrough.gif
Set Shell "bash"
Set FontSize 18
Set Width 1280
Set Height 720

Type "peira run --adapter mock --suite trial-demo --out /tmp/peira-gif-demo" Enter
Sleep 4s
Type "peira report --run /tmp/peira-gif-demo/mock-trial-demo.json --out /tmp/peira-gif-demo/report.html" Enter
Sleep 2s
TAPE
}

print_instructions() {
  cat <<'EOF'
record_gif: no terminal recording tools found, so no GIFs were recorded.
The static SVG fallbacks in site/assets/fallbacks/ were written and the
docs should keep using them until real GIFs exist.

To record the real walkthrough GIFs on a machine with the tooling:

  Option A, vhs (recommended)
    brew install vhs
    # or go install github.com/charmbracelet/vhs@latest   (needs Go)
    vhs site/assets/gifs/walkthrough.tape

  Option B, asciinema plus agg
    pip install asciinema
    cargo install --git https://github.com/asciinema/agg   # needs Rust
    asciinema rec --title "peira walkthrough" site/assets/gifs/walkthrough.cast
    agg --font-size 18 site/assets/gifs/walkthrough.cast site/assets/gifs/walkthrough.gif

Record only the mock adapter on the trial-demo fixture, as the tape does.
Do not record real adapter runs with API keys in the terminal.
EOF
}

record_with_vhs() {
  echo "record_gif: recording with vhs"
  vhs "$GIFS/walkthrough.tape"
}

record_with_asciinema() {
  echo "record_gif: recording with asciinema"
  asciinema rec --title "peira walkthrough" "$GIFS/walkthrough.cast"
  echo "record_gif: rendering GIF with agg"
  agg --font-size 18 "$GIFS/walkthrough.cast" "$GIFS/walkthrough.gif"
}

main() {
  write_install_fallback
  write_firstrun_fallback
  write_report_fallback
  write_tape
  echo "record_gif: wrote static fallbacks to $FALLBACKS"

  if command -v vhs >/dev/null 2>&1; then
    record_with_vhs
  elif command -v asciinema >/dev/null 2>&1 && command -v agg >/dev/null 2>&1; then
    record_with_asciinema
  else
    print_instructions
  fi
  exit 0
}

main "$@"
