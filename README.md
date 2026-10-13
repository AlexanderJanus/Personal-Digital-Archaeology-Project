
# Network PDAP Project - CLCV 3000 FALL 2026

Install required libs
`pip install -r requirments.txt`


This segment will make matplotlib interface work in wsl.
`sudo apt install python3-tk python3-matplotlib`

If this errors it means linux cannot see your wifi card.
`netsh.exe wlan show interfaces`   # should print a "Signal : xx%" line

How to run script.
`python3 wifi_survey.py floorplan.png survey.csv`    