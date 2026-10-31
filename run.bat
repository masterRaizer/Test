@echo off
rem Starts the loader from source. Pass --launch to start the game too.
python -m pip install -q -r requirements.txt
start "" pythonw -m mcd_loader run %*
