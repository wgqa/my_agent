# RAG 知识库一键启动脚本（PowerShell）
Write-Host "Starting API ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; uvicorn api.app:app --host 127.0.0.1 --port 8000"
Write-Host "Starting UI ..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot'; streamlit run ui/app.py"
Write-Host "API: http://localhost:8000" -ForegroundColor Cyan
Write-Host "UI:  http://localhost:8501" -ForegroundColor Cyan
