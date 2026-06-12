import os
import json
import re
import logging
from app import config
from app.runner import SandboxRunner

logger = logging.getLogger("Agent")

class LLMAgent:
    def __init__(self):
        self.provider = config.LLM_PROVIDER
        self.api_key = config.LLM_API_KEY
        self.base_url = config.LLM_BASE_URL
        self.model_diagnostic = config.LLM_MODEL_DIAGNOSTIC
        self.model_coder = config.LLM_MODEL_CODER
        self.runner = SandboxRunner()

        # Initialize the appropriate API client
        if self.provider == "gemini":
            from google import genai
            logger.info("Initializing Google GenAI Client for Gemini...")
            # If api_key is provided, use it. Otherwise, genai.Client will pick it up from GEMINI_API_KEY env.
            self.gemini_client = genai.Client(api_key=self.api_key)
            self.openai_client = None
        else:
            from openai import OpenAI
            logger.info(f"Initializing OpenAI Client (Base URL: {self.base_url or 'Default OpenAI'})...")
            # Works for OpenAI, DeepInfra, Fireworks, Ollama, etc.
            self.openai_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.gemini_client = None

    def generate_text(self, system_prompt: str, user_prompt: str, is_coder: bool = False, require_json: bool = False) -> str:
        """
        Sends requests to the configured LLM API.
        """
        model = self.model_coder if is_coder else self.model_diagnostic
        logger.info(f"Sending request to LLM Provider: {self.provider} | Model: {model} | Coder Mode: {is_coder}")
        
        try:
            if self.provider == "gemini":
                from google.genai import types
                
                # Setup system instructions
                config_params = types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2 if is_coder else 0.5,
                )
                if require_json:
                    config_params.response_mime_type = "application/json"

                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config_params
                )
                return response.text or ""
            else:
                # OpenAI and compatible providers
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
                
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2 if is_coder else 0.5
                }
                if require_json:
                    kwargs["response_format"] = {"type": "json_object"}

                response = self.openai_client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Error calling LLM Provider ({self.provider}): {e}")
            raise e

    def diagnose_logs(self, service_status: dict, cloudflare_deployments: list, logs: str, cloudflare_stages: list = None) -> str:
        """
        Uses the diagnostic model to generate a summary report identifying the issue.
        """
        system_prompt = (
            "You are an expert SRE (Site Reliability Engineer). Your job is to analyze system status and logs, "
            "determine if the failure is on the Frontend (Cloudflare Pages), Backend (Render Web Service), Database, "
            "or due to deployment configuration errors. Provide a clear, structured SRE diagnosis report that is "
            "concise, highlight the exact failure logs, and explain what is wrong.\n\n"
            "CRITICAL: The report is sent to a Telegram chat, which only supports a strict subset of Markdown. You MUST adhere to these formatting rules:\n"
            "- Do NOT use headers (e.g. '#', '##', '###'). Use bold text (e.g., '*Header*') for headings.\n"
            "- Do NOT use markdown tables. Format data as clean bullet lists using emoji points.\n"
            "- Do NOT use blockquotes ('>').\n"
            "- Highlight logs and error traces using code blocks (triple backticks).\n\n"
            "At the very end of your response, on a new line, you MUST append the following tag exactly:\n"
            "FAILED_COMPONENT: <component>\n"
            "Where <component> is either 'backend', 'frontend', or 'none' (use 'backend' for database or backend code errors, "
            "'frontend' for frontend/pages UI issues, and 'none' if everything is healthy or unclear)."
        )

        user_prompt = f"""
=== SYSTEM STATUS ===
Render Service: {json.dumps(service_status, indent=2)}
Cloudflare Deployments: {json.dumps(cloudflare_deployments[:3], indent=2)}
Cloudflare Latest Deployment Stages: {json.dumps(cloudflare_stages, indent=2) if cloudflare_stages else "None"}

=== LATEST RENDER SERVICE LOGS ===
{logs}

Please diagnose the issue and answer:
1. What is wrong with the website? (Pinpoint exact failure and component - frontend, backend, database, configuration, etc.)
2. What are the key error lines?
3. Recommended fix action.
"""
        return self.generate_text(system_prompt, user_prompt, is_coder=False)

    def respond_to_query(self, user_message: str, service_status: dict, cloudflare_deployments: list, logs: str, cloudflare_stages: list = None, history: list = None) -> dict:
        """
        Analyzes the user message against the live system context (status, logs, build stages) and chat history.
        Returns a JSON structure dictating if an action should be taken or providing a rich conversational answer.
        """
        system_prompt = (
            "You are Autoopsy, an advanced SRE AI agent. You have access to the live status of the system (Render backend and Cloudflare frontend) and recent logs.\n"
            "Analyze the user's message and determine their intent. Pay close attention to the provided chat history to resolve context-dependent confirmations (e.g. if the user says 'yes do that', check what was previously proposed).\n\n"
            "Classify the intent into one of the following actions:\n"
            "1. 'debug': The user wants a detailed diagnostic report of system errors (similar to running /debug).\n"
            "2. 'fix': The user wants to run the code repair sandbox (similar to running /fix). You can also specify which 'component' (backend or frontend) to target if they mentioned or confirmed it.\n"
            "3. 'chat': The user is asking a general question, checking status conversationally, or discussing operations.\n\n"
            "If the action is 'chat', formulate a friendly, concise, and highly professional SRE report answering their query using the provided live system context.\n"
            "CRITICAL: The report is sent to a Telegram chat, which only supports a strict subset of Markdown. You MUST adhere to these formatting rules:\n"
            "- Do NOT use headers (e.g. '#', '##', '###'). Use bold text (e.g., '*Header*') for headings.\n"
            "- Do NOT use markdown tables. Format data as clean bullet lists using emoji points.\n"
            "- Do NOT use blockquotes ('>').\n"
            "- Highlight logs and error traces using code blocks (triple backticks).\n\n"
            "You MUST return a JSON structure ONLY:\n"
            "{\n"
            "  \"action\": \"debug\" | \"fix\" | \"chat\",\n"
            "  \"component\": \"backend\" | \"frontend\" | \"none\",\n"
            "  \"response\": \"Your rich Markdown answer here (only if action is chat, otherwise empty string)\"\n"
            "}"
        )

        formatted_history = ""
        if history:
            for msg in history:
                role = "User" if msg["role"] == "user" else "Autoopsy"
                formatted_history += f"{role}: {msg['text']}\n"

        user_prompt = f"""
=== RECENT CONVERSATION HISTORY ===
{formatted_history or "None (this is the start of the conversation)"}

=== USER QUERY ===
{user_message}

=== LIVE SYSTEM CONTEXT ===
Render Backend Status: {json.dumps(service_status, indent=2)}
Cloudflare Frontend Deployments: {json.dumps(cloudflare_deployments[:3], indent=2)}
Cloudflare Latest Deployment Stages History: {json.dumps(cloudflare_stages, indent=2) if cloudflare_stages else "None"}
Render Logs (Last 50 lines):
{logs}
"""
        try:
            raw_res = self.generate_text(system_prompt, user_prompt, is_coder=False, require_json=True)
            cleaned = self._clean_json_string(raw_res)
            return json.loads(cleaned)
        except Exception as e:
            logger.error(f"Failed to respond to query: {e}")
            return {
                "action": "chat",
                "component": "none",
                "response": "I encountered an error trying to process your request against the system logs. Please try again or use standard commands like `/status`, `/debug`, or `/fix`."
            }

    def _get_source_files(self, repo_dir: str) -> dict:
        """
        Walks the repository directory, reading files and creating a structured map of paths and contents.
        Excludes bulky build directories, package locks, git folders, and images.
        """
        source_files = {}
        exclude_dirs = {".git", "node_modules", "target", ".gradle", "venv", "dist", "build", "out", ".idea", ".vscode"}
        exclude_files = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "mvnw", "gradlew", "gradle-wrapper.jar"}
        allowed_extensions = {
            ".js", ".ts", ".svelte", ".vue", ".jsx", ".tsx",
            ".py", ".java", ".go", ".rs", ".rb", ".php",
            ".json", ".yaml", ".yml", ".properties", ".xml", ".ini", ".conf",
            ".css", ".html", ".sh", ".md", "Dockerfile"
        }

        for root, dirs, files in os.walk(repo_dir):
            # Prune directory search
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file in exclude_files:
                    continue
                
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, repo_dir)
                
                # Check extension or special files like Dockerfile
                _, ext = os.path.splitext(file)
                if ext in allowed_extensions or file == "Dockerfile":
                    try:
                        # Skip files that are too large (e.g. > 60KB) to prevent token overflow
                        if os.path.getsize(filepath) < 60000:
                            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                                source_files[rel_path] = f.read()
                    except Exception as e:
                        logger.warning(f"Error reading file {rel_path} in sandbox: {e}")
        
        return source_files

    def _clean_json_string(self, text: str) -> str:
        """
        Strips markdown syntax wrappers (like ```json ... ```) to clean JSON strings.
        """
        # Remove markdown code blocks if present
        text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
        text = re.sub(r"```$", "", text.strip(), flags=re.IGNORECASE)
        return text.strip()

    def run_fixing_loop(self, repo_dir: str, build_cmd: str, test_cmd: str, diagnosis_report: str) -> dict:
        """
        Executes the self-correcting code edit loop up to 3 iterations.
        """
        logger.info(f"Starting self-correcting fix loop in: {repo_dir}")
        history = []
        last_error = ""

        system_prompt = (
            "You are an SRE AI Bot. Your task is to write code modifications to fix application errors.\n"
            "You will be given the list of files in the repository and their contents, the diagnosis report, the "
            "build and test commands, and the build outputs of previous attempts.\n"
            "Apply modifications to existing files or create new files to resolve the build/test failures.\n"
            "You MUST return a JSON structure only, formatted as:\n"
            "{\n"
            "  \"explanation\": \"A description of the fixes you are proposing.\",\n"
            "  \"edits\": [\n"
            "    {\n"
            "      \"file_path\": \"relative/path/to/file.js\",\n"
            "      \"operation\": \"modify\" | \"create\" | \"delete\",\n"
            "      \"content\": \"the complete new content for the file (empty if delete)\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "Follow these rules:\n"
            "- Only edit relevant files that need to be changed.\n"
            "- Provide the COMPLETE file contents in 'content' for 'create' and 'modify' operations.\n"
            "- Double check file paths match the repository structure exactly."
        )

        for iteration in range(1, 4):
            logger.info(f"Fixing loop iteration {iteration}/3...")
            
            # Fetch current state of source files
            source_files = self._get_source_files(repo_dir)
            files_context = json.dumps(source_files, indent=2)

            user_prompt = f"""
=== REPOSITY SOURCE FILES ===
{files_context}

=== DIAGNOSIS REPORT ===
{diagnosis_report}

=== SANDBOX RUN CONFIGURATION ===
Build Command: {build_cmd}
Test Command: {test_cmd}
"""
            if last_error:
                user_prompt += f"\n=== PREVIOUS ITERATION ERROR ===\n{last_error}\n"

            try:
                # Call LLM Coder
                raw_edits = self.generate_text(system_prompt, user_prompt, is_coder=True, require_json=True)
                cleaned_edits = self._clean_json_string(raw_edits)
                edit_data = json.loads(cleaned_edits)
            except Exception as e:
                logger.error(f"Failed to generate edits or parse JSON on iteration {iteration}: {e}")
                last_error = f"Error generating edits: {e}"
                continue

            explanation = edit_data.get("explanation", "Applying edits.")
            edits = edit_data.get("edits", [])
            
            if not edits:
                logger.warning("LLM proposed zero file edits. Ending loop.")
                break

            # Apply edits to the repository
            applied_edits_summary = []
            for edit in edits:
                file_path = edit.get("file_path")
                operation = edit.get("operation", "modify")
                content = edit.get("content", "")
                
                full_path = os.path.join(repo_dir, file_path)
                
                # Make parent directories if they don't exist
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                if operation == "delete":
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        applied_edits_summary.append(f"Deleted {file_path}")
                else: # modify or create
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    applied_edits_summary.append(f"Modified/Created {file_path}")

            history.append({
                "iteration": iteration,
                "explanation": explanation,
                "applied_changes": applied_edits_summary
            })

            # Verify by running build & test commands
            logger.info(f"Verifying changes for iteration {iteration}...")
            build_res = self.runner.run_command(build_cmd, cwd=repo_dir)
            
            if build_res["returncode"] != 0:
                last_error = f"Build failed with exit code {build_res['returncode']}.\nSTDOUT:\n{build_res['stdout']}\nSTDERR:\n{build_res['stderr']}"
                logger.warning(f"Iteration {iteration} Build failed: {build_res['stderr']}")
                continue
                
            test_res = self.runner.run_command(test_cmd, cwd=repo_dir)
            if test_res["returncode"] != 0:
                last_error = f"Test failed with exit code {test_res['returncode']}.\nSTDOUT:\n{test_res['stdout']}\nSTDERR:\n{test_res['stderr']}"
                logger.warning(f"Iteration {iteration} Tests failed: {test_res['stderr']}")
                continue

            # Both build and test succeeded!
            logger.info("Verification succeeded! Local build and test passed.")
            return {
                "success": True,
                "history": history,
                "last_error": ""
            }

        # Failed after 3 iterations
        return {
            "success": False,
            "history": history,
            "last_error": last_error
        }
