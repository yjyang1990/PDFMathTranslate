@echo off
setlocal enabledelayedexpansion

set PYTHON_URL=https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip
set PIP_URL=https://bootstrap.pypa.io/get-pip.py
set HF_ENDPOINT=https://hf-mirror.com

if not exist pdf2zh/python.exe (
    powershell -Command "& {Invoke-WebRequest -Uri !PYTHON_URL! -OutFile python.zip}"
    powershell -Command "& {Expand-Archive -Path python.zip -DestinationPath pdf2zh -Force}"
    del python.zip
    echo import site >> pdf2zh/python312._pth
)
cd pdf2zh

if not exist Scripts/pip.exe (
    powershell -Command "& {Invoke-WebRequest -Uri !PIP_URL! -OutFile get-pip.py}"
    python get-pip.py
)
path Scripts

pip install --no-warn-script-location --upgrade pdf2zh
pdf2zh -i

pause
