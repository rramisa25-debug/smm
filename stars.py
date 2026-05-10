import subprocess
import threading

def run_claw():
    subprocess.run(["python", "Claw_VIP_Final.py"])

def run_smm():
    subprocess.run(["python", "smm_bot_Final.py"])

t1 = threading.Thread(target=run_claw)
t2 = threading.Thread(target=run_smm)

t1.start()
t2.start()

t1.join()
t2.join()
