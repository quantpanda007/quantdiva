@echo off
call C:\Users\Abhishek\anaconda3\Scripts\activate.bat quantlib-pricing
pyinstaller main.py ^
--onefile ^
--noconsole ^
--name Optima ^
--add-data "frontend/static;frontend/static" ^
--add-data "api;api" ^
--add-data "services;services" ^
--add-data "engines;engines" ^
--add-data "instruments;instruments" ^
--add-data "registry;registry" ^
--add-data "core;core" ^
--add-data "market;market" ^
--add-data "models;models" ^
--add-data "configs;configs" ^
--add-data "definitions;definitions" ^
--add-data "numerics;numerics" ^
--add-data "reporting;reporting" ^
--add-data "workflows;workflows" ^
--add-data "C:\Users\Abhishek\anaconda3\envs\quantlib-pricing\Lib\site-packages\QuantLib;QuantLib" ^
--collect-all QuantLib ^
--collect-all fastapi ^
--collect-all uvicorn ^
--collect-all starlette ^
--collect-all fpdf ^
--collect-all plotly ^
--collect-all kaleido ^
--collect-all openpyxl ^
--collect-all requests ^
--hidden-import QuantLib ^
--hidden-import fastapi ^
--hidden-import fastapi.middleware ^
--hidden-import fastapi.middleware.cors ^
--hidden-import uvicorn ^
--hidden-import uvicorn.logging ^
--hidden-import uvicorn.loops ^
--hidden-import uvicorn.loops.auto ^
--hidden-import uvicorn.protocols ^
--hidden-import uvicorn.protocols.http ^
--hidden-import uvicorn.protocols.http.auto ^
--hidden-import uvicorn.lifespan ^
--hidden-import uvicorn.lifespan.on ^
--hidden-import starlette ^
--hidden-import starlette.middleware ^
--hidden-import starlette.middleware.cors
echo.
echo Build complete. Check dist/Optima.exe
pause