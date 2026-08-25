@echo off
chcp 65001 > nul
title Запуск Stalzone Auction System

echo [1/2] Запуск локального сервера FastAPI (Uvicorn)...
start "Stalzone API" cmd /k "uvicorn main:app --reload"

echo [2/2] Запуск Telegram-бота...
start "Stalzone Bot" cmd /k "py bot.py"

echo.
echo Все компоненты запущены в отдельных окнах!
pause