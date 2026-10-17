$ErrorActionPreference = "Stop"
python -m unittest discover -s tests -p "test_*.py" -v
python demos/run_core_demo.py
python demos/run_enclosure_demo.py
