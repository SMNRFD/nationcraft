"""Telegram bot (aiogram 3.x).

The bot is a *thin client*. All game logic lives in the backend; the
bot calls the REST API using ``httpx.AsyncClient`` and renders responses
as rich inline keyboards and Markdown messages.
"""
