from pathlib import Path
import os
import argparse
import yaml
from os.path import expanduser
import logging
import coloredlogs

coloredlogs.install()
logging.getLogger("paramiko").setLevel(logging.WARNING)
"""
# Scheduled with fake SCANNET 
python tools/cluster/push_and_run_folder.py --exp=pretrain --time=4 --gpus=1 --mem=5240 --workers=16 --ram=60 --scratch=80 --fake=True

python tools/cluster/push_and_run_folder.py --exp=coco_train --time=24 --gpus=1 --mem=5240 --workers=16 --ram=60 --scratch=80
"""
parser = argparse.ArgumentParser()
parser.add_argument(
  "--exp", default="exp", required=True, help="Folder containing experiment yaml file."
)
parser.add_argument("--time", default=24, required=True, help="Runtime.")
parser.add_argument("--mem", default=5240, help="Min GPU Memory")
parser.add_argument("--gpus", default=1)
parser.add_argument("--workers", default=16)
parser.add_argument("--ram", default=60)
parser.add_argument("--env", default="cfg/env/leonhard.yml")
parser.add_argument("--scratch", default=0, help="Total Scratch space in GB")
parser.add_argument("--fake", default=False, help="Not schedule")
parser.add_argument("--ignore_workers", default=False, help="Ignore workers")
parser.add_argument("--fast_gpu", default=True, help="Select script to start")
parser.add_argument("--host", default="euler", choices=["leonhard", "euler"])


args = parser.parse_args()
if args.host == "leonhard":
  login = "jonfrey@login.leonhard.ethz.ch"
  export_cmd = """export LSF_ENVDIR=/cluster/apps/lsf/conf; export LSF_SERVERDIR=/cluster/apps/lsf/10.1/linux3.10-glibc2.17-x86_64/etc;"""
  bsub_cmd = """/cluster/apps/lsf/10.1/linux3.10-glibc2.17-x86_64/bin/bsub"""

elif args.host == "euler":
  login = "jonfrey@euler.ethz.ch"
  export_cmd = """export LSF_ENVDIR=/cluster/apps/lsf/conf; export LSF_SERVERDIR=/cluster/apps/lsf/10.1/linux2.6-glibc2.3-x86_64/etc;"""
  bsub_cmd = """/cluster/apps/lsf/10.1/linux2.6-glibc2.3-x86_64/bin/bsub"""

env = f"cfg/env/{args.host}.yml"
w = int(args.workers)
gpus = int(args.gpus)
ram = int(int(args.ram) * 1000 / w)
print("#" * 80)
print(" " * 25 + f"All jobs will be run for {args.time}h")
print("#" * 80)
mem = args.mem
if args.time == "120":
  s1 = "119:59"
elif args.time == "24":
  s1 = "23:59"
elif args.time == "4":
  s1 = "3:59"
elif isinstance(args.time, str):
  s1 = args.time
else:
  raise Exception
scratch = int(int(args.scratch) * 1000 / w)
fake = args.fake
ign = args.ignore_workers
# Get all model_paths
home = expanduser("~")
p = f"{home}/ASL/cfg/exp/{args.exp}/"
exps = [str(p) for p in Path(p).rglob("*.yml") if str(p).find("_tmp.yml") == -1]
model_paths = []
print("")
print("Found Config Files in directory:")
for j, e in enumerate(exps):
  print("   " + e)
  with open(e) as f:
    doc = yaml.load(f, Loader=yaml.FullLoader)

  if not ign and doc["loader"]["num_workers"] != w:
    logging.warning("   Error: Number of workers dosent align with requested cores!")
    logging.warning("   Error: Either set ignore_workers flag true or change config")
    exps.remove(e)
  # Validate if config trainer settings fits with job.
  elif gpus > 1 and doc["trainer"]["accelerator"].find("ddp") == -1:
    logging.warning("   Error: Mutiple GPUs but not using ddp")
    exps.remove(e)
  elif doc["trainer"]["gpus"] != gpus and doc["trainer"]["gpus"] != -1:
    logging.warning(f"   Error: Nr GPUS does not match job")
    exps.remove(e)
  else:
    model_paths.append(doc["name"])

print("")

if len(model_paths) == 0:
  print("Model Paths Empty!")

else:

  with open(os.path.join(home, "ASL", env)) as f:
    doc = yaml.load(f, Loader=yaml.FullLoader)
    base = doc["base"]
  model_paths = [os.path.join(base, i) for i in model_paths]

  # Push to cluster
  cmd = f"""rsync -a --delete --exclude='.git/' --exclude='__pycache__/' --exclude='cfg/exp/tmp/*' --exclude='notebooks/*' --exclude='docs/*' {home}/ASL/* {login}:/cluster/home/jonfrey/ASL"""
  os.system(cmd)

  # Executue commands on cluster
  import paramiko

  try:

    host = login[login.find("@") + 1 :]
    port = 22
    username = "jonfrey"
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    # ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(host, port, username)
    ssh.connect(host, port, username)

    N = len(exps)
    print(f"Using bsub to schedule {N}-jobs:")
    for j, e in enumerate(exps):
      e = e.replace("/home/jonfrey/ASL/", "")
      print("   Model Path:" + model_paths[j])
      p = model_paths[j].split("/")
      p = "/".join(p[:-1])

      # Remote make Path
      cmd = f"mkdir -p {p}"
      stdin, stdout, stderr = ssh.exec_command(cmd)

      name = model_paths[j].split("/")[-1] + str(j) + ".out"
      o = f""" -oo {p}/{name} """
      cmd = f"""bsub{o} -n {w} -W {s1} -R "rusage[mem={ram},ngpus_excl_p={gpus}]" """

      if scratch > 0:
        cmd += f"""-R "rusage[scratch={scratch}]" """

      if bool(args.fast_gpu):
        cmd += """ -R "select[gpu_model0==GeForceRTX2080Ti]" """
      else:
        cmd += f""" -R "select[gpu_mtotal0>={mem}]" """
      subscr = "submit_supervisor"

      cmd += f""" /cluster/home/jonfrey/miniconda3/envs/track4/bin/python supervisor.py --exp={e} --mode=shell """
      cmd = cmd.replace("\n", "")
      t = ""
      cmd = (
        """source /cluster/apps/local/env2lmod.sh && module purge && module load gcc/6.3.0 && module load hdf5 eth_proxy python_gpu/3.8.5 && cd $HOME/ASL && """
        + cmd
      )
      print(cmd)
      # cmd = "echo $MODELS"
      print(f"   {j}-Command: {cmd}")

      if not fake:
        stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
        # a = stdin.readlines()
        b = stdout.readlines()
        c = stderr.readlines()
        print(f"   {j}-Results: {b} {c} ")
      else:
        print("   Fake Flag is set")
      # Remote schedule jobs
  finally:
    if ssh is not None:
      ssh.close()
      try:
        del ssh, stdin, stdout, stderr
      except:
        pass
