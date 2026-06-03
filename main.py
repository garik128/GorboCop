"""GorboCop — точка входа приложения контроля осанки."""
from app import single_instance
from app.ui import GorboCopApp


def main() -> None:
    # Если экземпляр уже запущен — показать его окно и выйти.
    existing = single_instance.find_existing()
    if existing:
        single_instance.signal_existing(existing)
        return

    app = GorboCopApp()
    app.run()


if __name__ == "__main__":
    main()
