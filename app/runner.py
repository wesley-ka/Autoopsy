import os
import subprocess
import yaml
import logging
import tempfile
import shutil
from app import config

logger = logging.getLogger("Runner")

class SandboxRunner:
    def __init__(self, repo: str = None, pat: str = None):
        self.pat = pat or config.GITHUB_PAT
        self.repo = repo

    def clone_repository(self) -> str:
        """
        Clones the target repository to a temporary folder and returns the directory path.
        """
        temp_dir = tempfile.mkdtemp(prefix="ops-agent-")
        clone_url = f"https://x-access-token:{self.pat}@github.com/{self.repo}.git"
        logger.info(f"Cloning repository {self.repo} to {temp_dir}")
        
        try:
            # Run git clone
            cmd = ["git", "clone", clone_url, "."]
            res = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise Exception(f"Git clone failed: {res.stderr or res.stdout}")
            
            # Configure local Git identity to prevent commit issues
            subprocess.run(["git", "config", "user.name", "Ops-Agent"], cwd=temp_dir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "ops-agent@internal.local"], cwd=temp_dir, capture_output=True)
            
            return temp_dir
        except Exception as e:
            logger.error(f"Error cloning repository: {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def get_agent_ops_config(self, repo_dir: str) -> dict:
        """
        Reads and parses .agent-ops.yml in the repository root.
        Falls back to auto-detecting stack build commands if the file is missing.
        """
        config_path = os.path.join(repo_dir, ".agent-ops.yml")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    logger.info("Successfully loaded .agent-ops.yml from repo root.")
                    return {
                        "build_command": data.get("build_command"),
                        "test_command": data.get("test_command"),
                        "core_files": data.get("core_files", [])
                    }
            except Exception as e:
                logger.error(f"Error reading .agent-ops.yml: {e}. Falling back to auto-detection.")


        # Heuristic Auto-Detection of standard project stacks
        logger.info("Missing or invalid .agent-ops.yml. Running stack auto-detection...")
        
        # Svelte / Node.js
        if os.path.exists(os.path.join(repo_dir, "package.json")):
            logger.info("Detected Svelte/Node.js project structure.")
            return {
                "build_command": "npm run build",
                "test_command": "npm test"
            }
        # Spring Boot / Maven
        elif os.path.exists(os.path.join(repo_dir, "pom.xml")):
            logger.info("Detected Spring Boot/Maven project structure.")
            return {
                "build_command": "mvn clean compile",
                "test_command": "mvn test"
            }
        # Gradle
        elif os.path.exists(os.path.join(repo_dir, "build.gradle")) or os.path.exists(os.path.join(repo_dir, "build.gradle.kts")):
            logger.info("Detected Gradle project structure.")
            wrapper = "./gradlew" if os.path.exists(os.path.join(repo_dir, "gradlew")) else "gradle"
            return {
                "build_command": f"{wrapper} build -x test",
                "test_command": f"{wrapper} test"
            }
        # Python
        elif os.path.exists(os.path.join(repo_dir, "requirements.txt")) or os.path.exists(os.path.join(repo_dir, "pyproject.toml")):
            logger.info("Detected Python project structure.")
            return {
                "build_command": "python -m py_compile **/*.py",
                "test_command": "pytest"
            }

        # Fallback default (empty commands)
        return {
            "build_command": "",
            "test_command": ""
        }

    def run_command(self, command: str, cwd: str, timeout: float = 300.0) -> dict:
        """
        Runs a shell command inside a subprocess, capturing output.
        """
        if not command:
            return {"returncode": 0, "stdout": "No command provided.", "stderr": ""}
            
        logger.info(f"Running command: '{command}' in {cwd}")
        try:
            # Run command via shell
            res = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "returncode": res.returncode,
                "stdout": res.stdout,
                "stderr": res.stderr
            }
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command '{command}' timed out after {timeout}s")
            return {
                "returncode": -9,
                "stdout": e.stdout or "",
                "stderr": f"Error: Command timed out after {timeout} seconds."
            }
        except Exception as e:
            logger.error(f"Exception running command '{command}': {e}")
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }

    def checkout_branch(self, branch_name: str, cwd: str) -> bool:
        """
        Checks out a new branch in the git repository.
        """
        logger.info(f"Checking out branch: {branch_name}")
        res = self.run_command(f"git checkout -b {branch_name}", cwd=cwd)
        if res["returncode"] != 0:
            # If branch already exists, just check it out
            res = self.run_command(f"git checkout {branch_name}", cwd=cwd)
        return res["returncode"] == 0

    def commit_and_push(self, branch_name: str, commit_msg: str, cwd: str) -> bool:
        """
        Stages all changes, commits them, and pushes to origin.
        """
        logger.info(f"Committing and pushing changes to {branch_name}")
        
        # Git Add
        res = self.run_command("git add -A", cwd=cwd)
        if res["returncode"] != 0:
            logger.error(f"Failed to run git add: {res['stderr']}")
            return False
            
        # Check if there are changes to commit
        status_res = self.run_command("git status --porcelain", cwd=cwd)
        if not status_res["stdout"].strip():
            logger.warning("No files were modified. Skipping commit.")
            return True

        # Git Commit
        res = self.run_command(f'git commit -m "{commit_msg}"', cwd=cwd)
        if res["returncode"] != 0:
            logger.error(f"Failed to run git commit: {res['stderr']}")
            return False
            
        # Git Push
        res = self.run_command(f"git push origin {branch_name}", cwd=cwd)
        if res["returncode"] != 0:
            logger.error(f"Failed to run git push: {res['stderr']}")
            return False
            
        return True

    def run_aider_fix(self, repo_dir: str, build_cmd: str, test_cmd: str, diagnosis_report: str, core_files: list = None) -> dict:
        """
        Runs Aider agent CLI inside the sandbox repository to fix code.
        """
        logger.info(f"Invoking Aider agentic fixer in: {repo_dir}")
        
        import sys
        # Resolve the aider executable path
        venv_bin_dir = os.path.dirname(sys.executable)
        aider_path = os.path.join(venv_bin_dir, "aider")
        
        if not os.path.exists(aider_path):
            # Fallback to system-wide aider if not in venv
            check_aider = subprocess.run(["which", "aider"], capture_output=True, text=True)
            if check_aider.returncode == 0:
                aider_path = "aider"
            else:
                raise Exception("Aider is not installed. Please run './venv/bin/pip install aider-chat' in your environment.")

        # Build prompt
        message = (
            f"Fix the bugs described in the SRE diagnosis report below.\n\n"
            f"=== SRE DIAGNOSIS ===\n{diagnosis_report}\n\n"
            f"=== VERIFICATION RULES ===\n"
            f"Use the build command: {build_cmd}\n"
            f"Use the test command: {test_cmd}\n"
            f"Apply code corrections to fix all errors."
        )

        # Prepare environment variables
        env = os.environ.copy()
        if config.LLM_PROVIDER == "gemini":
            env["GEMINI_API_KEY"] = config.LLM_API_KEY
            model_flag = f"gemini/{config.LLM_MODEL_CODER}"
        else:
            env["OPENAI_API_KEY"] = config.LLM_API_KEY
            if config.LLM_BASE_URL:
                env["OPENAI_API_BASE"] = config.LLM_BASE_URL
                env["OPENAI_BASE_URL"] = config.LLM_BASE_URL
            model_flag = f"openai/{config.LLM_MODEL_CODER}"

        # Construct Aider command arguments
        cmd = [
            aider_path,
            "--model", model_flag,
            "--message", message,
            "--yes"
        ]
        
        # If core files are provided, validate they exist and add them to the command arguments
        if core_files:
            existing_files = [f for f in core_files if os.path.exists(os.path.join(repo_dir, f))]
            if existing_files:
                logger.info(f"Pre-loading core context files for Aider: {existing_files}")
                # Pass files to Aider so they are added to chat context on startup
                cmd = [aider_path] + existing_files + cmd[1:]

        
        # If build/test commands are defined, feed them to Aider
        if test_cmd:
            cmd.extend(["--test-cmd", test_cmd, "--auto-test"])
            
        logger.info(f"Running Aider CLI: {' '.join(cmd)}")
        
        # Run Aider
        res = subprocess.run(cmd, cwd=repo_dir, env=env, capture_output=True, text=True, timeout=600.0)
        
        if res.returncode != 0:
            logger.error(f"Aider execution failed with exit code {res.returncode}:\n{res.stderr or res.stdout}")
            return {
                "success": False,
                "last_error": res.stderr or res.stdout or f"Aider returned non-zero code {res.returncode}"
            }
            
        logger.info("Aider agent successfully finished editing and testing.")
        return {
            "success": True,
            "last_error": ""
        }

    def cleanup(self, directory: str):
        """
        Cleans up the temporary folder safely.
        """
        logger.info(f"Cleaning up directory: {directory}")
        shutil.rmtree(directory, ignore_errors=True)

