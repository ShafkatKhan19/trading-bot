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
        self.threshold       = config.KILL_SWITCH_PCT   # e.g. 0.25 — resets daily
        self.is_active       = False
        self.session_start_value = None
        self.activation_time = None
        self.activation_loss_pct = None

        # Cumulative (all-time) drawdown tracking — never reset by start_session.
        self.cumulative_threshold = config.CUMULATIVE_KILL_SWITCH_PCT
        self.peak_value           = None
        self.cumulative_active    = False
        self.cumulative_activation_time = None
        self.cumulative_loss_pct  = None

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
            self.peak_value                 = state.get("peak_value")
            self.cumulative_active          = state.get("cumulative_active", False)
            self.cumulative_activation_time = state.get("cumulative_activation_time")
            self.cumulative_loss_pct        = state.get("cumulative_loss_pct")
            # A peak recorded under a different capital basis is not
            # comparable: drawdown built up while paper trades were sized off
            # $100k equity would read as a 66% loss of a $500 basis and trip
            # the permanent lock on the first check. Re-anchor once.
            if state.get("capital_basis") != config.ACCOUNT_CAPITAL and not self.cumulative_active:
                if self.peak_value is not None:
                    logger.warning(
                        f"Kill switch capital basis changed "
                        f"({state.get('capital_basis')} -> {config.ACCOUNT_CAPITAL}) — "
                        f"re-anchoring peak (was ${self.peak_value:,.2f})"
                    )
                self.peak_value = None
            if self.cumulative_active:
                logger.critical(
                    f"CUMULATIVE kill switch still ACTIVE from "
                    f"{self.cumulative_activation_time} — requires manual reset "
                    f"(call reset_cumulative() after reviewing the account)"
                )
            if self.is_active:
                loss_str = f"{self.activation_loss_pct:.1%}" if self.activation_loss_pct is not None else "unknown"
                logger.warning(
                    f"Kill switch still ACTIVE from {self.activation_time} "
                    f"(loss was {loss_str})"
                )

    def _save_state(self):
        """Persist kill switch state to disk."""
        state = {
            "is_active":           self.is_active,
            "session_start_value": self.session_start_value,
            "activation_time":     self.activation_time,
            "activation_loss_pct": self.activation_loss_pct,
            "peak_value":                 self.peak_value,
            "cumulative_active":          self.cumulative_active,
            "cumulative_activation_time": self.cumulative_activation_time,
            "cumulative_loss_pct":        self.cumulative_loss_pct,
            "capital_basis":              config.ACCOUNT_CAPITAL,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    @staticmethod
    def _loss_pct(reference: float, current: float) -> float:
        """
        Dollars lost since `reference`, as a fraction of the capital actually
        at risk — min(reference, ACCOUNT_CAPITAL). On a $100k paper account
        trading a $500 book, a $25 loss is 5%, not 0.025%. On a real $500
        account this is identical to (reference - current) / reference.
        """
        base = min(reference, config.ACCOUNT_CAPITAL)
        return (reference - current) / base

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
        if self.peak_value is None:
            self.peak_value = portfolio_value
        self._save_state()

        logger.info(
            f"Kill switch session started — "
            f"starting value: ${portfolio_value:,.2f} | "
            f"threshold: {self.threshold:.0%} loss = "
            f"${min(portfolio_value, config.ACCOUNT_CAPITAL) * self.threshold:,.2f}"
        )

    # ── Core check ────────────────────────────────────────────

    def check(self) -> bool:
        """
        Call this before every trade decision.
        Returns True if kill switch is ACTIVE (bot must stop).
        Returns False if safe to continue.
        """
        # Cumulative switch is permanent — never auto-clears, checked first.
        if self.cumulative_active:
            return True

        current_value = self.client.get_portfolio_value()

        if self.peak_value is None:
            self.peak_value = current_value
        elif current_value > self.peak_value:
            self.peak_value = current_value

        cumulative_loss_pct = self._loss_pct(self.peak_value, current_value)
        if cumulative_loss_pct >= self.cumulative_threshold:
            self._activate_cumulative(cumulative_loss_pct, current_value)
            return True

        # Already active for the day — no need to recheck the daily threshold
        if self.is_active:
            return True

        if self.session_start_value is None:
            logger.warning("Kill switch: no session start value — call start_session() first")
            self._save_state()
            return False

        loss_pct = self._loss_pct(self.session_start_value, current_value)

        logger.debug(
            f"Kill switch check: start=${self.session_start_value:,.2f} | "
            f"now=${current_value:,.2f} | loss={loss_pct:.2%} | "
            f"peak=${self.peak_value:,.2f} | cumulative_loss={cumulative_loss_pct:.2%}"
        )

        self._save_state()

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
        orders_ok    = self.client.cancel_all_orders()
        positions_ok = self.client.close_all_positions()
        if not (orders_ok and positions_ok):
            logger.critical(
                "KILL SWITCH SHUTDOWN INCOMPLETE — account may still hold open "
                "orders/positions. Manual intervention required immediately."
            )

        # Log to kill switch event file
        self._write_event_log(loss_pct, current_value)
        self._save_state()

    def _write_event_log(self, loss_pct: float, current_value: float, event_name: str = "KILL_SWITCH_ACTIVATED"):
        """Write a permanent record of the kill switch activation."""
        os.makedirs("logs", exist_ok=True)
        event = {
            "event":             event_name,
            "timestamp":         datetime.now().isoformat(),
            "session_start":     self.session_start_value,
            "value_at_trigger":  current_value,
            "loss_pct":          round(loss_pct, 4),
            "threshold_pct":     self.threshold if event_name == "KILL_SWITCH_ACTIVATED" else self.cumulative_threshold,
        }
        log_path = f"logs/kill_switch_events.json"
        events = []
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                events = json.load(f)
        events.append(event)
        with open(log_path, "w") as f:
            json.dump(events, f, indent=2)

    def _activate_cumulative(self, loss_pct: float, current_value: float):
        """
        Trigger the PERMANENT cumulative kill switch — drawdown from the
        all-time equity peak exceeded CUMULATIVE_KILL_SWITCH_PCT. Unlike the
        daily switch, this does NOT reset on the next session; it requires
        an explicit reset_cumulative() call after a human reviews the account.
        """
        self.cumulative_active          = True
        self.cumulative_activation_time = datetime.now().isoformat()
        self.cumulative_loss_pct        = loss_pct

        logger.critical(
            f"\n{'='*60}\n"
            f"  CUMULATIVE KILL SWITCH ACTIVATED — PERMANENT LOCK\n"
            f"  All-time drawdown: {loss_pct:.2%} (threshold {self.cumulative_threshold:.0%})\n"
            f"  Portfolio: ${current_value:,.2f} (all-time peak ${self.peak_value:,.2f})\n"
            f"  This does NOT reset daily. Call reset_cumulative() manually\n"
            f"  after reviewing the account before the bot will trade again.\n"
            f"{'='*60}"
        )

        orders_ok    = self.client.cancel_all_orders()
        positions_ok = self.client.close_all_positions()
        if not (orders_ok and positions_ok):
            logger.critical(
                "CUMULATIVE KILL SWITCH SHUTDOWN INCOMPLETE — account may still hold "
                "open orders/positions. Manual intervention required immediately."
            )

        self._write_event_log(loss_pct, current_value, event_name="CUMULATIVE_KILL_SWITCH_ACTIVATED")
        self._save_state()

    def reset_cumulative(self):
        """
        Manually clear the permanent cumulative kill switch.
        Intended to be called deliberately (e.g. from a console/admin action)
        after a human has reviewed the account — never called automatically.
        """
        self.cumulative_active          = False
        self.cumulative_activation_time = None
        self.cumulative_loss_pct        = None
        self.peak_value                 = self.client.get_portfolio_value()
        self._save_state()
        logger.warning(
            f"Cumulative kill switch manually RESET — new peak set to "
            f"${self.peak_value:,.2f}"
        )

    # ── Status ────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current kill switch status as dict for dashboard."""
        current = self.client.get_portfolio_value()
        loss_pct = 0.0
        if self.session_start_value:
            loss_pct = self._loss_pct(self.session_start_value, current)
        return {
            "active":            self.is_active,
            "threshold":         self.threshold,
            "session_start":     self.session_start_value,
            "current_value":     current,
            "current_loss_pct":  round(loss_pct, 4),
            "activation_time":   self.activation_time,
            "activation_loss":   self.activation_loss_pct,
        }
