#!/usr/bin/env python3
"""
Dynamic Agent Dashboard - System Runner
Starts and manages the complete system including backend API and frontend dashboard.
"""

import os
import sys
import time
import signal
import subprocess
import asyncio
import argparse
import requests
from pathlib import Path
from typing import Optional, List

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

class Colors:
    """Terminal colors for pretty output."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

class SystemRunner:
    """Manages the complete Dynamic Agent Dashboard system."""
    
    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        self.backend_process: Optional[subprocess.Popen] = None
        self.frontend_process: Optional[subprocess.Popen] = None
        self.backend_pid: Optional[int] = None
        self.frontend_pid: Optional[int] = None
        self.running = False
        
        # Configuration
        self.backend_port = 8000
        self.frontend_port = 8501
        self.backend_url = f"http://localhost:{self.backend_port}"
        self.frontend_url = f"http://localhost:{self.frontend_port}"
        
        # Health check configuration
        self.health_check_interval = 30  # Check every 30 seconds
        self.health_check_timeout = 5    # 5 second timeout for health checks
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def log(self, message: str, color: str = Colors.OKBLUE, prefix: str = "INFO"):
        """Print colored log message."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"{color}[{timestamp}] [{prefix}]{Colors.ENDC} {message}")
    
    def success(self, message: str):
        """Print success message."""
        self.log(message, Colors.OKGREEN, "SUCCESS")
    
    def warning(self, message: str):
        """Print warning message."""
        self.log(message, Colors.WARNING, "WARNING")
    
    def error(self, message: str):
        """Print error message."""
        self.log(message, Colors.FAIL, "ERROR")
    
    def header(self, message: str):
        """Print header message."""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}")
        print(f"  {message}")
        print(f"{'='*60}{Colors.ENDC}\n")
    
    def check_dependencies(self) -> bool:
        """Check if all required dependencies are available."""
        self.log("Checking system dependencies...")
        
        # Check Python version
        if sys.version_info < (3, 11):
            self.error(f"Python 3.11+ required, found {sys.version}")
            return False
        
        # Check if running in UV environment
        if "VIRTUAL_ENV" not in os.environ and "UV_PROJECT_ROOT" not in os.environ:
            self.warning("Not running in UV environment. Use 'uv run python run_system.py'")
        
        # Check if uv is available
        try:
            result = subprocess.run(["uv", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                self.success(f"UV package manager found: {result.stdout.strip()}")
            else:
                self.error("UV package manager not found")
                return False
        except FileNotFoundError:
            self.error("UV package manager not installed")
            return False
        
        # Check if .env file exists
        env_file = PROJECT_ROOT / ".env"
        if not env_file.exists():
            self.warning(".env file not found, using defaults")
            
        # Check database
        db_file = PROJECT_ROOT / "dynamic_agent_dashboard.db"
        if not db_file.exists():
            self.warning("Database not found, will be created automatically")
        
        return True
    
    async def initialize_database(self) -> bool:
        """Initialize the database."""
        self.log("Initializing database...")
        
        try:
            # Set environment variables
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            
            # Run database initialization
            result = subprocess.run([
                "uv", "run", "python", "scripts/init_db.py"
            ], capture_output=True, text=True, env=env, cwd=PROJECT_ROOT)
            
            if result.returncode == 0:
                self.success("Database initialized successfully")
                return True
            else:
                self.error(f"Database initialization failed: {result.stderr}")
                return False
                
        except Exception as e:
            self.error(f"Database initialization error: {str(e)}")
            return False
    
    async def initialize_coordinator(self) -> bool:
        """Initialize the coordinator agent."""
        self.log("Initializing coordinator agent...")
        
        try:
            # Test basic imports first
            import sqlalchemy
            self.log(f"SQLAlchemy available: {sqlalchemy.__version__}")
            
            from backend.services.coordinator_startup import coordinator_startup
            self.log("Coordinator startup service imported successfully")
            
            success = await coordinator_startup.ensure_coordinator_exists()
            
            if success:
                self.success("Coordinator agent initialized successfully")
                return True
            else:
                self.error("Failed to initialize coordinator agent")
                return False
                
        except ImportError as e:
            self.error(f"Import error during coordinator initialization: {str(e)}")
            import traceback
            print(f"Import traceback: {traceback.format_exc()}")
            return False
        except Exception as e:
            self.error(f"Coordinator initialization error: {str(e)}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def start_backend(self) -> bool:
        """Start the FastAPI backend server."""
        self.log("Starting backend API server...")
        
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            
            self.backend_process = subprocess.Popen([
                "uv", "run", "uvicorn", 
                "backend.main:app",
                "--host", "127.0.0.1",
                "--port", str(self.backend_port),
                "--reload"
            ], env=env, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            self.processes.append(self.backend_process)
            self.backend_pid = self.backend_process.pid
            
            # Wait for backend to start
            for i in range(30):  # Wait up to 30 seconds
                try:
                    response = requests.get(f"{self.backend_url}/health", timeout=1)
                    if response.status_code == 200:
                        self.success(f"Backend API started successfully at {self.backend_url}")
                        return True
                except requests.exceptions.RequestException:
                    pass
                
                time.sleep(1)
                self.log(f"Waiting for backend to start... ({i+1}/30)")
            
            # Check if process has died using process existence
            try:
                os.kill(self.backend_pid, 0)  # Signal 0 checks if process exists
                self.error("Backend failed to start within 30 seconds (process still running)")
            except ProcessLookupError:
                stdout, stderr = self.backend_process.communicate()
                self.error("Backend process died during startup")
                if stderr:
                    print(f"Backend stderr: {stderr}")
                if stdout:
                    print(f"Backend stdout: {stdout}")
            
            return False
            
        except Exception as e:
            self.error(f"Failed to start backend: {str(e)}")
            return False
    
    def start_frontend(self) -> bool:
        """Start the Streamlit frontend."""
        self.log("Starting frontend dashboard...")
        
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            
            self.frontend_process = subprocess.Popen([
                "uv", "run", "streamlit", "run", 
                "frontend/main.py",
                "--server.port", str(self.frontend_port),
                "--server.address", "127.0.0.1",
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false"
            ], env=env, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            self.processes.append(self.frontend_process)
            self.frontend_pid = self.frontend_process.pid
            
            # Wait for frontend to start
            for i in range(20):  # Wait up to 20 seconds
                try:
                    response = requests.get(self.frontend_url, timeout=1)
                    if response.status_code == 200:
                        self.success(f"Frontend dashboard started successfully at {self.frontend_url}")
                        return True
                except requests.exceptions.RequestException:
                    pass
                
                time.sleep(1)
                self.log(f"Waiting for frontend to start... ({i+1}/20)")
            
            # Frontend might be starting, check if process is alive
            try:
                os.kill(self.frontend_pid, 0)
                self.success(f"Frontend dashboard starting at {self.frontend_url}")
                return True
            except ProcessLookupError:
                self.error("Frontend process died during startup")
                return False
            
        except Exception as e:
            self.error(f"Failed to start frontend: {str(e)}")
            return False
    
    def check_system_health(self) -> dict:
        """Check the health of all system components."""
        health = {
            "backend": False,
            "frontend": False,
            "database": False
        }
        
        # Check backend
        try:
            response = requests.get(f"{self.backend_url}/health", timeout=2)
            health["backend"] = response.status_code == 200
        except:
            pass
        
        # Check frontend
        try:
            response = requests.get(self.frontend_url, timeout=2)
            health["frontend"] = response.status_code == 200
        except:
            pass
        
        # Check database
        db_file = PROJECT_ROOT / "dynamic_agent_dashboard.db"
        health["database"] = db_file.exists()
        
        return health
    
    def print_system_status(self):
        """Print current system status."""
        self.header("SYSTEM STATUS")
        
        health = self.check_system_health()
        
        # Backend status
        if health["backend"]:
            self.success(f"✓ Backend API: {self.backend_url}")
        else:
            self.error(f"✗ Backend API: {self.backend_url}")
        
        # Frontend status
        if health["frontend"]:
            self.success(f"✓ Frontend Dashboard: {self.frontend_url}")
        else:
            self.error(f"✗ Frontend Dashboard: {self.frontend_url}")
        
        # Database status
        if health["database"]:
            self.success("✓ Database: Connected")
        else:
            self.error("✗ Database: Not found")
        
        # Process status using PID checks
        if self.backend_pid:
            try:
                os.kill(self.backend_pid, 0)
                self.success("✓ Backend Process: Running")
            except ProcessLookupError:
                self.error("✗ Backend Process: Not running")
        else:
            self.error("✗ Backend Process: Not started")
        
        if self.frontend_pid:
            try:
                os.kill(self.frontend_pid, 0)
                self.success("✓ Frontend Process: Running")
            except ProcessLookupError:
                self.error("✗ Frontend Process: Not running")
        else:
            self.error("✗ Frontend Process: Not started")
        
        print(f"\n{Colors.OKCYAN}Quick Links:{Colors.ENDC}")
        print(f"  • API Documentation: {self.backend_url}/docs")
        print(f"  • OpenAPI Schema: {self.backend_url}/api/v1/openapi.json")
        print(f"  • Dashboard: {self.frontend_url}")
    
    def stop_all_processes(self):
        """Stop all running processes."""
        self.log("Stopping all processes...")
        
        for process in self.processes:
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except:
                    pass
        
        self.processes.clear()
        self.backend_process = None
        self.frontend_process = None
        self.running = False
        
        self.success("All processes stopped")
    
    def signal_handler(self, signum, frame):
        """Handle system signals for graceful shutdown."""
        self.log(f"Received signal {signum}, shutting down...")
        self.stop_all_processes()
        sys.exit(0)
    
    async def run_system(self, init_db: bool = True, open_browser: bool = True):
        """Run the complete system."""
        self.header("DYNAMIC AGENT DASHBOARD")
        self.log("Starting Dynamic Agent Dashboard system...")
        
        # Check dependencies
        if not self.check_dependencies():
            self.error("Dependency check failed")
            return False
        
        # Initialize database if requested
        if init_db:
            if not await self.initialize_database():
                self.error("Database initialization failed")
                return False
            
            # Initialize coordinator agent
            if not await self.initialize_coordinator():
                self.warning("Coordinator initialization failed, continuing...")
                # Don't fail system startup if coordinator fails
        
        # Start backend
        if not self.start_backend():
            self.error("Backend startup failed")
            return False
        
        # Start frontend
        if not self.start_frontend():
            self.error("Frontend startup failed")
            return False
        
        # System is running
        self.running = True
        
        # Print status
        time.sleep(2)  # Give services time to fully start
        self.print_system_status()
        
        # Open browser if requested
        if open_browser:
            try:
                import webbrowser
                self.log("Opening browser...")
                webbrowser.open(self.frontend_url)
            except:
                self.warning("Could not open browser automatically")
        
        # Keep running and monitor
        self.header("SYSTEM RUNNING")
        self.log("System is running. Press Ctrl+C to stop.")
        self.log("Monitoring system health...")
        
        try:
            while self.running:
                # Use HTTP health checks instead of poll()
                health = self.check_system_health()
                
                # Only report actual failures (when HTTP endpoints are down)
                if not health["backend"]:
                    # Double-check if process is actually dead
                    if self.backend_pid:
                        try:
                            os.kill(self.backend_pid, 0)
                            # Process exists but not responding - might be temporary
                            self.warning("Backend not responding to health checks (process still running)")
                        except ProcessLookupError:
                            self.error("Backend process died unexpectedly")
                            break
                    else:
                        self.error("Backend health check failed")
                        break
                
                if not health["frontend"]:
                    # Double-check if process is actually dead
                    if self.frontend_pid:
                        try:
                            os.kill(self.frontend_pid, 0)
                            # Process exists but not responding - this is normal for Streamlit
                            pass  # Streamlit might not respond to HTTP immediately
                        except ProcessLookupError:
                            self.error("Frontend process died unexpectedly")
                            break
                    else:
                        self.error("Frontend health check failed")
                        break
                
                # Wait before next check
                await asyncio.sleep(self.health_check_interval)
                
        except KeyboardInterrupt:
            self.log("Received interrupt signal")
        
        # Cleanup
        self.stop_all_processes()
        return True
    
    async def test_system(self):
        """Run system tests."""
        self.header("SYSTEM TESTS")
        
        # Run the test script
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            
            result = subprocess.run([
                "uv", "run", "python", "test_api.py"
            ], env=env, cwd=PROJECT_ROOT)
            
            return result.returncode == 0
            
        except Exception as e:
            self.error(f"Test execution failed: {str(e)}")
            return False

async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Dynamic Agent Dashboard System Runner")
    parser.add_argument("--no-init-db", action="store_true", help="Skip database initialization")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    parser.add_argument("--test-only", action="store_true", help="Run tests only")
    parser.add_argument("--status-only", action="store_true", help="Show status only")
    
    args = parser.parse_args()
    
    runner = SystemRunner()
    
    try:
        if args.test_only:
            # Run tests only
            success = await runner.test_system()
            sys.exit(0 if success else 1)
        
        elif args.status_only:
            # Show status only
            runner.print_system_status()
            sys.exit(0)
        
        else:
            # Run full system
            success = await runner.run_system(
                init_db=not args.no_init_db,
                open_browser=not args.no_browser
            )
            sys.exit(0 if success else 1)
    
    except Exception as e:
        runner.error(f"Unexpected error: {str(e)}")
        runner.stop_all_processes()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())