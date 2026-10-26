@echo off
echo ===================================================
echo         ESTADO DEL PROCESO ETL QUANT NQ
echo ===================================================
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main_dashboard_nq.py*' }; if ($p) { Write-Host '[ACTIVO] El ETL esta corriendo en segundo plano (PID: ' + $p.ProcessId + ')' -ForegroundColor Green } else { Write-Host '[DETENIDO] No hay proceso ETL corriendo actualmente.' -ForegroundColor Yellow }"
echo.
echo Ultimas 10 lineas del log:
echo ---------------------------------------------------
powershell -NoProfile -Command "if (Test-Path 'outputs\etl_daemon.log') { Get-Content 'outputs\etl_daemon.log' -Tail 10 } else { Write-Host 'No se ha generado log todavia.' }"
echo ---------------------------------------------------
echo.
pause
