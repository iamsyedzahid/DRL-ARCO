# Setting up ns-3

This installs ns-3.40 with the ns3-gym module and builds the DRL-ARCO scenario. Allow about an hour the first time; most of it is the build.

**Versions:** Ubuntu 22.04, ns-3.40 and the `app-ns-3.36+` branch of ns3-gym. ns3-gym's own instructions use ns-3.40, so stay on this combination unless you have a reason to change it.

If you already run Ubuntu 22.04, skip to [Step 3](#step-3-get-the-project-inside-ubuntu).

## Step 1: Turn on CPU virtualization (Windows)

WSL2 needs this. To check it, open **Task Manager > Performance > CPU** and look for **Virtualization: Enabled**.

If it says Disabled:

1. Restart the laptop and enter the BIOS. The key depends on the model:
   - **Lenovo ThinkPad:** tap **F1** at the logo.
   - **Other Lenovo laptops:** press **F2** or **Fn+F2**, or use the **Novo** button if there is one.
   - **Any Windows laptop:** go to **Settings > System > Recovery > Advanced startup > Restart now**, then **Troubleshoot > Advanced options > UEFI Firmware Settings**.
2. Find the setting under **Security > Virtualization**, **Config > CPU** or **Configuration**. It is called **Intel Virtualization Technology**, **Intel VT-x** or **AMD-V / SVM**.
3. Turn it on, then save and exit (often F10).
4. Back in Windows, confirm Task Manager shows **Virtualization: Enabled** before continuing. The next step fails without it.

## Step 2: Install WSL2 and Ubuntu 22.04 (Windows)

1. Right-click **Start** and choose **Terminal (Admin)**, then install WSL's components:

   ```powershell
   wsl --install --no-distribution
   ```

2. Restart Windows.
3. Open a **normal** terminal, not Admin, because WSL keeps a separate list of distributions for each Windows account. Install Ubuntu and keep the window open until it asks for a username:

   ```powershell
   wsl --install -d Ubuntu-22.04
   ```

4. Create a username and password. This password is what `sudo` asks for later. To reopen Ubuntu later, run `wsl -d Ubuntu-22.04`.

To check what is installed, run `wsl -l -v`.

Run every remaining command **inside the Ubuntu window**.

## Step 3: Get the project inside Ubuntu

Keep the project in Ubuntu's own disk (`~`), not under `/mnt/d`. Builds and file access are much slower across the Windows boundary, and Windows line endings can break the scripts.

**If the project is on GitHub:**

```bash
sudo apt-get update && sudo apt-get install -y git
cd ~
git clone https://github.com/<your-account>/DRL-ARCO.git
cd DRL-ARCO
```

**If it is only on your D: drive so far:**

```bash
sudo apt-get update && sudo apt-get install -y rsync dos2unix
cd ~
rsync -a --exclude .venv --exclude __pycache__ /mnt/d/DRL-ARCO/ DRL-ARCO/
cd DRL-ARCO
find scripts -name '*.sh' -exec dos2unix {} +
```

## Step 4: Build ns-3 and the scenario

```bash
bash scripts/install_ns3.sh
```

The script does the following:

1. Installs the compiler, CMake, ZeroMQ and protobuf packages.
2. Downloads ns-3.40 to `~/ns-allinone/ns-3.40`.
3. Adds ns3-gym as `contrib/opengym`.
4. Copies `ns3/scratch/drl-arco` into ns-3's `scratch` folder.
5. Configures and builds only the modules this project needs.

You do not need to run `pip install ./model/ns3gym`, which ns3-gym's own guide asks for. This project has its own Python bridge (see [ARCHITECTURE.md](ARCHITECTURE.md#why-not-the-ns3gym-python-package)).

When it finishes, tell your shell where ns-3 lives:

```bash
echo 'export NS3_HOME="$HOME/ns-allinone/ns-3.40"' >> ~/.bashrc
source ~/.bashrc
```

## Step 5: Set up Python

```bash
cd ~/DRL-ARCO
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[ns3,dev]"
python scripts/gen_proto.py
```

Leave out the `--index-url` part if you have an NVIDIA GPU and want the CUDA build. The training network is small, so CPU is fine.

Run `source .venv/bin/activate` again each time you open a new terminal.

## Step 6: Check that everything works

```bash
bash scripts/check_ns3.sh
```

This runs a 10-second simulation with real ns-3 traffic. Every line should start with `OK`, and the script should exit without an error. **Do this before trusting any ns-3 result.**

## Step 7: Use it

```bash
python -m drl_arco train --backend ns3 --episodes 120
python -m drl_arco benchmark --backend ns3 --seeds 10
python -m drl_arco gui
```

For the dashboard, open <http://127.0.0.1:8000> in your Windows browser. WSL2 forwards localhost automatically. Choose **ns-3** in the Simulator menu.

Results go to `results/benchmark_ns3.csv` and `.json`.

## After editing the C++

```bash
bash scripts/sync_ns3.sh
(cd "$NS3_HOME" && ./ns3 build drl-arco)
bash scripts/check_ns3.sh
```

## Running the two sides by hand

Useful when debugging the C++, because you see all of its output:

```bash
cd "$NS3_HOME"
NS_LOG="RoutingGymEnv=level_all" ./ns3 run "drl-arco --simTime=2"
```

This waits for an agent on port 5555. The Python bridge normally chooses a free port and starts ns-3 itself, so use this form only for looking at the scenario's startup.

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `HCS_E_HYPERV_NOT_INSTALLED` or another virtualization error from `wsl --install` | CPU virtualization is off, or Windows has not restarted since enabling WSL's components. Redo Steps 1 and 2. |
| `/usr/bin/env: 'bash\r': No such file` | Windows line endings. Run `find scripts -name '*.sh' -exec dos2unix {} +`. |
| `zeromq not found` or `protobuf not found` during configure | The opengym module was skipped. Install `libzmq3-dev libprotobuf-dev protobuf-compiler pkg-config`, then run `./ns3 clean` and repeat the configure and build lines from `bash scripts/install_ns3.sh`. |
| `Invalid command-line argument` or target `drl-arco` not found | The scenario was not copied. Run `bash scripts/sync_ns3.sh`, then rebuild. |
| The GUI shows "ns-3 (not set up)" | Hover over the menu for the reason. Usually `NS3_HOME` is not set in the terminal that started the GUI. |
| `No module named ...messages_pb2` | Run `python scripts/gen_proto.py`. |
| `no message from ns-3 in 120 s` | ns-3 crashed or never started. Run `(cd "$NS3_HOME" && ./ns3 run "drl-arco --simTime=2")` to see the error. |
| The compiler is killed during the build | Out of memory. Add `-j2` to limit parallel jobs: `./ns3 build -j2 drl-arco`. |

## Native Windows

ns-3 also supports MSYS2/MinGW, but ns3-gym calls `getppid`, which MinGW does not provide, so it would need a small patch. This project has not been tested that way. WSL2 is the supported route.
