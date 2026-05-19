@echo off
color a
echo Which bot do you want to run?
echo   1) Spotify Streaming Bot
echo   2) SoundCloud Streaming Bot
echo.
set /p choice="Enter 1 or 2: "
if "%choice%"=="1" py -3 spotifystreambot.py
if "%choice%"=="2" py -3 soundcloudbot.py
