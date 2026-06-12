import httpx
import logging
from app import config

logger = logging.getLogger("AutoopsyLogsClient")

class RenderClient:
    def __init__(self):
        self.api_key = config.RENDER_API_KEY
        self.service_id = config.RENDER_SERVICE_ID
        self.owner_id = config.RENDER_OWNER_ID
        self.base_url = "https://api.render.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Accept": "application/json"
        }

    def _get_owner_id(self, client: httpx.Client) -> str:
        """
        Fetches the ownerId automatically from the service details if not configured.
        """
        if not self.api_key or not self.service_id:
            return ""
        if self.owner_id:
            return self.owner_id
        
        try:
            url = f"{self.base_url}/services/{self.service_id}"
            resp = client.get(url, headers=self.headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                owner_id = data.get("ownerId") or data.get("service", {}).get("ownerId")
                if owner_id:
                    self.owner_id = owner_id
                    logger.info(f"Auto-discovered Render Owner ID: {self.owner_id}")
                    return self.owner_id
            logger.warning(f"Could not auto-discover Render Owner ID. Status code: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error auto-discovering Render Owner ID: {e}")
        return ""

    def get_service_status(self) -> dict:
        """
        Fetches status details of the Render service.
        """
        if not self.api_key or not self.service_id:
            return {"name": "Disabled", "type": "web_service", "status": "disabled", "updated_at": "", "dashboard_url": ""}
            
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/services/{self.service_id}"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    service_data = data.get("service") or data
                    return {
                        "name": service_data.get("name", "Unknown"),
                        "type": service_data.get("type", "unknown"),
                        "status": service_data.get("suspended", "active"), # suspended/not_suspended
                        "updated_at": service_data.get("updatedAt", ""),
                        "dashboard_url": service_data.get("dashboardUrl", ""),
                        "repo": service_data.get("repo", ""),
                        "branch": service_data.get("branch", ""),
                        "auto_deploy": service_data.get("autoDeploy", "")
                    }
        except Exception as e:
            logger.error(f"Error fetching Render service status: {e}")
        
        return {"name": "Unknown", "type": "web_service", "status": "unknown", "updated_at": "", "dashboard_url": ""}

    def get_logs(self, limit: int = 50) -> str:
        """
        Retrieves logs from Render using service logs endpoint, or general workspace logs endpoint.
        """
        if not self.api_key or not self.service_id:
            return "[SYSTEM] Render backend monitoring is disabled."

        with httpx.Client() as client:
            # Try 1: Specific service logs endpoint
            try:
                url = f"{self.base_url}/services/{self.service_id}/logs"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    return resp.text
            except Exception as e:
                logger.warning(f"Failed to fetch logs via service endpoint: {e}")

            # Try 2: General logs endpoint using owner ID
            owner_id = self._get_owner_id(client)
            if owner_id:
                try:
                    url = f"{self.base_url}/logs"
                    params = {
                        "ownerId": owner_id,
                        "resource": self.service_id,
                        "limit": limit
                    }
                    resp = client.get(url, headers=self.headers, params=params, timeout=10.0)
                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            logs_list = []
                            if isinstance(data, dict) and "logs" in data:
                                logs_list = data["logs"]
                            elif isinstance(data, list):
                                logs_list = data
                                
                            if logs_list:
                                return "\n".join([str(l.get("text") or l.get("message") or l) for l in logs_list])
                        except Exception as e:
                            logger.error(f"Error parsing Render logs: {e}")
                            return resp.text
                except Exception as e:
                    logger.error(f"Failed to fetch logs via workspace logs endpoint: {e}")
            
        # Fallback Mock Logs for testing / first run
        if config.ENABLE_MOCK_FALLBACK:
            logger.info("Falling back to simulated/mock Render service logs.")
            return (
                "[2026-06-11T09:00:01Z] INFO: Starting backend application server on port 8080...\n"
                "[2026-06-11T09:00:03Z] INFO: Database connected successfully.\n"
                "[2026-06-11T09:00:04Z] INFO: Redis connection pool initialized.\n"
                "[2026-06-11T09:02:15Z] ERROR: Database connection timeout during peak query.\n"
                "[2026-06-11T09:02:15Z] ERROR: Failed to process GET /api/v1/users request. Internal Server Error (500)\n"
                "[2026-06-11T09:02:18Z] WARNING: High Memory usage detected - Heap size: 852MB\n"
            )
        return "[ERROR] Failed to retrieve live logs from Render backend. Please verify your Render API key and Service ID configuration."




class CloudflarePagesClient:
    def __init__(self):
        self.api_token = config.CLOUDFLARE_API_TOKEN
        self.account_id = config.CLOUDFLARE_ACCOUNT_ID
        self.project_name = config.CLOUDFLARE_PROJECT_NAME
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {self.api_token or ''}",
            "Content-Type": "application/json"
        }

    def get_deployments(self) -> list:
        """
        Fetches the deployments list of a Cloudflare Pages project.
        """
        if not self.api_token or not self.account_id or not self.project_name:
            return []
            
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/accounts/{self.account_id}/pages/projects/{self.project_name}/deployments"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("result") or []
                logger.warning(f"Cloudflare deployments API returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Cloudflare Page deployments: {e}")
        
        if config.ENABLE_MOCK_FALLBACK:
            return [
                {
                    "id": "mock-cf-deploy-1",
                    "short_id": "87fa2d3c",
                    "project_name": self.project_name,
                    "environment": "production",
                    "latest_stage": {"name": "deploy", "status": "success"},
                    "modified_on": "2026-06-10T14:30:00Z",
                    "url": f"https://production.{self.project_name}.pages.dev"
                }
            ]
        return []

    def get_deployment_stages(self, deployment_id: str) -> list:
        """
        Fetches the detailed build stages and status history for a specific Cloudflare Pages deployment.
        """
        if not self.api_token or not self.account_id or not self.project_name or not deployment_id:
            return []
            
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/accounts/{self.account_id}/pages/projects/{self.project_name}/deployments/{deployment_id}/history"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("result") or {}
                    if isinstance(result, dict):
                        return result.get("stages") or []
                    return result if isinstance(result, list) else []
                logger.warning(f"Cloudflare deployment history API returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Cloudflare Page deployment history: {e}")
            
        if config.ENABLE_MOCK_FALLBACK:
            return [
                {"name": "initialize", "status": "success", "started_on": "2026-06-10T14:28:00Z", "ended_on": "2026-06-10T14:28:15Z"},
                {"name": "clone", "status": "success", "started_on": "2026-06-10T14:28:15Z", "ended_on": "2026-06-10T14:28:30Z"},
                {"name": "build", "status": "success", "started_on": "2026-06-10T14:28:30Z", "ended_on": "2026-06-10T14:29:45Z"},
                {"name": "deploy", "status": "success", "started_on": "2026-06-10T14:29:45Z", "ended_on": "2026-06-10T14:30:00Z"}
            ]
        return []

    def get_project_details(self) -> dict:
        """
        Fetches the details of a Cloudflare Pages project, including subdomain and custom domains.
        """
        if not self.api_token or not self.account_id or not self.project_name:
            return {}
            
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/accounts/{self.account_id}/pages/projects/{self.project_name}"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("result") or {}
                logger.warning(f"Cloudflare project details API returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"Error fetching Cloudflare Page project details: {e}")
            
        if config.ENABLE_MOCK_FALLBACK:
            return {
                "name": self.project_name,
                "subdomain": f"{self.project_name}.pages.dev",
                "domains": [f"www.{self.project_name}.com"]
            }
        return {}


class GithubClient:
    def __init__(self, repo: str, pat: str):
        """
        Initialize GithubClient dynamically for a targeted repository.
        """
        self.repo = repo
        self.pat = pat
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {self.pat}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_default_branch(self) -> str:
        """
        Fetches the default branch (e.g. main, master) of the repository.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    return resp.json().get("default_branch", "main")
        except Exception as e:
            logger.error(f"Error getting GitHub repo default branch: {e}")
        return "main"

    def create_pull_request(self, head_branch: str, base_branch: str, title: str, body: str) -> dict:
        """
        Creates a new Pull Request.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}/pulls"
                payload = {
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch
                }
                resp = client.post(url, headers=self.headers, json=payload, timeout=10.0)
                if resp.status_code == 201:
                    data = resp.json()
                    logger.info(f"Successfully created GitHub PR #{data.get('number')}")
                    return {
                        "success": True,
                        "pr_number": data.get("number"),
                        "html_url": data.get("html_url"),
                        "title": data.get("title")
                    }
                else:
                    logger.error(f"GitHub PR creation failed ({resp.status_code}): {resp.text}")
                    return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Exception creating GitHub PR: {e}")
            return {"success": False, "error": str(e)}

    def merge_pull_request(self, pr_number: int) -> dict:
        """
        Merges a Pull Request.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}/pulls/{pr_number}/merge"
                payload = {
                    "commit_title": f"chore(autoopsy): merged PR #{pr_number}",
                    "merge_method": "merge"
                }
                resp = client.put(url, headers=self.headers, json=payload, timeout=10.0)
                if resp.status_code == 200:
                    logger.info(f"Successfully merged GitHub PR #{pr_number}")
                    return {"success": True, "message": resp.json().get("message", "Merged")}
                else:
                    logger.error(f"GitHub PR merge failed ({resp.status_code}): {resp.text}")
                    return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Exception merging GitHub PR #{pr_number}: {e}")
            return {"success": False, "error": str(e)}

    def close_pull_request(self, pr_number: int) -> dict:
        """
        Closes a Pull Request without merging.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}/pulls/{pr_number}"
                payload = {"state": "closed"}
                resp = client.patch(url, headers=self.headers, json=payload, timeout=10.0)
                if resp.status_code == 200:
                    logger.info(f"Successfully closed GitHub PR #{pr_number}")
                    return {"success": True}
                else:
                    logger.error(f"GitHub PR close failed ({resp.status_code}): {resp.text}")
                    return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Exception closing GitHub PR #{pr_number}: {e}")
            return {"success": False, "error": str(e)}

    def delete_branch(self, branch_name: str) -> dict:
        """
        Deletes a branch ref from the GitHub repository.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}/git/refs/heads/{branch_name}"
                resp = client.delete(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 204:
                    logger.info(f"Successfully deleted branch {branch_name}")
                    return {"success": True}
                else:
                    logger.error(f"GitHub branch delete failed ({resp.status_code}): {resp.text}")
                    return {"success": False, "error": resp.text}
        except Exception as e:
            logger.error(f"Exception deleting GitHub branch {branch_name}: {e}")
            return {"success": False, "error": str(e)}

    def get_pr_details(self, pr_number: int) -> dict:
        """
        Retrieves details of a specific Pull Request.
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/repos/{self.repo}/pulls/{pr_number}"
                resp = client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "success": True,
                        "pr_number": data.get("number"),
                        "title": data.get("title"),
                        "state": data.get("state"),
                        "merged": data.get("merged", False),
                        "head_branch": data.get("head", {}).get("ref"),
                        "base_branch": data.get("base", {}).get("ref")
                    }
        except Exception as e:
            logger.error(f"Error fetching GitHub PR details: {e}")
        return {"success": False, "error": "Not Found"}
