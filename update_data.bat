@echo off
cd /d C:\erp_ai_assistant
call .venv\Scripts\activate
python update_data.py
pause