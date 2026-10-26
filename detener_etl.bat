@echo off
echo ===================================================
echo   Deteniendo el proceso ETL de NQ en segundo plano
echo ===================================================
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main_dashboard_nq.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('[OK] Proceso detenido PID: ' + $_.ProcessId) }"
echo Proceso finalizado exitosamente.
echo.
pause
