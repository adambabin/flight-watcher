import argparse
import json
import sys
from datetime import date

from . import dashboard
from .frontier import Frontier
from .inbox import GitHubInbox
from .runner import App
from .state import State
from .telegram import Telegram


def main(argv=None):
    p = argparse.ArgumentParser(prog="flightwatch", description="Frontier GoWild seat tracker")
    p.add_argument("mode", choices=["auto", "tick", "night", "digest", "check", "commands", "search"])
    p.add_argument("args", nargs="*", help="search: ORIGIN DEST YYYY-MM-DD")
    p.add_argument("--state", default=".state", help="state directory (default .state)")
    a = p.parse_args(argv)

    if a.mode == "search":
        o, d, day = a.args
        print(json.dumps(Frontier().search(o.upper(), d.upper(), date.fromisoformat(day)), indent=1))
        return 0

    state = State(a.state)
    app = App(state, Frontier(), Telegram.from_env(), log=lambda m: print(m, flush=True),
              inbox=GitHubInbox.from_env())
    mode = app.pick_mode() if a.mode == "auto" else a.mode
    print(f"mode: {mode}", flush=True)
    try:
        if mode == "digest":
            app.process_commands()
            app.maybe_digest(force=True)
        elif mode == "commands":
            app.commands_run()
        else:
            getattr(app, mode)()
    finally:
        state.save()
        dashboard.write(state, app.local_now())
    if app.health_alerted:
        # A red run makes GitHub email the owner too (once a day, like the Telegram alert).
        print(f"::error::Frontier checks are failing: {state.runtime['health']['last_error']}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
