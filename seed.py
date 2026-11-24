"""Reset and load the benchmark master data. Run: python seed.py"""
import os
from app import DB, init_db
if os.path.exists(DB):
    os.remove(DB)
init_db()
print("SmartFactory AI benchmark database seeded.")
