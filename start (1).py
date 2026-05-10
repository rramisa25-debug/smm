import subprocess
import sys
import os

print("Files:", os.listdir('.'))

p1 = subprocess.Popen([sys.executable, "smm_bot_Final.py"])
p2 = subprocess.Popen([sys.executable, "Claw_VIP_Final.py"])

print("SMM Bot chalu!")
print("Claw VIP Bot chalu!")

p1.wait()
p2.wait()
