"""Ponto de entrada do processo dedicado aos trabalhos de fundo."""

from app.services.background_workers import main


if __name__ == "__main__":
    main()
