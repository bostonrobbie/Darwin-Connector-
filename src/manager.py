import subprocess
import time
import sys
import os
import signal
import logging
from colorama import Fore, Style
import psutil

import logging
import requests
from colorama import Fore, Style

logger = logging.getLogger("Supervisor")

class ProcessManager:
    def __init__(self, config):
        self.config = config
        self.processes = {}
        self.start_times = {} 
        self.restart_stats = {} # {name: {'count': 0, 'last_restart': 0}}
        self.running = True

    def log(self, msg, color=Fore.WHITE):
        """Color-coded logging."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"{Fore.CYAN}[{timestamp}]{color} {msg}{Style.RESET_ALL}")
        logger.info(msg)

    def launch_external_app(self, name, path):
        """Launches an external GUI application."""
        # Check if we should use IBC for TWS
        if "tws" in name.lower() and "ibc" in self.config.get('ibkr', {}).get('tws_login_mode', 'standard'):
            path = "C:\\IBC\\StartIBC_Custom.bat"
            name = "IBC_Auto_Login"
            
        if not os.path.exists(path):
            self.log(f"Cannot launch {name}: Path not found {path}", Fore.RED)
            return False # Changed from `return` to `return False` for consistency with original logic
            
        self.log(f"Launching {name}...", Fore.CYAN)
        try:
            subprocess.Popen(
                [path], 
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                shell=False,
                close_fds=True
            )
            return True
        except Exception as e:
            self.log(f"Failed to launch {name}: {e}", Fore.RED)
            return False

    def start_process(self, name, command, cwd=None, stdout=None, stderr=None):
        """Starts a process and tracks it."""
        if name in self.processes and self.processes[name].poll() is None:
            # Silent return to avoid log spam in lookups
            return

        self.log(f"Starting {name}...", Fore.CYAN)
        
        try:
            # Determine output
            if stdout is None:
                stdout = sys.stdout if "Bridge" in name else subprocess.DEVNULL
            if stderr is None:
                stderr = sys.stderr if "Bridge" in name else subprocess.DEVNULL
            
            proc = subprocess.Popen(
                command, 
                shell=True, 
                cwd=cwd,
                stdout=stdout,
                stderr=stderr
            )

            self.processes[name] = proc
            self.start_times[name] = time.time()
            self.log(f"STARTED {name} (PID: {proc.pid})", Fore.GREEN)
        except Exception as e:
            self.log(f"Failed to start {name}: {e}", Fore.RED)

    def start_tunnel(self, port, subdomain, name="Tunnel"):
        """Starts a localtunnel instance."""
        # Using npx localtunnel
        cmd = f"npx localtunnel --port {port} --subdomain {subdomain}"
        log_file = open(f"logs/{name}.log", "w")
        
        self.log(f"Starting {name} on port {port} (subdomain: {subdomain})...", Fore.CYAN)
        return self.start_process(name, cmd, stdout=log_file, stderr=log_file)

    def start_backup_tunnel(self, port, name="Backup_Tunnel", type="serveo"):
        """Starts a backup SSH tunnel (Serveo/Pinggy)."""
        if type == "serveo":
            # Serveo exposes http on port 80 via ssh
            # ssh -R 80:localhost:PORT serveo.net
            # Note: Serveo might assign a random subdomain if custom is taken/not requested.
            # We can request one with -R alias:80:localhost:PORT
            alias = f"bostonrobbie-{port}" # Try to keep it unique but recognizable
            cmd = f"ssh -o StrictHostKeyChecking=no -R {alias}:80:localhost:{port} serveo.net"
            
            log_file = open(f"logs/{name}.log", "w")
            self.log(f"Starting {name} (Serveo) on port {port}...", Fore.MAGENTA)
            return self.start_process(name, cmd, stdout=log_file, stderr=log_file)
    
    def stop_process(self, name):
        """Stops a specific process."""
        if name in self.processes:
            proc = self.processes[name]
            self.log(f"Stopping {name} (PID: {proc.pid})...", Fore.MAGENTA)
            try:
                # Murder child process and its children (important for shell=True)
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
            except Exception as e:
                self.log(f"Error stopping {name}: {e}", Fore.RED)
            
            del self.processes[name]

    def cleanup(self):
        """Stops all processes."""
        self.log("Shutting down all processes...", Fore.YELLOW)
        for name in list(self.processes.keys()):
            self.stop_process(name)

    def check_tws_process(self):
        """Checks if TWS/Gateway is actually running OS-level."""
        found = False
        for proc in psutil.process_iter(['name']):
            try:
                # TWS is java.exe usually, but could be tws.exe wrapper
                if proc.info['name'] in ['tws.exe', 'ibgateway.exe', 'java.exe']:
                    # Simple heuristic
                    found = True
                    # If strictly java.exe, we might match other java apps, but for this dedicated machine it's likely TWS.
                    # We could check cmdline if needed but it requires privileges sometimes.
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found
        
    def check_mt5_process(self):
        """Checks if MT5 Terminal is running."""
        found = False
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] in ['terminal64.exe', 'terminal.exe']:
                    found = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return found
            
    def monitor(self):
        """Main loop to check process health."""
        # Clean up zombies
        for name, proc in list(self.processes.items()):
            if proc.poll() is not None: # It died
                code = proc.returncode
                self.log(f"ALERT: {name} died (Exit Code: {code})", Fore.RED)
                del self.processes[name]
                
                # Logic to auto-restart?
                # For now, let's just log. The main loop can decide to restart.
                
        time.sleep(1)

    def check_health(self, name, url):
        """Pings a service to ensure it's responsive."""
        if name not in self.processes: return
        
        # Warmup Grace Period (5s)
        if time.time() - self.start_times.get(name, 0) < 5:
            return

        try:
            r = requests.get(f"{url}/health", timeout=15)
            if r.status_code != 200:
                raise Exception(f"Status {r.status_code}")
            return r.json()
        except Exception as e:
            self.log(f"WARNING: {name} Health Check Failed: {e}", Fore.YELLOW)
            # self.stop_process(name) # Optional: Don't kill immediately on one fail? 
            # But original logic was to kill. Let's keep it for now but maybe allow main.py to handle?
            # Actually, if health check fails (timeout), the bridge might be hung. Killing is safer.
            self.stop_process(name)
            return None

    def check_public_health(self, name, public_url, port_check=True):
        """Checks if the public tunnel URL is actually reachable."""
        if name not in self.processes: return
        
        # Warmup Grace Period (45s for tunnels, they are slow)
        if time.time() - self.start_times.get(name, 0) < 45:
            return

        try:
            target = f"{public_url}/health"
            r = requests.get(target, timeout=15)
            
            if r.status_code != 200:
                 self.log(f"WARNING: Public Tunnel {name} returned {r.status_code}", Fore.YELLOW)
                 self.stop_process(name)
                 
        except Exception as e:
            self.log(f"WARNING: Public Tunnel {name} Unreachable: {e}", Fore.YELLOW)
            self.stop_process(name)

    def should_restart(self, name):
        """Implements Exponential Backoff for restarts."""
        now = time.time()
        
        if name not in self.restart_stats:
            self.restart_stats[name] = {'count': 0, 'last_restart': 0}
            
        stats = self.restart_stats[name]
        
        # Reset count if it's been stable for 5 minutes
        if now - stats['last_restart'] > 300:
            stats['count'] = 0
            
        delay = min(2 ** stats['count'], 60) # Max 60s delay
        
        if now - stats['last_restart'] < delay:
            return False # Not ready yet
            
        return True

    def register_restart(self, name):
        """Updates restart stats."""
        now = time.time()
        if name not in self.restart_stats:
            self.restart_stats[name] = {'count': 0, 'last_restart': now}
        else:
            self.restart_stats[name]['count'] += 1
            self.restart_stats[name]['last_restart'] = now
            
        count = self.restart_stats[name]['count']
        if count > 1:
            self.log(f"Restarting {name} (Attempt #{count}). Fast restarts detected.", Fore.YELLOW)

    def kill_port(self, port):
        """Force kills any process holding a specific port."""
        import psutil
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    for conn in proc.connections(kind='inet'):
                        if conn.laddr.port == port:
                            # Skip System Idle Process (PID 0)
                            if proc.pid == 0: continue
                            
                            self.log(f"Killing {proc.name()} (PID: {proc.pid}) on port {port}", Fore.YELLOW)
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            self.log(f"Error killing port {port}: {e}", Fore.RED)
