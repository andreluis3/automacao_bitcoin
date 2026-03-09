import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulation_engine import *

engine = SimulationEngine()
engine.rodar()