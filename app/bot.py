import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import logging
import re
from app import config
from app.logs_client import RenderClient, CloudflarePagesClient, GithubClient
from app.runner import SandboxRunner
from app.agent import LLMAgent

logger = logging.getLogger("Bot")

# Initialize the bot. threaded=True spawns a thread for each handler to prevent blocking
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=True)

# Initialize API clients and agent
render_client = RenderClient()
cf_client = CloudflarePagesClient()
agent = LLMAgent()
chat_histories = {}

# Authorization check decorator
def check_auth(func):
    def wrapper(update, *args, **kwargs):
        from_user = getattr(update, 'from_user', None)
        if not from_user:
            return func(update, *args, **kwargs)
            
        user_id = from_user.id
        
        # If whitelist is configured, check membership
        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized access attempt by user_id {user_id}")
            if isinstance(update, telebot.types.CallbackQuery):
                bot.answer_callback_query(update.id, "❌ Access Denied: Unauthorized account.", show_alert=True)
            else:
                bot.send_message(update.chat.id, "❌ Access Denied: Unauthorized account.")
            return
        return func(update, *args, **kwargs)
    return wrapper

@bot.message_handler(commands=['start'])
@check_auth
def handle_start(message):
    chat_id = message.chat.id
    config.save_target_chat_id(chat_id)
    
    welcome_text = (
        "🤖 *Welcome to Autoopsy!* Your Autonomous DevSecOps SRE.\n\n"
        "I monitor your Render backend, Cloudflare frontend, and execute self-correcting sandboxes to fix issues.\n\n"
        "*Available Commands:*\n"
        "🔌 `/status` - Check Render and Cloudflare deployments health\n"
        "🔍 `/debug` - Fetch logs and diagnose failure using LLM\n"
        "🛠️ `/fix` - Run self-correcting sandbox and create PR\n\n"
        "You can also ask me questions in plain English, like:\n"
        "💬 _'what is wrong with the website?'_ or _'fix it'_"
    )
    bot.send_message(chat_id, welcome_text, parse_mode="Markdown")


def get_status_card(title: str = "Autoopsy Status Overview") -> str:
    render_status = render_client.get_service_status()
    cf_deployments = cf_client.get_deployments()
    
    # 1. Evaluate Backend Health
    r_state = render_status.get("status", "unknown").lower()
    if r_state in ["suspended", "failed"]:
        backend_health = f"🔴 *Issues Detected* ({r_state})"
        backend_ok = False
    elif r_state == "disabled":
        backend_health = "⚪ *Disabled*"
        backend_ok = True
    else:
        backend_health = "🟢 *Healthy*"
        backend_ok = True
        
    # Format updated_at timestamp (e.g. "2026-06-11T15:26:44.977Z" -> "2026-06-11 15:26")
    r_updated = render_status.get("updated_at", "")
    if len(r_updated) >= 16:
        r_updated_clean = r_updated[:16].replace("T", " ")
    else:
        r_updated_clean = r_updated or "N/A"
        
    # 2. Evaluate Frontend Health
    frontend_health = "🟢 *Healthy*"
    frontend_ok = True
    cf_details = ""
    
    if cf_deployments:
        latest_cf = cf_deployments[0]
        cf_state = latest_cf.get("latest_stage", {}).get("status", "unknown").lower()
        if cf_state in ["failed"]:
            frontend_health = "🔴 *Deploy Failed*"
            frontend_ok = False
        elif cf_state in ["queued", "active", "building"]:
            frontend_health = "🟡 *Deploying...*"
            frontend_ok = True
            
        env = latest_cf.get("environment", "production")
        metadata = latest_cf.get("deployment_trigger", {}).get("metadata", {}) or {}
        commit_hash = latest_cf.get("short_id") or (metadata.get("commit_hash", "")[:8] if metadata else "")
        branch = metadata.get("branch", "") if metadata else ""
        
        cf_details = f"• *Project*: `{latest_cf.get('project_name')}` ({env})\n"
        if commit_hash and branch:
            cf_details += f"• *Last Deploy*: `{commit_hash}` (`{branch}`)\n"
        elif commit_hash:
            cf_details += f"• *Last Deploy*: `{commit_hash}`\n"
    else:
        cf_details = "• *Status*: `No deployments found`\n"

    # 3. Overall Status Summary
    if backend_ok and frontend_ok:
        if frontend_health == "🟡 *Deploying...*":
            overall_status = "🟡 *Status*: Frontend deployment in progress."
        else:
            overall_status = "🟢 *Status*: All systems nominal. All good!"
    elif not backend_ok and not frontend_ok:
        overall_status = "🔴 *Status*: Action required. Both systems have issues!"
    elif not backend_ok:
        overall_status = "🔴 *Status*: Action required. Backend has issues."
    else:
        overall_status = "🔴 *Status*: Action required. Frontend deployment failed."

    # 4. Construct Card
    status_card = f"📊 *{title}*\n"
    status_card += "========================================\n\n"
    
    status_card += f"🖥️ *Backend*: {backend_health}\n"
    status_card += f"• *Service*: `{render_status.get('name')}`\n"
    status_card += f"• *Last Deploy*: `{r_updated_clean}`\n\n"
    
    status_card += f"⚡ *Frontend*: {frontend_health}\n"
    status_card += cf_details
    
    status_card += "\n========================================\n"
    status_card += overall_status
    return status_card

