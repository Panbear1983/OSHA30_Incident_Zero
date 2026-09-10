"""Small reusable modal dialogs. These are NOT part of the named screen registry in
ui/app.py -- other screens import them directly and await the result:

    confirmed = await self.app.push_screen_wait(ConfirmModal("Abandon this shift?"))
    if confirmed:
        ...
"""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical {
        width: 60; height: auto; border: heavy #58a6ff; background: #161b22; padding: 1 2;
    }
    ConfirmModal Static { margin-bottom: 1; }
    ConfirmModal Button { margin-right: 1; }
    """

    def __init__(self, message: str, confirm_label: str = "Yes", cancel_label: str = "No"):
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.message)
            yield Button(self.confirm_label, id="confirm", variant="error")
            yield Button(self.cancel_label, id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)


class TypedConfirmModal(ModalScreen[bool]):
    """Requires typing an exact string (e.g. a profile name) before confirming a destructive
    action -- used for profile deletion."""

    DEFAULT_CSS = ConfirmModal.DEFAULT_CSS

    def __init__(self, message: str, required_text: str):
        super().__init__()
        self.message = message
        self.required_text = required_text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.message)
            yield Input(placeholder=self.required_text, id="typed")
            yield Button("Confirm", id="confirm", variant="error")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            typed = self.query_one("#typed", Input).value
            self.dismiss(typed.strip() == self.required_text)
        else:
            self.dismiss(False)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)
