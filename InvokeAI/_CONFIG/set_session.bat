@echo off
    set OUTFOLDER_PATH=E:\Documents\GenerativeAI\StableDiffusion
    set OUTFOLDER_DEFAULT_PREFIX=_SANDBOX_20230622
    set OUTFOLDER_DATED_PREFIX=_SANDBOX
    set NEW_STARTER_FOLDER=E:\Documents\GenerativeAI\StableDiffusion\__NEW
    set EMBEDDING_PATH=G:\GenAI-data\ModelsDownloads\embeddings

    set YYYYMMDD=%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%

    echo Do you want to use a folder session with date? Today is %DATE%
    set /P USE_DATED_OUTFOLDER="Enter 0 or 1 Q: [1] "
    if not defined USE_DATED_OUTFOLDER set USE_DATED_OUTFOLDER=1

    if /I "%USE_DATED_OUTFOLDER%" == "1" (   
        set OUTFOLDER=%OUTFOLDER_PATH%\%OUTFOLDER_DATED_PREFIX%_%YYYYMMDD%
    ) else (
        set OUTFOLDER=%OUTFOLDER_PATH%\%OUTFOLDER_DEFAULT_PREFIX%
    )

    if not exist %OUTFOLDER% ( 
        if not exist %NEW_STARTER_FOLDER% (
            mkdir %OUTFOLDER%  
        ) else (
            xcopy /e /k /h /i %NEW_STARTER_FOLDER% %OUTFOLDER% 
            echo Session Folder created : %OUTFOLDER%
        )
    ) else (
        echo Session Folder : %OUTFOLDER%
    )

    REM echo  .venv\Scripts\invokeai.exe --outdir="%OUTFOLDER%" --web --host 0.0.0.0
    REM pause
    
    set INVOKEAI_ROOT=.
    python .venv\Scripts\invokeai.exe --outdir="%OUTFOLDER%" --model="%DEFAULT_MODEL%" --embedding_path="%EMBEDDING_PATH%" --width=576 --height=832 --steps=75 --web --host 0.0.0.0