@bot.message_handler(commands=['status'])
@check_auth
def handle_status(message):
    chat_id = message.chat.id
    config.save_target_chat_id(chat_id)
    
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        card = get_status_card(title="Autoopsy Status Overview")
        bot.send_message(chat_id, card, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error retrieving status details: {e}")
        bot.send_message(chat_id, f"❌ Error retrieving status details: `{e}`", parse_mode="Markdown")


@bot.message_handler(commands=['debug'])
@check_auth
def handle_debug(message):
    chat_id = message.chat.id
    config.save_target_chat_id(chat_id)
    
    status_msg = bot.send_message(chat_id, "🔍 Fetching logs and analyzing system status...", parse_mode="Markdown")
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        render_status = render_client.get_service_status()
        cf_deployments = cf_client.get_deployments()
        logs = render_client.get_logs()
        cf_stages = []
        if cf_deployments:
            latest_id = cf_deployments[0].get("id")
            if latest_id:
                cf_stages = cf_client.get_deployment_stages(latest_id)
        
        diagnosis = agent.diagnose_logs(render_status, cf_deployments, logs, cloudflare_stages=cf_stages)
        
        report_msg = (
            "🛠️ *Autoopsy Diagnostic Report*\n\n"
            f"{diagnosis}"
        )
        try:
            bot.send_message(chat_id, report_msg, parse_mode="Markdown")
        except Exception as me:
            logger.warning(f"Markdown parse error, falling back to plain text: {me}")
            bot.send_message(chat_id, report_msg)
            
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error handling /debug command: {e}")
        try:
            bot.edit_message_text(f"❌ Diagnostic failed: `{e}`", chat_id, status_msg.message_id)
        except Exception:
            pass


def execute_fix(chat_id, component, diagnosis_report=None):
    # Validate configurations
    if component == "backend":
        repo = config.BACKEND_GITHUB_REPO
        branch = config.BACKEND_GITHUB_BRANCH
        if not repo or repo == "owner/backend-repo":
            bot.send_message(chat_id, "❌ Backend repository is not configured. Please set `BACKEND_GITHUB_REPO`.", parse_mode="Markdown")
            return
    elif component == "frontend":
        repo = config.FRONTEND_GITHUB_REPO
        branch = config.FRONTEND_GITHUB_BRANCH
        if not repo or repo == "owner/frontend-repo":
            bot.send_message(chat_id, "❌ Frontend repository is not configured. Please set `FRONTEND_GITHUB_REPO`.", parse_mode="Markdown")
            return
    else:
        bot.send_message(chat_id, "❌ Invalid component targeted for fix.", parse_mode="Markdown")
        return

    status_msg = bot.send_message(chat_id, f"🔍 Fetching latest logs and diagnosing failure for `{component}`...", parse_mode="Markdown")
    bot.send_chat_action(chat_id, 'typing')
    
    repo_dir_cleaned = None
    try:
        if not diagnosis_report:
            render_status = render_client.get_service_status()
            cf_deployments = cf_client.get_deployments()
            logs = render_client.get_logs()
            cf_stages = []
            if cf_deployments:
                latest_id = cf_deployments[0].get("id")
                if latest_id:
                    cf_stages = cf_client.get_deployment_stages(latest_id)
            diagnosis_report = agent.diagnose_logs(render_status, cf_deployments, logs, cloudflare_stages=cf_stages)
        
        bot.edit_message_text(
            f"⚙️ Cloning `{repo}` (branch: `{branch}`) into sandbox...",
            chat_id, status_msg.message_id, parse_mode="Markdown"
        )
        
        runner = SandboxRunner(repo=repo, pat=config.GITHUB_PAT)
        github_client = GithubClient(repo=repo, pat=config.GITHUB_PAT)
        
        # 1. Clone repository
        repo_dir = runner.clone_repository()
        repo_dir_cleaned = repo_dir
        
        # 2. Get build and test configs
        ops_config = runner.get_agent_ops_config(repo_dir)
        build_cmd = ops_config.get("build_command")
        test_cmd = ops_config.get("test_command")
        core_files = ops_config.get("core_files", [])
        
        if not build_cmd:
            bot.edit_message_text(
                "❌ Sandbox run skipped: could not detect build tools. Please create a `.agent-ops.yml` config.",
                chat_id, status_msg.message_id
            )
            runner.cleanup(repo_dir)
            return

        # 3. Setup git branch
        branch_name = f"fix/ops-agent-{int(time.time())}"
        base_branch = github_client.get_default_branch()
        
        # 4. Run fixing loop based on coding engine
        if config.CODING_ENGINE == "aider":
            if not runner.checkout_branch(branch_name, cwd=repo_dir):
                raise Exception("Failed to checkout branch in git.")
            
            bot.edit_message_text(
                f"🛠️ Sandbox setup complete for `{component}`.\n*Build*: `{build_cmd}`\n*Test*: `{test_cmd}`\n\nStarting Aider Agent Engine...",
                chat_id, status_msg.message_id, parse_mode="Markdown"
            )
            
            loop_res = runner.run_aider_fix(repo_dir, build_cmd, test_cmd, diagnosis_report, core_files=core_files)
            
            if not loop_res["success"]:
                bot.edit_message_text(
                    "❌ *Aider Auto-Fixing Failed*\n\nLocal builds/tests did not pass. Here is the last error:\n"
                    f"```\n{loop_res.get('last_error')[:3000]}\n```",
                    chat_id, status_msg.message_id, parse_mode="Markdown"
                )
                runner.cleanup(repo_dir)
                return
                
            bot.edit_message_text(
                "✅ Aider checks passed! Pushing changes to GitHub...",
                chat_id, status_msg.message_id, parse_mode="Markdown"
            )
            
            # Push changes
            push_res = runner.run_command(f"git push origin {branch_name}", cwd=repo_dir)
            if push_res["returncode"] != 0:
                raise Exception(f"Failed to push Aider commits to GitHub: {push_res['stderr']}")
                
            log_res = runner.run_command(f"git log origin/{base_branch}..HEAD --oneline", cwd=repo_dir)
            changes_md = "📂 *Git Commits Made by Aider*:\n" + "\n".join([f"  • {c}" for c in log_res["stdout"].splitlines()])
        else:
            bot.edit_message_text(
                f"🛠️ Sandbox setup complete for `{component}`.\n*Build*: `{build_cmd}`\n*Test*: `{test_cmd}`\n\nStarting native LLM auto-fixing loop...",
                chat_id, status_msg.message_id, parse_mode="Markdown"
            )
            
            # Update agent runner reference temporarily
            agent.runner = runner
            loop_res = agent.run_fixing_loop(repo_dir, build_cmd, test_cmd, diagnosis_report)
            
            if not loop_res["success"]:
                bot.edit_message_text(
                    "❌ *LLM Auto-Fixing Failed*\n\nLocal builds did not pass in 3 iterations. Here is the last compilation error:\n"
                    f"```\n{loop_res.get('last_error')[:3000]}\n```",
                    chat_id, status_msg.message_id, parse_mode="Markdown"
                )
                runner.cleanup(repo_dir)
                return
                
            bot.edit_message_text(
                "✅ Sandbox build passed! Pushing changes to GitHub...",
                chat_id, status_msg.message_id, parse_mode="Markdown"
            )
            
            if not runner.checkout_branch(branch_name, cwd=repo_dir):
                raise Exception("Failed to checkout branch in git.")
                
            commit_msg = "chore(ops-agent): applied auto-corrective SRE patch"
            if not runner.commit_and_push(branch_name, commit_msg, cwd=repo_dir):
                raise Exception("Failed to commit and push changes.")
                
            changes_md = ""
            for h in loop_res.get("history", []):
                changes_md += f"⚙️ *Iteration {h['iteration']}*:\n"
                changes_md += f"  _Fix_: {h['explanation']}\n"
                for change in h.get("applied_changes", []):
                    changes_md += f"  • {change}\n"

        # 5. Create Pull Request
        pr_title = f"[Autoopsy] Auto-Correction patch for {component}"
        pr_body = (
            f"This Pull Request was generated by **Autoopsy** to resolve system anomalies on the {component}.\n\n"
            "### Modification Details:\n"
            f"• **Diagnostics Trigger**: Detected runtime issues in Render logs.\n"
            f"• **Target Component**: `{component}`\n"
            f"• **Coding Engine**: `{config.CODING_ENGINE}`\n"
        )
        if config.CODING_ENGINE == "aider":
            pr_body += f"\n{changes_md}\n"
        else:
            pr_body += "\n"
            for h in loop_res.get("history", []):
                pr_body += f"  - _Iteration {h['iteration']}_: {h['explanation']}\n"
                for change in h.get("applied_changes", []):
                    pr_body += f"    * {change}\n"
                    
        pr_res = github_client.create_pull_request(branch_name, base_branch, pr_title, pr_body)
        
        if not pr_res.get("success"):
            raise Exception(f"PR creation failed: {pr_res.get('error')}")

        bot.delete_message(chat_id, status_msg.message_id)
        
        # 6. Ask for approval with Inline Keyboard Button containing component type
        pr_url = pr_res.get("html_url")
        pr_number = pr_res.get("pr_number")
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("Approve & Merge", callback_data=f"merge_pr:{pr_number}:{component}"),
            InlineKeyboardButton("Reject & Close", callback_data=f"reject_pr:{pr_number}:{component}")
        )
        
        success_message = (
            f"🚀 *Auto-Fix Succeeded & Pull Request Created for {component.upper()}!*\n\n"
            f"• *Pull Request*: [PR #{pr_number}]({pr_url})\n"
            f"• *Target Repo*: `{repo}`\n"
            f"• *Base Branch*: `{base_branch}`\n"
            f"• *Head Branch*: `{branch_name}`\n\n"
            "📝 *SRE DIAGNOSIS*:\n"
            f"_{diagnosis_report[:250]}..._\n\n"
            "🛠️ *SANDBOX TESTING*:\n"
            f"• Build command: `{build_cmd}`\n"
            f"• Test command: `{test_cmd}`\n"
            "• Status: ✅ All checks compiled and passed successfully.\n\n"
            "📂 *CHANGES APPLIED*:\n"
            f"{changes_md}\n"
            "Please authorize the changes below. Approving will merge the PR and trigger the production deployment."
        )
        
        try:
            bot.send_message(chat_id, success_message, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            bot.send_message(chat_id, success_message, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Error handling fix for {component}: {e}")
        try:
            bot.send_message(chat_id, f"❌ Fixing loop failed for `{component}`: `{e}`", parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, f"❌ Fixing loop failed for `{component}`: `{e}`")
    finally:
        if repo_dir_cleaned:
            runner.cleanup(repo_dir_cleaned)


@bot.message_handler(commands=['fix'])
@check_auth
def handle_fix(message):
    chat_id = message.chat.id
    config.save_target_chat_id(chat_id)
    
    args = message.text.strip().split()
    component = None
    for word in args:
        w = word.lower()
        if w in ["frontend", "backend"]:
            component = w
            break
            
    if component:
        execute_fix(chat_id, component)
    else:
        # Auto-detect failing component using diagnostic logs
        status_msg = bot.send_message(chat_id, "🔍 Fetching logs and diagnosing component failure...", parse_mode="Markdown")
        bot.send_chat_action(chat_id, 'typing')
        try:
            render_status = render_client.get_service_status()
            cf_deployments = cf_client.get_deployments()
            logs = render_client.get_logs()
            cf_stages = []
            if cf_deployments:
                latest_id = cf_deployments[0].get("id")
                if latest_id:
                    cf_stages = cf_client.get_deployment_stages(latest_id)
            diagnosis_report = agent.diagnose_logs(render_status, cf_deployments, logs, cloudflare_stages=cf_stages)
            
            # Parse FAILED_COMPONENT
            match = re.search(r"FAILED_COMPONENT:\s*(backend|frontend|none)", diagnosis_report, re.IGNORECASE)
            detected_component = match.group(1).lower() if match else "none"
            
            bot.delete_message(chat_id, status_msg.message_id)
            
            if detected_component in ["backend", "frontend"]:
                execute_fix(chat_id, detected_component, diagnosis_report)
            else:
                # Undetermined failure, prompt user with selection buttons
                keyboard = InlineKeyboardMarkup()
                keyboard.row(
                    InlineKeyboardButton("Fix Backend 🖥️", callback_data="run_fix:backend"),
                    InlineKeyboardButton("Fix Frontend ⚡", callback_data="run_fix:frontend")
                )
                
                bot.send_message(
                    chat_id,
                    "❓ *Failing component undetermined.*\n\n"
                    f"SRE Diagnosis:\n{diagnosis_report}\n\n"
                    "Please select which repository to run the auto-fix sandbox on:",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"Error auto-detecting failing component: {e}")
            bot.send_message(chat_id, f"❌ Failed to diagnose system: `{e}`", parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("run_fix:"))
@check_auth
def handle_run_fix_callback(call):
    chat_id = call.message.chat.id
    component = call.data.split(":")[1]
    bot.answer_callback_query(call.id, f"Starting fix for {component}...")
    bot.delete_message(chat_id, call.message.message_id)
    execute_fix(chat_id, component)


@bot.callback_query_handler(func=lambda call: call.data.startswith("merge_pr:"))
@check_auth
def handle_merge_pr_callback(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    pr_number = int(parts[1])
    component = parts[2]
    
    bot.answer_callback_query(call.id, "Authorizing PR merge...")
    bot.edit_message_text(
        f"{call.message.text}\n\n⏳ *Status*: Merging PR #{pr_number} on GitHub ({component})...",
        chat_id, call.message.message_id, parse_mode="Markdown"
    )
    
    repo = config.BACKEND_GITHUB_REPO if component == "backend" else config.FRONTEND_GITHUB_REPO
    github_client = GithubClient(repo=repo, pat=config.GITHUB_PAT)
    
    try:
        # Get details first to know the head branch name for cleanup
        pr_details = github_client.get_pr_details(pr_number)
        head_branch = pr_details.get("head_branch")
        
        merge_res = github_client.merge_pull_request(pr_number)
        if merge_res.get("success"):
            status_text = (
                f"🚀 *PR #{pr_number} Approved and Merged ({component})!*\n\n"
                "✅ *Status*: Merged. Deploying to production.\n"
            )
            # Cleanup remote branch
            if head_branch:
                del_res = github_client.delete_branch(head_branch)
                if del_res.get("success"):
                    status_text += f"🧹 Remote branch `{head_branch}` deleted successfully.\n"
            
            bot.edit_message_text(
                status_text,
                chat_id, call.message.message_id, parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                f"{call.message.text}\n\n❌ *Status*: Merge failed: `{merge_res.get('error')}`",
                chat_id, call.message.message_id, parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error merging PR #{pr_number}: {e}")
        bot.edit_message_text(
            f"{call.message.text}\n\n❌ *Status*: Exception during merge: `{e}`",
            chat_id, call.message.message_id, parse_mode="Markdown"
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_pr:"))
@check_auth
def handle_reject_pr_callback(call):
    chat_id = call.message.chat.id
    parts = call.data.split(":")
    pr_number = int(parts[1])
    component = parts[2]
    
    bot.answer_callback_query(call.id, "Rejecting PR...")
    bot.edit_message_text(
        f"{call.message.text}\n\n⏳ *Status*: Closing PR #{pr_number} on GitHub ({component})...",
        chat_id, call.message.message_id, parse_mode="Markdown"
    )
    
    repo = config.BACKEND_GITHUB_REPO if component == "backend" else config.FRONTEND_GITHUB_REPO
    github_client = GithubClient(repo=repo, pat=config.GITHUB_PAT)
    
    try:
        # Get details first to know the head branch name for cleanup
        pr_details = github_client.get_pr_details(pr_number)
        head_branch = pr_details.get("head_branch")
        
        close_res = github_client.close_pull_request(pr_number)
        if close_res.get("success"):
            status_text = (
                f"❌ *PR #{pr_number} Rejected and Closed ({component}).*\n\n"
                "🚫 *Status*: Closed. No deployment triggered.\n"
            )
            # Cleanup remote branch
            if head_branch:
                del_res = github_client.delete_branch(head_branch)
                if del_res.get("success"):
                    status_text += f"🧹 Remote branch `{head_branch}` deleted successfully.\n"
            
            bot.edit_message_text(
                status_text,
                chat_id, call.message.message_id, parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                f"{call.message.text}\n\n❌ *Status*: Close failed: `{close_res.get('error')}`",
                chat_id, call.message.message_id, parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error rejecting PR #{pr_number}: {e}")
        bot.edit_message_text(
            f"{call.message.text}\n\n❌ *Status*: Exception during close: `{e}`",
            chat_id, call.message.message_id, parse_mode="Markdown"
        )


@bot.message_handler(func=lambda message: True)
@check_auth
def handle_general_messages(message):
    chat_id = message.chat.id
    config.save_target_chat_id(chat_id)
    
    user_text = message.text
    logger.info(f"Received message: '{user_text}' from chat {chat_id}")
    
    # Store user message in history
    chat_histories.setdefault(chat_id, []).append({"role": "user", "text": user_text})
    chat_histories[chat_id] = chat_histories[chat_id][-6:]
    
    bot.send_chat_action(chat_id, 'typing')
    
    try:
        # Fetch live system context for the LLM
        render_status = render_client.get_service_status()
        cf_deployments = cf_client.get_deployments()
        logs = render_client.get_logs()
        cf_stages = []
        if cf_deployments:
            latest_id = cf_deployments[0].get("id")
            if latest_id:
                cf_stages = cf_client.get_deployment_stages(latest_id)
        
        # Get history context (excluding the user query that was just appended)
        history_context = chat_histories[chat_id][:-1]
        
        # Call LLM with history context
        result = agent.respond_to_query(user_text, render_status, cf_deployments, logs, metrics=None, cloudflare_stages=cf_stages, history=history_context)
        action = result.get("action", "chat")
        component = result.get("component", "none")
        
        if action == "debug":
            handle_debug(message)
        elif action == "fix":
            # Extract the original request instruction from the conversation thread
            original_instruction = user_text
            if len(chat_histories[chat_id]) >= 3 and chat_histories[chat_id][-2]["role"] == "assistant":
                original_instruction = chat_histories[chat_id][-3]["text"]
                
            if component in ["backend", "frontend"]:
                execute_fix(chat_id, component, diagnosis_report=f"User Request: {original_instruction}")
            else:
                handle_fix(message)
        else:
            reply = result.get("response", "I could not formulate an answer. How can I help you?")
            try:
                bot.send_message(chat_id, reply, parse_mode="Markdown")
            except Exception as me:
                logger.warning(f"Failed to send Markdown general reply, falling back to plain text: {me}")
                bot.send_message(chat_id, reply)
            # Store assistant response in history
            chat_histories[chat_id].append({"role": "assistant", "text": reply})
            
    except Exception as e:
        logger.error(f"Error handling general query: {e}")
        try:
            bot.send_message(chat_id, f"⚠️ Error processing query: `{e}`", parse_mode="Markdown")
        except Exception:
            bot.send_message(chat_id, f"⚠️ Error processing query: `{e}`")


def send_daily_report():
    """
    Cron job task executed daily. Fetches Render/Cloudflare status and publishes the status card.
    """
    chat_id = config.get_target_chat_id()
    if not chat_id:
        logger.warning("Daily report scheduler fired, but no cached target chat ID exists.")
        return
        
    logger.info(f"Triggering daily status report for chat ID {chat_id}...")
    try:
        card = get_status_card(title="Autoopsy Daily Status Report")
        bot.send_message(chat_id, card, parse_mode="Markdown", disable_web_page_preview=True)
        logger.info("Daily metrics report dispatched successfully.")
    except Exception as e:
        logger.error(f"Error generating daily metrics report: {e}")
        bot.send_message(chat_id, f"⚠️ Failed to generate daily metrics report: `{e}`", parse_mode="Markdown")
