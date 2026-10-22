@echo off
REM Запуск бота ПивДонер с авто-перезапуском при падении (watchdog).
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

:loop
echo [%date% %time%] Запуск бота...
python -X utf8 bot.py >> bot_stdout.log 2>> bot_stderr.log
echo [%date% %time%] Бот завершился с кодом %ERRORLEVEL%. Перезапуск через 10 сек...
timeout /t 10 /nobreak >nul
goto loop
