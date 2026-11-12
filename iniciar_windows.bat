@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente .venv nao encontrado. Crie com: py -m venv .venv
  pause
  exit /b 1
)
if not exist ".venv\Scripts\waitress-serve.exe" (
  echo Instale as dependencias primeiro: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo PENTE FINO 3.0 - abra http://localhost:5050
echo Outros celulares precisam estar na mesma rede Wi-Fi do computador.
".venv\Scripts\waitress-serve.exe" --listen=0.0.0.0:5050 app:app
pause
