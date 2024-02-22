@echo off

PUSHD "%~dp0"
setlocal

call .venv\Scripts\activate.bat
set INVOKEAI_ROOT=.

:start
echo Desired action:
echo 1. Generate images with the browser-based interface
echo 2. Run textual inversion training
echo 3. Merge models (diffusers type only)
echo 4. Download and install models
echo 5. Change InvokeAI startup options
echo 6. Re-run the configure script to fix a broken install or to complete a major upgrade
echo 7. Open the developer console
echo 8. Update InvokeAI
echo 9. Run the InvokeAI image database maintenance script
echo 10. Command-line help
echo Q - Quit
set /P choice="Please enter 1-10, Q: [1] "
if not defined choice set choice=1
IF /I "%choice%" == "1" (
    echo Starting the InvokeAI browser-based UI..
    python .venv\Scripts\invokeai-web.exe %*
) ELSE IF /I "%choice%" == "2" (
    echo Starting textual inversion training..
    python .venv\Scripts\invokeai-ti.exe --gui
) ELSE IF /I "%choice%" == "3" (
    echo Starting model merging script..
    python .venv\Scripts\invokeai-merge.exe --gui
) ELSE IF /I "%choice%" == "4" (
    echo Running invokeai-model-install...
    python .venv\Scripts\invokeai-model-install.exe
) ELSE IF /I "%choice%" == "5" (
    echo Running invokeai-configure...
    python .venv\Scripts\invokeai-configure.exe --skip-sd-weight --skip-support-models
) ELSE IF /I "%choice%" == "6" (
    echo Running invokeai-configure...
    python .venv\Scripts\invokeai-configure.exe --yes --skip-sd-weight
) ELSE IF /I "%choice%" == "7" (
    echo Developer Console
    echo Python command is:
    where python
    echo Python version is:
    python --version
    echo *************************
    echo You are now in the system shell, with the local InvokeAI Python virtual environment activated,
    echo so that you can troubleshoot this InvokeAI installation as necessary.
    echo *************************
    echo *** Type `exit` to quit this shell and deactivate the Python virtual environment ***
    call cmd /k
) ELSE IF /I "%choice%" == "8" (
   echo Running invokeai-update...
   python -m invokeai.frontend.install.invokeai_update
) ELSE IF /I "%choice%" == "9" (
   echo Running the db maintenance script...
   python .venv\Scripts\invokeai-db-maintenance.exe
) ELSE IF /I "%choice%" == "10" (
    echo Displaying command line help...
    python .venv\Scripts\invokeai-web.exe --help %*
    pause
    exit /b
) ELSE IF /I "%choice%" == "q" (
    echo Goodbye!
    goto ending
) ELSE (
    echo Invalid selection
    pause
    exit /b
)
goto start

endlocal
pause

:ending
exit /b

