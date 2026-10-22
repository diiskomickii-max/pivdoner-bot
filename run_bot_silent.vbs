' Тихий запуск бота без окна консоли (для автозапуска через Планировщик).
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\Projects\pivdoner-pro-bot"
WshShell.Run "cmd /c run_bot.bat", 0, False
Set WshShell = Nothing
