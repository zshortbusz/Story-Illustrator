"""
pipeline/health_check.py: Deterministic health and environment diagnostic for human users and AI agents.
Checks Python version, required dependencies, backend connectivity (LM Studio, ComfyUI),
project directory structure, and workflow validity.
"""

import sys
import os
import json
import socket
from typing import Dict, Any

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass


def check_python_version() -> Dict[str, Any]:
    major, minor, micro = sys.version_info[:3]
    passed = (major == 3 and minor >= 10)
    return {
        "check": "python_version",
        "passed": passed,
        "version": f"{major}.{minor}.{micro}",
        "requirement": ">= 3.10",
        "message": f"Python {major}.{minor}.{micro}" + (" (Compatible)" if passed else " (Upgrade recommended to 3.10+)")
    }


def check_dependencies() -> Dict[str, Any]:
    required_packages = [
        ("requests", "requests"),
        ("websockets", "websockets"),
        ("flask", "flask"),
        ("Pillow", "PIL"),
        ("reportlab", "reportlab"),
    ]
    optional_packages = [
        ("mcp", "mcp"),
    ]
    
    missing_required = []
    installed = {}
    
    for display_name, import_name in required_packages:
        try:
            __import__(import_name)
            try:
                import importlib.metadata
                ver = importlib.metadata.version(display_name)
            except Exception:
                ver = "installed"
            installed[display_name] = ver
        except ImportError:
            missing_required.append(display_name)
            installed[display_name] = "missing"

    for display_name, import_name in optional_packages:
        try:
            __import__(import_name)
            try:
                import importlib.metadata
                ver = importlib.metadata.version(display_name)
            except Exception:
                ver = "installed"
            installed[display_name] = f"{ver} (optional)"
        except ImportError:
            installed[display_name] = "not installed (optional)"
            
    passed = len(missing_required) == 0
    return {
        "check": "dependencies",
        "passed": passed,
        "installed": installed,
        "missing_required": missing_required,
        "message": "All required dependencies installed" if passed else f"Missing required packages: {', '.join(missing_required)}"
    }


def check_service_connection(name: str, host_port_url: str, timeout: float = 1.5) -> Dict[str, Any]:
    """Test HTTP reachability of a service."""
    try:
        req = urllib.request.Request(host_port_url, headers={"User-Agent": "ASI-HealthCheck"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            return {
                "check": name,
                "url": host_port_url,
                "reachable": True,
                "http_status": status,
                "message": f"Connected to {name} at {host_port_url} (HTTP {status})"
            }
    except Exception as e:
        return {
            "check": name,
            "url": host_port_url,
            "reachable": False,
            "error": str(e),
            "message": f"Could not reach {name} at {host_port_url} (Service offline or on alternate port)"
        }


def check_directories() -> Dict[str, Any]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected_dirs = ["pipeline", "projects", "workflows", "tests", "config"]
    missing = [d for d in expected_dirs if not os.path.isdir(os.path.join(base_dir, d))]
    
    workflows_dir = os.path.join(base_dir, "workflows")
    workflows = [f for f in os.listdir(workflows_dir) if f.endswith(".json")] if os.path.isdir(workflows_dir) else []
    
    passed = len(missing) == 0 and len(workflows) > 0
    return {
        "check": "directories_and_workflows",
        "passed": passed,
        "missing_dirs": missing,
        "workflows_found": workflows,
        "message": f"Workspace intact, found {len(workflows)} workflow(s)" if passed else f"Missing directories: {missing}"
    }


def run_all_checks() -> Dict[str, Any]:
    lm_url = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234/v1/models")
    comfy_url = os.environ.get("COMFY_URL", "http://127.0.0.1:8188/system_stats")
    
    py_check = check_python_version()
    dep_check = check_dependencies()
    dir_check = check_directories()
    lm_check = check_service_connection("LM Studio", lm_url)
    comfy_check = check_service_connection("ComfyUI", comfy_url)
    
    core_ready = py_check["passed"] and dep_check["passed"] and dir_check["passed"]
    
    return {
        "status": "ready" if core_ready else "not_ready",
        "core_ready": core_ready,
        "services": {
            "lm_studio": lm_check,
            "comfyui": comfy_check
        },
        "environment": {
            "python": py_check,
            "dependencies": dep_check,
            "directories": dir_check
        }
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Automated Story Illustrator Health Check")
    parser.add_argument("--json", action="store_true", help="Output health diagnostic as raw JSON")
    args = parser.parse_args()
    
    results = run_all_checks()
    
    if args.json:
        print(json.dumps(results, indent=2))
        sys.exit(0 if results["core_ready"] else 1)
        
    print("\n=======================================================")
    print("   AUTOMATED STORY ILLUSTRATOR - HEALTH DIAGNOSTIC")
    print("=======================================================")
    print(f"[*] Python:       {results['environment']['python']['message']}")
    print(f"[*] Dependencies: {results['environment']['dependencies']['message']}")
    print(f"[*] Workspace:    {results['environment']['directories']['message']}")
    print("-------------------------------------------------------")
    print(f"[*] LM Studio:    {results['services']['lm_studio']['message']}")
    print(f"[*] ComfyUI:      {results['services']['comfyui']['message']}")
    print("=======================================================")
    
    if results["core_ready"]:
        print("[+] Core application is READY for execution.\n")
        sys.exit(0)
    else:
        print("[-] Setup incomplete. Please resolve missing dependencies.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
