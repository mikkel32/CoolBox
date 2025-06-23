"""Main entry point for the CoolBox application."""

from src.app import CoolBoxApp
from src.utils.theme import apply_theme
from src.utils.helpers import log


def main() -> None:
    log("Starting CoolBox")
    app = CoolBoxApp()
    apply_theme(app)
    app.mainloop()


if __name__ == "__main__":
    main()
