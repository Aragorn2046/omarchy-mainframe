# Contributing to Mainframe

Thanks for wanting to help. Mainframe is a small, community-run system monitor for Omarchy. Bug reports, fixes,
hardware support and design improvements are all welcome.

## Before you start

- **Small fixes:** open a pull request directly.
- **Bigger changes** (new views, new data sources, design changes): open an issue first so we can agree on the
  approach before you spend time on it.
- **Security problems:** do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Where to start

Look for issues labelled `good first issue` or `help wanted`. Share questions and ideas in GitHub Discussions.
For a first-time contributor, GitHub's default settings require maintainer approval before CI runs.

## What fits Mainframe

- Plain QML, JavaScript and Python only. No compiled code, no build step, no extra runtime dependencies beyond what
  Omarchy ships (Quickshell, Python 3, standard command-line tools).
- Light: it should stay around 2% of one CPU core while open and use nothing when closed.
- Follows the Omarchy theme and look. Quiet, uncluttered, keyboard-friendly.
- Reads system information only. It never needs root and never changes the system.
- Hardware support for machines we can't test ourselves is especially welcome: tell us what you tested it on.

## Running it from your checkout

```bash
git clone https://github.com/Aragorn2046/omarchy-mainframe.git
cd omarchy-mainframe
qs -p mainframe          # run straight from the checkout
```

## Tests (please run before opening a pull request)

```bash
node --test mainframe/tests/
python3 -m unittest discover -s mainframe/tests -p 'test_*.py'
python3 mainframe/collect.py --selftest
QT_QPA_PLATFORM=offscreen QSG_RENDER_LOOP=basic /usr/lib/qt6/bin/qmltestrunner -input mainframe/tests
MAINFRAME_SMOKE_NO_SCOPE=1 MAINFRAME_SMOKE_NO_SSH=1 MAINFRAME_SMOKE_NO_REMOTE=1 QT_QPA_PLATFORM=offscreen QSG_RENDER_LOOP=basic scripts/mainframe-smoke.sh
```

The same checks run automatically on every pull request. CI uses Omarchy's Quickshell package.
CI skips the real SSH check, connections to remote hosts,
the live Wayland window, the systemd scope, and the storage shutdown check. CI reports CPU and frame-rate numbers without failing on limit breaches, while
`scripts/mainframe-smoke.sh` enforces the limits locally. Report mode still fails when measurements are missing.

## Pull requests

- Keep each pull request focused on one change.
- Describe what you changed, why, and what hardware or theme you tested on. A screenshot helps for visual changes.
- Add or update tests for logic changes.
- Every pull request is reviewed by the maintainer before it is merged. Automated checks must pass.
- By contributing you agree your contribution is licensed under the [MIT License](LICENSE).

## Code of conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
