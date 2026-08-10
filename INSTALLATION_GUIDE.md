# Bot Installation and User Guide

This guide provides step-by-step instructions on how to install and run the bot on your local system (laptop). The bot is built using Python, Streamlit (for the user interface), and Playwright (for browser automation). 

Instructions are provided for both **Linux (Ubuntu/Debian)** and **Windows**.

---

## 1. Prerequisites

### For Linux:
Before installing the Python packages, ensure your system has the following requirements:
- **Python 3.12** (or a compatible Python 3 version)
- **Xvfb**: A virtual display server, which is required to run the bot in the background without opening visible windows on your main screen.

**Terminal Command (Linux):**
```bash
sudo apt-get update
sudo apt-get install -y xvfb python3.12 python3.12-venv
```

### For Windows:
You can easily install Python 3.12 using the Windows Package Manager (`winget`) directly from your terminal.

**Terminal Command (Windows):**
```cmd
winget install -e --id Python.Python.3.12
```
*(Alternatively, you can download and install Python 3.12 from the [official Python website](https://www.python.org/downloads/). If installing manually, make sure to check the box that says **"Add Python to PATH"**).*

---

## 2. Setting Up the Virtual Environment

It is highly recommended to isolate the bot's dependencies inside a virtual environment (`venv`).

### For Linux:
```bash
# Navigate to the bot's directory
cd /path/to/playwright

# Create the virtual environment
python3.12 -m venv venv

# Activate the virtual environment
source venv/bin/activate
```

### For Windows:
Open **Command Prompt** (cmd) or **PowerShell**, then type:
```cmd
# Navigate to the bot's directory
cd \path\to\playwright

# Create the virtual environment
python -m venv venv

# Activate the virtual environment
venv\Scripts\activate
```
*(Note: You must activate the virtual environment every time you open a new terminal to run the bot).*

---

## 3. Installing Dependencies

With the virtual environment activated, install the required Python packages and their specific versions. (These commands are the exact same for both Linux and Windows).

### Required Packages:
- `streamlit` (v1.58.0): For the web interface.
- `playwright` (v1.60.0): For automating the browser interactions.
- `playwright-stealth` (v2.0.3): For bypassing bot detection during automation.
- `pandas` (v3.0.4): For data handling and history logs.

### Terminal Commands:
```bash
# Install the python packages
pip install streamlit==1.58.0 playwright==1.60.0 playwright-stealth==2.0.3 pandas==3.0.4

# Install the necessary Playwright browsers (Chromium is required)
playwright install chromium
```

---

## 4. How to Run the Bot

The bot is composed of two main parts:
1. **The Web Interface**: Used to configure tasks, manage profiles, and monitor the bot.
2. **The Background Worker**: The engine that executes the automated tasks in the background.

### For Linux:
Linux runs both parts using provided shell scripts that utilize `xvfb-run`. This ensures the automated browser runs seamlessly in a virtual display in the background.

**Step 4A: Start the Web Interface**
```bash
./start_background.sh
```
*You can access the interface by opening a web browser and navigating to `http://localhost:8501`. Logs are saved to `streamlit.log`.*

**Step 4B: Start the Background Worker**
```bash
./start_worker.sh
```
*Logs are saved to `worker.log`.*

### For Windows:
On Windows, you should open **two separate Command Prompt windows**. Activate the virtual environment in **both** windows (`venv\Scripts\activate`).

**Step 4A: Start the Web Interface (Window 1)**
```cmd
python -m streamlit run app.py
```
*Leave this window open. A browser will automatically open to `http://localhost:8501` displaying the Streamlit interface.*

**Step 4B: Start the Background Worker (Window 2)**
```cmd
python background_worker.py
```
*Leave this window open to keep the worker running. You will see its activity directly in the console.*

---

## 5. Troubleshooting & Maintenance

- **Stopping the Bot (Linux)**: Because they run in the background via `nohup`, you can stop them by killing their process IDs (PIDs):
  ```bash
  pkill -f streamlit
  pkill -f background_worker.py
  ```
- **Stopping the Bot (Windows)**: Simply click into the Command Prompt windows where the bot is running and press `Ctrl + C` to stop them, or close the terminal windows.
- **Session Locked**: If you encounter a "Browser in use" warning, make sure all manual Chrome windows opened by the bot are closed. The bot checks for a `SingletonLock` file and will refuse to start if another instance is actively using the same profile.
