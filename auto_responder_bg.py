import os
import time
import json
import random
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def human_pause(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))

def is_session_locked(user_data_dir):
    if not user_data_dir: return False
    lock_file = os.path.join(user_data_dir, "SingletonLock")
    return os.path.exists(lock_file)

def process_auto_responder_bg(profile, universal_msg, check_priority=True, check_hidden=True, unlock_password="2004", skip_older_than_hours=2.0):
    """Auto-replies to messages in Priority and Hidden tabs silently."""
    user_data_dir = profile.get("user_data_dir")
    final_reply = universal_msg
    
    with sync_playwright() as p:
        context = None
        if is_session_locked(user_data_dir):
            log(f"Browser locked for {profile['id']}")
            return
            
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-features=Translate",
                    "--disable-sync"
                ]
            )
            page = context.new_page()
            context.set_default_navigation_timeout(60000)
            
            # Scrape main inbox first to build a whitelist of already-accepted users
            log(f"[{profile['id']}] Scraping main inbox for already-accepted users...")
            page.goto("https://x.com/messages", wait_until="commit")
            human_pause(4.0, 6.0)
            
            try:
                pwd_input = page.locator('input[type="password"], input[name="pin"], input[placeholder*="password" i], input[placeholder*="pin" i]').first
                pwd_input.wait_for(state="visible", timeout=3000)
                log(f"[{profile['id']}] Found standard chat lock screen on main inbox. Entering password...")
                pwd_input.fill(unlock_password)
                human_pause(1.5, 3.0)
                page.keyboard.press("Enter")
                human_pause(3.0, 5.0)
            except Exception:
                try:
                    passcode_text = page.get_by_text("Enter Passcode").first
                    passcode_text.wait_for(state="visible", timeout=10000)
                    log(f"[{profile['id']}] Found Encrypted DM Passcode screen. Typing PIN...")
                    pin_inputs = page.locator('div[data-testid="pin-code-input-container"] input')
                    if pin_inputs.count() >= 4:
                        for i in range(4):
                            if i < len(unlock_password):
                                pin_inputs.nth(i).focus()
                                page.keyboard.press(unlock_password[i])
                                human_pause(0.2, 0.4)
                    else:
                        box = passcode_text.bounding_box()
                        if box: page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] + 60)
                        else: page.mouse.click(500, 500)
                        for char in unlock_password:
                            page.keyboard.press(char)
                            human_pause(0.2, 0.4)
                    human_pause(1.0, 2.0)
                    page.keyboard.press("Enter")
                    human_pause(3.0, 5.0)
                except Exception: pass
            
            accepted_users_whitelist = set()
            try:
                # Wait up to 5 seconds for conversations to appear
                page.wait_for_selector('[data-testid^="dm-conversation-item-"], [data-testid="conversation"]', timeout=5000)
                # Scrape while scrolling to catch virtualized DOM elements
                for _ in range(12):
                    main_convos = page.locator('[data-testid^="dm-conversation-item-"], [data-testid="conversation"]')
                    for i in range(main_convos.count()):
                        try:
                            name = main_convos.nth(i).inner_text().split('\n')[0].strip()
                            accepted_users_whitelist.add(name)
                        except: pass
                    page.keyboard.press("PageDown")
                    human_pause(1.0, 2.0)
                log(f"[{profile['id']}] Whitelisted {len(accepted_users_whitelist)} users from main inbox.")
            except Exception as e:
                log(f"[{profile['id']}] Main inbox is empty or loading took too long. Proceeding...")
                try: page.screenshot(path=f"debug_inbox_{profile['id']}.png")
                except: pass
                
            log(f"[{profile['id']}] Navigating to message requests...")
            page.goto("https://x.com/messages/requests", wait_until="commit")
            human_pause(4.0, 6.0)
            
            try:
                pwd_input = page.locator('input[type="password"], input[name="pin"], input[placeholder*="password" i], input[placeholder*="pin" i]').first
                pwd_input.wait_for(state="visible", timeout=3000)
                log(f"[{profile['id']}] Found standard chat lock screen. Entering password...")
                pwd_input.fill(unlock_password)
                human_pause(1.5, 3.0)
                page.keyboard.press("Enter")
                human_pause(3.0, 5.0)
            except Exception:
                try:
                    passcode_text = page.get_by_text("Enter Passcode").first
                    passcode_text.wait_for(state="visible", timeout=10000)
                    log(f"[{profile['id']}] Found Encrypted DM Passcode screen. Typing PIN...")
                    pin_inputs = page.locator('div[data-testid="pin-code-input-container"] input')
                    if pin_inputs.count() >= 4:
                        for i in range(4):
                            if i < len(unlock_password):
                                pin_inputs.nth(i).focus()
                                page.keyboard.press(unlock_password[i])
                                human_pause(0.2, 0.4)
                    else:
                        box = passcode_text.bounding_box()
                        if box: page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] + 60)
                        else: page.mouse.click(500, 500)
                        for char in unlock_password:
                            page.keyboard.press(char)
                            human_pause(0.2, 0.4)
                    human_pause(1.0, 2.0)
                    page.keyboard.press("Enter")
                    human_pause(3.0, 5.0)
                except Exception: pass
            
            tabs_to_check = []
            if check_priority: tabs_to_check.append("Priority")
            if check_hidden: tabs_to_check.append("Hidden")
            
            processed_unified_list = False
            
            for tab_name in tabs_to_check:
                if processed_unified_list:
                    break
                    
                log(f"[{profile['id']}] Processing '{tab_name}' tab...")
                try:
                    tab_locator = page.locator(f"[role='tab']:has-text('{tab_name}'), a:has-text('{tab_name}'), span:text-is('{tab_name}')").first
                    try:
                        tab_locator.wait_for(state="visible", timeout=10000)
                        tab_locator.click()
                        human_pause(2.0, 4.0)
                    except Exception:
                        log(f"Could not find the '{tab_name}' tab on screen. Your account might not use tabs. Processing visible requests anyway...")
                        if tab_name == "Hidden":
                            # If we are on the second tab and it fails, we already processed the main page on 'Priority'.
                            # No need to process the exact same list twice.
                            log("Skipping duplicate processing for tabless account.")
                            continue
                        processed_unified_list = True
                    
                    processed_users = set()
                    
                    while True:
                        try:
                            page.wait_for_selector('[data-testid^="dm-conversation-item-"], [data-testid="conversation"], [data-testid="dm-message-requests-empty"]', timeout=3000)
                        except: pass
                        
                        convos = page.locator('[data-testid^="dm-conversation-item-"], [data-testid="conversation"]')
                        if convos.count() == 0:
                            log(f"[{profile['id']}] No more pending conversations found in {tab_name}.")
                            break
                            
                        unprocessed_index = -1
                        current_convo_name = None
                        for i in range(convos.count()):
                            try:
                                name = convos.nth(i).inner_text().split('\n')[0].strip()
                            except:
                                name = f"unknown_{i}"
                            
                            if name in accepted_users_whitelist:
                                processed_users.add(name)
                                log(f"Skipping {name} as they are already in the main inbox (accepted).")
                                continue
                                
                            if name not in processed_users:
                                unprocessed_index = i
                                current_convo_name = name
                                break
                                
                        if unprocessed_index == -1:
                            break
                            
                        convo = convos.nth(unprocessed_index)
                        
                        try:
                            time_el = convo.locator('time').first
                            if time_el.count() > 0:
                                dt_str = time_el.get_attribute('datetime')
                                if dt_str:
                                    dt_str = dt_str.replace('Z', '+00:00')
                                    msg_time = datetime.fromisoformat(dt_str)
                                    now_utc = datetime.now(timezone.utc)
                                    diff = now_utc - msg_time
                                    if skip_older_than_hours > 0 and diff.total_seconds() > skip_older_than_hours * 3600:
                                        log(f"Message from {current_convo_name} is older than {skip_older_than_hours} hours. Skipping.")
                                        processed_users.add(current_convo_name)
                                        continue
                                        
                            convo_text = convo.inner_text().lower()
                            if "you accepted the request" in convo_text or "you sent" in convo_text or "you:" in convo_text:
                                processed_users.add(current_convo_name)
                                continue
                        except Exception as e:
                            log(f"Error during pre-screen check for {current_convo_name}: {e}")
                        convo.click()
                        human_pause(1.5, 3.0)
                        
                        try:
                            view_btn = page.get_by_role("button", name="View", exact=True).last
                            view_btn.wait_for(state="visible", timeout=1500)
                            view_btn.click()
                            human_pause(1.0, 2.0)
                        except: pass
                        
                        needs_reply = False
                        try:
                            first_words = " ".join(final_reply.split()[:3])
                            if page.get_by_text(first_words).count() > 0:
                                processed_users.add(current_convo_name)
                                continue
                        except: pass
                            
                        try:
                            accept_btn = page.get_by_role("button", name="Accept", exact=True).last
                            accept_btn.wait_for(state="visible", timeout=3000)
                            accept_btn.click()
                            human_pause(1.5, 3.0)
                            needs_reply = True
                        except: pass
                            
                        if not needs_reply:
                            processed_users.add(current_convo_name)
                            continue 
                            
                        log(f"[{profile['id']}] Replying to {current_convo_name}...")
                        try:
                            human_pause(1.5, 3.0)
                            all_textboxes = page.locator('div[role="textbox"], textarea')
                            visible_boxes = []
                            for i in range(all_textboxes.count()):
                                box = all_textboxes.nth(i)
                                if box.is_visible():
                                    visible_boxes.append(box)
                            
                            if visible_boxes:
                                editor = visible_boxes[-1]
                                editor.click(timeout=3000)
                                human_pause(0.5, 1.5)
                                editor.fill(final_reply)
                                human_pause(0.5, 1.0)
                                editor.press("Space")
                                editor.press("Backspace")
                                human_pause(1.5, 3.0)
                                
                                try:
                                    send_btn = page.locator('div[data-testid="dmComposerSendButton"], button[aria-label="Send"], div[aria-label="Send"]').last
                                    send_btn.wait_for(state="visible", timeout=3000)
                                    send_btn.click(timeout=3000)
                                except:
                                    editor.press("Enter")
                                
                                # CRITICAL: Wait long enough for the network request to finish!
                                # If we navigate away too quickly, the browser aborts the API call.
                                human_pause(4.0, 6.0)
                                
                                try:
                                    if page.get_by_text("Failed to send", ignore_case=True).is_visible(timeout=1000) or \
                                       page.get_by_text("Not sent", ignore_case=True).is_visible(timeout=1000):
                                        log(f"[{profile['id']}] Detected 'Failed to send' message! Rate limit or block likely.")
                                        return "FAILED_TO_SEND"
                                except: pass
                        except Exception as e:
                            log(f"Error replying to {current_convo_name}: {e}")
                        
                        processed_users.add(current_convo_name)
                        page.goto("https://x.com/messages/requests", wait_until="commit")
                        human_pause(2.0, 4.0)
                        
                        try:
                            tab_locator = page.locator(f"[role='tab']:has-text('{tab_name}'), a:has-text('{tab_name}'), span:text-is('{tab_name}')").first
                            tab_locator.wait_for(state="visible", timeout=10000)
                            tab_locator.click()
                            human_pause(2.0, 4.0)
                        except Exception:
                            log(f"Could not re-select the '{tab_name}' tab. Moving to next.")
                        
                except Exception as e:
                    log(f"Error processing tab {tab_name}: {e}")
                    
        except Exception as e:
            log(f"Auto-responder error: {e}")
        finally:
            if context:
                try: context.close()
                except: pass

