from __future__ import annotations

import shlex
from decimal import Decimal, InvalidOperation

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static

from orchestrator import AgentReply, Orchestrator
from voice_router import VoiceRouter


AGENTS = ("AURA", "GHOST", "GASPARIN")
DISPLAY_NAMES = {"AURA": "AURA", "GHOST": "GHOST", "GASPARIN": "GASPARÍN"}
COLORS = {"AURA": "#00ffff", "GHOST": "#ff3366", "GASPARIN": "#00ff66"}
INITIAL_VOICES = {"AURA": "ef_dora", "GHOST": "bm_george", "GASPARIN": "am_adam"}


class GhostCommandCenter(App[None]):
    TITLE = "GHOST OS // CONTAINER #001"
    CSS_PATH = "styles.tcss"
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.orchestrator = Orchestrator()
        self.wallet = Decimal("0.00")
        self.voice_router = VoiceRouter(on_error=self._report_voice_error)

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-header"):
            yield Static(
                "GHOST OS // CONTAINER #001 — MILLENNIAL SURVIVAL PROTOCOL",
                id="header-title",
            )
            yield Static("TREASURY BALANCE: $0.00", id="wallet-header")
        with Vertical(id="main-layout"):
            with Vertical(id="pane-grid"):
                with Vertical(classes="pane agent-pane", id="aura-pane"):
                    yield Static("AURA [NEXUS / CO-HOST]", classes="pane-title")
                    yield Static("VOICE: ef_dora  |  STATUS: STANDBY", id="aura-status")
                    yield RichLog(id="aura-log", wrap=True, markup=False)
                with Vertical(classes="pane agent-pane", id="ghost-pane"):
                    yield Static("GHOST [COO / STRATEGY & WALLET]", classes="pane-title")
                    yield Static("ROI: NOT CONNECTED  |  TREASURY: $0.00", id="ghost-status")
                    yield RichLog(id="ghost-log", wrap=True, markup=False)
                with Vertical(classes="pane agent-pane", id="gasparin-pane"):
                    yield Static("GASPARÍN [CTO / DOCKER & CODE]", classes="pane-title")
                    yield Static("VRAM: NOT CONNECTED  |  CONTAINER: LOCAL", id="gasparin-status")
                    yield RichLog(id="gasparin-log", wrap=True, markup=False)
                with Vertical(classes="pane", id="bus-pane"):
                    yield Static(
                        "SHARED CONTEXT BUS [shared_bus.jsonl + $0.00 TREASURY]",
                        classes="pane-title",
                    )
                    yield Static("TTS: SILENT  |  CONTEXT WINDOW: LAST 25 MESSAGES", id="bus-status")
                    yield RichLog(id="bus-log", wrap=True, markup=False)
        yield Input(
            placeholder="Message the room, or use /voice and /wallet commands…",
            id="command-input",
        )

    async def on_mount(self) -> None:
        try:
            await self.orchestrator.initialize()
            await self.voice_router.start()
            self._append_bus_line("SYSTEM", "Shared context bus ready. TTS is off by default.")
            self._append_bus_line("SYSTEM", f"Context file: {self.orchestrator.bus_path}")
        except (OSError, ValueError) as error:
            self._append_bus_line("ERROR", f"Startup failed: {error}")
            self.notify(f"Startup failed: {error}", severity="error", timeout=8)

    async def on_unmount(self) -> None:
        await self.voice_router.close()
        await self.orchestrator.close()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        event.input.value = ""
        if not message:
            return
        if message.startswith("/"):
            self._handle_command(message)
            return

        event.input.disabled = True
        self.process_message(message)

    @work(group="conversation")
    async def process_message(self, message: str) -> None:
        try:
            await self.orchestrator.append_message("AXEL", message, self.voice_router.enabled)
            self._append_bus_line("AXEL", message)
            async for reply in self.orchestrator.route_user_message(
                message,
                voice_enabled=self.voice_router.enabled,
            ):
                self._display_reply(reply)
        except (OSError, ValueError, RuntimeError) as error:
            self._append_bus_line("ERROR", str(error))
            self.notify(f"Conversation failed: {error}", severity="error", timeout=8)
        finally:
            self.query_one("#command-input", Input).disabled = False
            self.query_one("#command-input", Input).focus()

    def _display_reply(self, reply: AgentReply) -> None:
        agent = reply.agent
        log = self.query_one(f"#{agent.lower()}-log", RichLog)
        log.write(Text(reply.text, style=COLORS[agent]))
        self._append_bus_line(agent, reply.text)
        if reply.fallback:
            reason = f" ({reply.fallback_reason})" if reply.fallback_reason else ""
            self._append_bus_line(
                "SYSTEM",
                f"{DISPLAY_NAMES[agent]} used the offline mock response{reason}.",
            )
        status = self.query_one(f"#{agent.lower()}-status", Static)
        current_voice = self.voice_router.voice_for(agent)
        status.update(f"VOICE: {current_voice}  |  STATUS: RESPONSE READY")
        self.voice_router.enqueue(agent, reply.text)

    def _handle_command(self, raw: str) -> None:
        try:
            parts = shlex.split(raw)
        except ValueError as error:
            self.notify(f"Invalid command syntax: {error}", severity="error")
            return

        if parts[:3] == ["/voice", "tts", "--init-all"] and len(parts) == 3:
            self.initialize_voices()
        elif len(parts) == 4 and parts[:2] == ["/voice", "set"]:
            self._set_voice(parts[2], parts[3])
        elif len(parts) == 3 and parts[:2] == ["/wallet", "add"]:
            self._add_wallet(parts[2])
        else:
            self.notify(
                "Commands: /voice tts --init-all | /voice set <agent> <voice_id> | /wallet add <amount>",
                severity="warning",
                timeout=8,
            )

    def _set_voice(self, agent_name: str, voice_id: str) -> None:
        agent = agent_name.upper()
        if agent in {"GASPARÍN", "CASPER"}:
            agent = "GASPARIN"
        if agent not in AGENTS:
            self.notify("Agent must be AURA, GHOST, or GASPARIN.", severity="error")
            return
        if not voice_id.replace("_", "").isalnum():
            self.notify("Voice IDs may contain only letters, numbers, and underscores.", severity="error")
            return
        self.voice_router.set_voice(agent, voice_id)
        self.query_one(f"#{agent.lower()}-status", Static).update(
            f"VOICE: {voice_id}  |  STATUS: {'TTS READY' if self.voice_router.enabled else 'STANDBY'}"
        )
        self._append_bus_line("SYSTEM", f"{DISPLAY_NAMES[agent]} voice set to {voice_id}.")

    def _add_wallet(self, amount_text: str) -> None:
        try:
            amount = Decimal(amount_text)
        except InvalidOperation:
            self.notify("Enter a valid non-negative amount, e.g. /wallet add 25.00.", severity="error")
            return
        if not amount.is_finite() or amount <= 0:
            self.notify("Wallet additions must be a positive finite amount.", severity="error")
            return
        self.wallet += amount
        formatted = f"${self.wallet:,.2f}"
        self.query_one("#wallet-header", Static).update(f"TREASURY BALANCE: {formatted}")
        self.query_one("#ghost-status", Static).update(f"ROI: NOT CONNECTED  |  TREASURY: {formatted}")
        self.query_one("#bus-status", Static).update(
            f"TTS: {'ENABLED' if self.voice_router.enabled else 'SILENT'}  |  TREASURY: {formatted}"
        )
        self._append_bus_line("SYSTEM", f"🎉 Treasury credited ${amount:,.2f}. New balance: {formatted}.")

    @work(group="voice-setup")
    async def initialize_voices(self) -> None:
        await self.voice_router.initialize_all()
        for agent in AGENTS:
            self.query_one(f"#{agent.lower()}-status", Static).update(
                f"VOICE: {self.voice_router.voice_for(agent)}  |  STATUS: TTS READY"
            )
        self.query_one("#bus-status", Static).update(
            f"TTS: ENABLED  |  TREASURY: ${self.wallet:,.2f}"
        )
        for agent, text in self.voice_router.awakening_lines():
            self.query_one(f"#{agent.lower()}-log", RichLog).write(Text(text, style=COLORS[agent]))
            await self.orchestrator.append_message(agent, text, True)
            self._append_bus_line(agent, text)

    def _append_bus_line(self, sender: str, text: str) -> None:
        if not self.is_mounted:
            return
        color = COLORS.get(sender, "#ffcc00" if sender != "ERROR" else "#ff3366")
        self.query_one("#bus-log", RichLog).write(Text(f"[{sender}] {text}", style=color))

    def _report_voice_error(self, message: str) -> None:
        self._append_bus_line("ERROR", f"Voice output failed: {message}")
        self.notify(f"Voice output failed: {message}", severity="error", timeout=8)


if __name__ == "__main__":
    GhostCommandCenter().run()
