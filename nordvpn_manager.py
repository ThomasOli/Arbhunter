"""
NordVPN manager for handling VPN connections to access Polymarket.
Updated for Windows NordVPN CLI commands.
"""
import subprocess
import time
import re
import os
from typing import Optional, Tuple
from config.settings import settings
from src.utils.logger import app_logger


class NordVPNManager:
    """Manages NordVPN connections for accessing geo-restricted APIs."""
    
    def __init__(self):
        self.is_connected = False
        self.current_server = None
        self.nordvpn_path, self.nordvpn_dir = self._get_nordvpn_path()
        
    def _get_nordvpn_path(self) -> Tuple[str, Optional[str]]:
        """Get the correct NordVPN executable path for Windows."""
        nordvpn_dir = r"C:\Program Files\NordVPN"
        nordvpn_exe = "nordvpn"
        
        try:
            # Test if the executable exists and works using version command
            result = subprocess.run([nordvpn_exe, "-v"], capture_output=True, timeout=5, cwd=nordvpn_dir)
            if result.returncode == 0:
                app_logger.info(f"Found NordVPN at: {nordvpn_dir}")
                return nordvpn_exe, nordvpn_dir
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
                
        # Default fallback - assume it's in PATH
        app_logger.warning("Could not find NordVPN executable at C:\\Program Files\\NordVPN, trying 'nordvpn' from PATH")
        return "nordvpn", None
        
    def check_nordvpn_installation(self) -> bool:
        """Check if NordVPN CLI is installed."""
        try:
            kwargs = {"capture_output": True, "text": True, "timeout": 10}
            if self.nordvpn_dir:
                kwargs["cwd"] = self.nordvpn_dir
            
            result = subprocess.run([self.nordvpn_path, "-v"], **kwargs)
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            app_logger.error("NordVPN CLI not found. Please install NordVPN for Windows.")
            return False
    
    def check_login_status(self) -> bool:
        """Check if NordVPN is already logged in."""
        # Windows NordVPN CLI doesn't have account info command
        # Assume logged in if nordvpn.exe exists and is accessible
        app_logger.info("Assuming NordVPN is logged in (Windows CLI doesn't provide login status check)")
        return True
    
    def connect(self, country: Optional[str] = None) -> bool:
        """Connect to NordVPN server using Windows commands."""
        try:
            if not self.check_nordvpn_installation():
                return False
            
            country = country or NORDVPN_COUNTRY
            app_logger.info(f"Connecting to NordVPN server in {country}...")
            
            # Use Windows NordVPN command: nordvpn -c -g "Country"
            kwargs = {"capture_output": True, "text": True, "timeout": 60}
            if self.nordvpn_dir:
                kwargs["cwd"] = self.nordvpn_dir
            
            result = subprocess.run([self.nordvpn_path, "-c", "-g", country], **kwargs)
            
            if result.returncode == 0:
                self.is_connected = True
                self.current_server = self._get_current_server()
                app_logger.info(f"Successfully connected to NordVPN server: {self.current_server}")
                return True
            else:
                app_logger.error(f"Failed to connect to NordVPN: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            app_logger.error("NordVPN connection timed out")
            return False
        except Exception as e:
            app_logger.error(f"Error connecting to NordVPN: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from NordVPN using Windows commands."""
        try:
            app_logger.info("Disconnecting from NordVPN...")
            
            # Use Windows NordVPN command: nordvpn -d (or --disconnect)
            kwargs = {"capture_output": True, "text": True, "timeout": 30}
            if self.nordvpn_dir:
                kwargs["cwd"] = self.nordvpn_dir
            
            result = subprocess.run([self.nordvpn_path, "-d"], **kwargs)
            
            if result.returncode == 0:
                self.is_connected = False
                self.current_server = None
                app_logger.info("Successfully disconnected from NordVPN")
                return True
            else:
                app_logger.error(f"Failed to disconnect from NordVPN: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            app_logger.error("NordVPN disconnection timed out")
            return False
        except Exception as e:
            app_logger.error(f"Error disconnecting from NordVPN: {e}")
            return False
    
    def get_status(self) -> Tuple[bool, Optional[str]]:
        """Get current VPN connection status using Windows network commands."""
        try:
            # Windows NordVPN CLI doesn't have a direct status command
            # Use Windows netsh to check for active VPN connections
            result = subprocess.run(
                ["netsh", "interface", "show", "interface"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.lower()
                # Look for NordVPN TAP adapter or similar VPN indicators
                lines = output.split('\n')
                for line in lines:
                    if 'connected' in line and ('nordvpn' in line or 'tap' in line or 'vpn' in line):
                        # Found a connected VPN interface
                        self.is_connected = True
                        self.current_server = "NordVPN Connected"
                        app_logger.debug("VPN connection detected via network interface")
                        return True, self.current_server
                
                # No VPN connection found
                self.is_connected = False
                self.current_server = None
                return False, None
            else:
                # Fallback: try to connect and see if already connected
                return self._check_status_via_connect_attempt()
                
        except Exception as e:
            app_logger.warning(f"Primary VPN status check failed: {e}, trying fallback method")
            return self._check_status_via_connect_attempt()
    
    def _check_status_via_connect_attempt(self) -> Tuple[bool, Optional[str]]:
        """Check VPN status by attempting to connect (fallback method)."""
        try:
            # Try to connect - if already connected, NordVPN will indicate this
            kwargs = {"capture_output": True, "text": True, "timeout": 15}
            if self.nordvpn_dir:
                kwargs["cwd"] = self.nordvpn_dir
            
            result = subprocess.run([self.nordvpn_path, "-c"], **kwargs)
            
            output = result.stdout.lower() + result.stderr.lower()
            
            # Check for "already connected" or similar messages
            if any(phrase in output for phrase in ['already connected', 'currently connected', 'disconnect first']):
                self.is_connected = True
                self.current_server = "NordVPN Connected"
                app_logger.debug("VPN status: already connected (detected via connect attempt)")
                return True, self.current_server
            elif 'connected' in output and 'success' in output:
                # Connection was successful (wasn't connected before)
                self.is_connected = True
                self.current_server = "NordVPN Connected"
                app_logger.debug("VPN status: newly connected")
                return True, self.current_server
            else:
                # Not connected and connection failed
                self.is_connected = False
                self.current_server = None
                app_logger.debug("VPN status: not connected")
                return False, None
                
        except Exception as e:
            app_logger.error(f"Fallback VPN status check failed: {e}")
            self.is_connected = False
            self.current_server = None
            return False, None
    
    def _get_current_server(self) -> Optional[str]:
        """Get the currently connected server."""
        is_connected, server = self.get_status()
        return server if is_connected else None
    
    def ensure_connection(self, country: Optional[str] = None, max_retries: int = 3) -> bool:
        """Ensure VPN is connected, connect if not. Returns False if connection cannot be established after retries."""
        is_connected, _ = self.get_status()
        
        if is_connected:
            app_logger.info(f"VPN already connected to: {self.current_server}")
            return True
        
        target_country = country or NORDVPN_COUNTRY
        app_logger.info(f"VPN not connected, attempting to establish connection to {target_country}...")
        
        # Retry connection up to max_retries times
        for attempt in range(1, max_retries + 1):
            app_logger.info(f"VPN connection attempt {attempt}/{max_retries}")
            
            connection_result = self.connect(country)
            
            if connection_result:
                # Verify the connection was actually established
                is_connected, server = self.get_status()
                if is_connected:
                    app_logger.info(f"VPN connection verified and established to: {server}")
                    return True
                else:
                    app_logger.warning(f"Attempt {attempt}: VPN connection command succeeded but status shows not connected")
            else:
                app_logger.warning(f"Attempt {attempt}: Failed to establish VPN connection to {target_country}")
            
            # Wait before retry (except on last attempt)
            if attempt < max_retries:
                wait_time = 2 * attempt  # Progressive backoff: 2s, 4s, 6s
                app_logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
        
        app_logger.error(f"CRITICAL: Failed to establish VPN connection to {target_country} after {max_retries} attempts")
        return False
    
    def __enter__(self):
        """Context manager entry."""
        self.ensure_connection()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # VPN connection will remain active - manual disconnection required
        pass


# Global VPN manager instance
vpn_manager = NordVPNManager() 