# ============================================================
#  kill_switch.py — Portfolio loss monitor
#  Activates when drawdown hits KILL_SWITCH_PCT (default 25%)
#  Closes all positions, cancels all orders, locks the bot
#  Cannot be bypassed — checked before every trade action
# ============================================================

import logging
import json
import os
from datetime import datetime
import config

logger = logging.getLogger(__name__)

# ── State file — persists kill switch status across restarts ──
STATE_FILE = "logs/kill_switch_state.json"


class KillSwitch:
    """
    Monitors portfolio drawdown and activates a hard stop
    when losses exceed KILL_SWITCH_PCT from session start value.
    """

    def __init__(self, alpaca_client):
        self.client          = alpaca_client
        self.threshold       = config.KILL_SWITCH_PCT   # e.g. 0.25
        self.is_active       = False
        self.session_start_value = None
        self.activation_time = None
        self.activation_loss_pct = None

        self._load_state()

    # ── State persistence ─────────────────────────────────────

    def _load_state(self):
        """Load kill switch state from disk (survives restarts)."""
        os.makedirs("logs", exist_ok=True)
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            self.is_active           = state.get("is_active", False)
            self.session_start_value = state.get("session_start_value")
            self.activation_time     = state.get("activation_time")
            self.activation_loss_pct = state.get("activation_loss_pct")
            if self.is_active:
                logger.warning(
                    f"Kill switch still ACTIVE from {self.activation_time} "
                    f"(loss was {self.activation_loss_pct:.1%})"
                )

    def _save_state(self):
        """Persist kill switch state to disk."""
        state = {
            "is_active":           self.is_active,
            "session_start_value": self.session_start_value,
            "activation_time":     self.activation_time,
            "activation_loss_pct": self.activation_loss_pct,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    # ── Session init ──────────────────────────────────────────

    def start_session(self):
        """
        Call at market open each day.
        Records the starting portfolio value for the day.
        Resets kill switch if it was active from prior day.
        """
        self.is_active = False
        self.activation_time = None
        self.activation_loss_pct = None

        portfolio_value = self.client.get_portfolio_value()
        self.session_start_value = portfolio_value
        self._save_state()

        logger.info(
            f"Kill switch session started — "
            f"starting value: ${portfolio_value:,.2f} | "
            f"threshold: {self.threshold:.0%} loss = "
            f"${portfolio_value * self.threshold:,.2f}"
        )

    # ── Core check ────────────────────────────────────────────

    def check(self) -> bool:
        """
        Call this before every trade decision.
        Returns True if kill switch is ACTIVE (bot must stop).
        Returns False if safe to continue.
        """
        # Already active — no need to recheck
        if self.is_active:
            return True

        if self.session_start_value is None:
            logger.warning("Kill switch: no session start value — call start_session() first")
            return False

        current_value = self.client.get_portfolio_value()
        loss_pct = (self.session_start_value - current_value) / self.session_start_value

        logger.debug(
            f"Kill switch check: start=${self.session_start_value:,.2f} | "
            f"now=${current_value:,.2f} | loss={loss_pct:.2%}"
        )

        if loss_pct >= self.threshold:
            self._activate(loss_pct, current_value)
            return True

        return False

    # ── Activation ────────────────────────────────────────────

    def _activate(self, loss_pct: float, current_value: float):
        """
        Trigger the kill switch:
        1. Cancel all open orders
        2. Close all positions at market
        3. Lock the bot for the rest of the session
        4. Log the event
        """
        self.is_active           = True
        self.activation_time     = datetime.now().isoformat()
        self.activation_loss_pct = loss_pct

        logger.critical(
            f"\n{'='*60}\n"
            f"  KILL SWITCH ACTIVATED\n"
            f"  Loss: {loss_pct:.2%} of session start value\n"
            f"  Portfolio: ${current_value:,.2f} "
            f"(started at ${self.session_start_value:,.2f})\n"
            f"  Time: {self.activation_time}\n"
            f"  Closing all positions and cancelling all orders...\n"
            f"{'='*60}"
        )

        # Execute emergency shutdown
        self.client.cancel_all_orders()
        self.client.close_all_positions()

        # Log to kill switch event file
        self._write_event_log(loss_pct, current_value)
        self._save_state()

    def _write_event_log(self, loss_pct: float, current_value: float):
        """Write a permanent record of the kill switch activation."""
        os.makedirs("logs", exist_ok=True)
        event = {
            "event":             "KILL_SWITCH_ACTIVATED",
            "timestamp":         datetime.now().isoformat(),
            "session_start":     self.session_start_value,
            "value_at_trigger":  current_value,
            "loss_pct":          round(loss_pct, 4),
            "threshold_pct":     self.threshold,
        }
        log_path = f"logs/kill_switch_events.json"
        events = []
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                events = json.load(f)
        events.append(event)
        with open(log_path, "w") as f:
            json.dump(events, f, indent=2)

    # ── Status ────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current kill switch status as dict for dashboard."""
        current = self.client.get_portfolio_value()
        loss_pct = 0.0
        if self.session_start_value:
            loss_pct = (self.session_start_value - current) / self.session_start_value
        return {
            "active":            self.is_active,
            "threshold":         self.threshold,
            "session_start":     self.session_start_value,
            "current_value":     current,
            "current_loss_pct":  round(loss_pct, 4),
            "activation_time":   self.activation_time,
            "activation_loss":   self.activation_loss_pct,
        }