def check_auto_responder():
    if not os.path.exists("auto_responder_config.json"): return
    try:
        with open("auto_responder_config.json", "r") as f:
            content = f.read().strip()
            if not content: return
            cfg = json.loads(content)
    except Exception as e: 
        log(f"Could not read auto responder config: {e}")
        return
    
    if not cfg.get("is_active"): return
    
    max_checks = cfg.get("max_checks", 0)
    checks_completed = cfg.get("checks_completed", 0)
    if max_checks > 0 and checks_completed >= max_checks:
        cfg["is_active"] = False
        with open("auto_responder_config.json", "w") as f:
            json.dump(cfg, f, indent=4)
        log("Auto-responder reached max checks. Deactivating.")
        return
        
    last_checked_iso = cfg.get("last_checked_iso")
    interval = cfg.get("interval_minutes", 60)
    now = datetime.now()
    if last_checked_iso:
        last_checked = datetime.fromisoformat(last_checked_iso)
        if (now - last_checked).total_seconds() < interval * 60:
            return 
            
    log("Running scheduled auto-responder background check...")
    
    try:
        with open("profiles.json", "r") as f:
            profiles = json.load(f)
    except: return
    
    run_all = cfg.get("run_all", False)
    sel_prof = cfg.get("selected_profile")
    profiles_to_run = profiles if run_all else [p for p in profiles if p["id"] == sel_prof]
    
    failed = False
    for prof in profiles_to_run:
        try:
            status = process_auto_responder_bg(
                prof, 
                cfg.get("universal_msg", ""), 
                cfg.get("check_priority", True), 
                cfg.get("check_hidden", True),
                cfg.get("unlock_password", ""),
                cfg.get("skip_older_than_hours", 2.0)
            )
            if status == "FAILED_TO_SEND":
                failed = True
                break
        except Exception as e:
            log(f"Unhandled exception in process_auto_responder_bg for {prof.get('id')}: {e}")
        
    # Re-read the config to avoid overwriting UI changes (like 'Stop') made while we were processing
    try:
        with open("auto_responder_config.json", "r") as f:
            content = f.read().strip()
            if content:
                latest_cfg = json.loads(content)
                if failed:
                    if latest_cfg.get("is_retry"):
                        log("Auto-responder failed to send AGAIN. Deactivating completely.")
                        latest_cfg["is_active"] = False
                        latest_cfg["is_retry"] = False
                    else:
                        log("Auto-responder failed to send. Suspending for 10 minutes and retrying...")
                        latest_cfg["is_retry"] = True
                        # Schedule next run for exactly 10 minutes from now
                        latest_cfg["last_checked_iso"] = (now - timedelta(minutes=interval - 10)).isoformat()
                else:
                    latest_cfg["is_retry"] = False
                    latest_cfg["last_checked_iso"] = now.isoformat()
                    latest_cfg["checks_completed"] = checks_completed + 1
                    
                with open("auto_responder_config.json", "w") as f:
                    json.dump(latest_cfg, f, indent=4)
    except Exception as e:
        log(f"Could not update auto responder config: {e}")
