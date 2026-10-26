@echo off
cd /d "C:\Users\david\Proyecto 1"
echo [%date% %time%] Iniciando ETL Quant NQ en bucle... >> "outputs\etl_daemon.log"
.\venv\Scripts\python.exe -u main_dashboard_nq.py --headless --supabase --loop 300 >> "outputs\etl_daemon.log" 2>&1
