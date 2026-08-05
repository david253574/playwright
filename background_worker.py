import json
import concurrent.futures
import threading

history_lock = threading.Lock()
import os
import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth
from auto_responder_bg import check_auto_responder

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def can_post_to_community(p_id, comm_url, max_daily_posts):
    if max_daily_posts <= 0: return True
    history_file = "daily_post_history.json"
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except: pass
    
    from datetime import timedelta
    now = datetime.now()
    cutoff = now - timedelta(days=1)
    
    if p_id not in history: return True
    timestamps = history[p_id].get(comm_url, [])
    valid_count = sum(1 for ts in timestamps if datetime.fromisoformat(ts) > cutoff)
    return valid_count < max_daily_posts

def record_community_post(p_id, comm_url):
    history_file = "daily_post_history.json"
    with history_lock:
        history = {}
        if os.path.exists(history_file):
            try:
                with open(history_file, "r") as f:
                    history = json.load(f)
            except: pass
        
        if p_id not in history: history[p_id] = {}
        if comm_url not in history[p_id]: history[p_id][comm_url] = []
        
        history[p_id][comm_url].append(datetime.now().isoformat())
        with open(history_file, "w") as f:
            json.dump(history, f)

def is_session_locked(user_data_dir):
    lock_file = os.path.join(user_data_dir, "SingletonLock")
    if os.path.lexists(lock_file):
        try:
            target = os.readlink(lock_file)
            parts = target.rsplit('-', 1)
            if len(parts) == 2:
                pid = int(parts[1])
                try:
                    os.kill(pid, 0)
                    return True # Process is still alive and locked
                except OSError:
                    # Process is dead, safe to remove lock
                    pass
            # If we reach here, process is dead or we couldn't parse PID
            try:
                os.remove(lock_file)
                cookie_file = os.path.join(user_data_dir, "SingletonCookie")
                if os.path.lexists(cookie_file):
                    os.remove(cookie_file)
            except: pass
            return False
        except Exception as e:
            log(f"Warning: Could not parse lock file, forcing removal: {e}")
            try:
                os.remove(lock_file)
            except: pass
            return False
    return False


def human_typing(page, selector, text):
    element = page.locator(selector).first
    element.focus()
    element.click(force=True)
    time.sleep(random.uniform(0.5, 1.5))
    for char in text:
        try:
            page.keyboard.press(char)
        except Exception:
            # Fallback for unrecognized characters (like smart quotes)
            page.keyboard.insert_text(char)
            
        if char in [" ", ",", ".", "!", "?", "\n"]:
            time.sleep(random.uniform(0.2, 0.6))
        else:
            time.sleep(random.uniform(0.03, 0.15))

def process_profile(profile, user_tweet_text, uploaded_media_path=None, selected_group_url=None, comment_text=None):
    user_data_dir = profile.get("user_data_dir")
    
    with sync_playwright() as p:
        context = None
        if is_session_locked(user_data_dir):
            log(f"Browser locked for {profile['id']}")
            return False
            
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--disable-features=Translate",
                    "--disable-sync"
                ],
                viewport={"width": random.choice([1366, 1440, 1920, 1536]), "height": random.choice([768, 900, 1080, 864])},
                ignore_default_args=["--enable-automation"]
            )
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            context.set_default_navigation_timeout(60000)
            
            if selected_group_url and selected_group_url.startswith("/i/communities/"):
                log(f"[{profile['id']}] Navigating to community...")
                page.goto(f"https://x.com{selected_group_url}", wait_until="domcontentloaded", timeout=60000, referer="https://x.com/home")
            else:
                log(f"Invalid community URL: {selected_group_url}")
                return False
            
            time.sleep(random.uniform(3.0, 5.0))
            
            # 1. Automatically join the community if not a member!
            try:
                join_btn = page.get_by_role("button", name="Join", exact=True)
                if join_btn.count() > 0 and join_btn.first.is_visible():
                    log(f"[{profile['id']}] Account is not a member. Clicking Join...")
                    time.sleep(random.uniform(0.8, 1.8))
                    join_btn.first.click(position={"x": random.randint(5, 20), "y": random.randint(5, 15)})
                    time.sleep(random.uniform(2.0, 4.0))
            except: pass
            
                        # Simulate human mouse movement and scroll
            try:
                page.mouse.move(random.randint(100, 500), random.randint(100, 500), steps=10)
                time.sleep(random.uniform(0.5, 1.5))
                page.mouse.wheel(0, random.randint(200, 500))
                time.sleep(random.uniform(0.5, 1.5))
                page.mouse.wheel(0, -random.randint(100, 300))
            except: pass
            
            log(f"[{profile['id']}] Waiting for community page to stabilize...")
            time.sleep(random.uniform(3.0, 5.0))
            
            # Extract community name from page title to force it later
            full_title = page.title()
            import re
            raw_name = full_title.split(' / X')[0].replace(' Community', '').strip()
            community_name = re.sub(r'^\(\d+\+?\)\s*', '', raw_name)
            log(f"[{profile['id']}] Identified community as: {community_name}")
            
            log(f"[{profile['id']}] Triggering compose modal...")
            page.keyboard.press('n')
            time.sleep(random.uniform(2.0, 4.0))
            
            # FORCE the audience to be the community if it defaulted to Everyone
            try:
                audience_btn = page.locator('div[aria-label="Choose audience"], button[aria-label="Choose audience"], div[role="button"][aria-label="Choose audience"]').first
                if audience_btn.is_visible(timeout=5000):
                    current_audience = audience_btn.inner_text()
                    if "Everyone" in current_audience and community_name:
                        log(f"[{profile['id']}] Audience defaulted to 'Everyone'. Forcing community selection...")
                        audience_btn.click(force=True)
                        time.sleep(random.uniform(1.0, 2.0))
                        
                        # Find the menu item containing the community name
                        menu_item = page.locator(f'[role="menuitem"]:has-text("{community_name}")').first
                        if menu_item.is_visible(timeout=5000):
                            menu_item.click(force=True)
                            time.sleep(random.uniform(0.5, 1.5))
                            log(f"[{profile['id']}] Successfully forced audience to: {community_name}")
                        else:
                            log(f"[{profile['id']}] Could not find '{community_name}' in audience dropdown! Aborting to prevent main feed spam.")
                            page.keyboard.press('Escape')
                            return False
                    else:
                        log(f"[{profile['id']}] Audience is correctly set to: {current_audience}")
            except Exception as e:
                log(f"[{profile['id']}] Audience verification skipped/failed: {e}")
                    
            log(f"[{profile['id']}] Directing text payload...")
            
            editor_selectors = [
                'div[data-testid="tweetTextarea_0RichTextInputContainer"]',
                'div[data-testid="tweetTextarea_0RichTextField"]', 
                'div[data-testid="tweetTextarea_0"]', 
                'div[role="textbox"]',
                '.public-DraftEditor-content'
            ]
            combined_editor = ", ".join(editor_selectors)
            try:
                page.wait_for_selector(combined_editor, state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                log("Composer element missing.")
                return False

            human_typing(page, combined_editor, user_tweet_text)
            time.sleep(random.uniform(0.8, 1.5))
            
            if uploaded_media_path and os.path.exists(uploaded_media_path):
                log(f"[{profile['id']}] Attaching local media upload stream...")
                file_input = page.locator('input[data-testid="fileInput"]')
                file_input.set_input_files(uploaded_media_path)
                time.sleep(random.uniform(4.0, 6.5))
            
            log(f"[{profile['id']}] Clicking the Post button...")
            try:
                # Wait for any media uploads to finish by checking if the post button is enabled
                post_btn = page.locator('button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]').last
                post_btn.wait_for(state="visible", timeout=5000)
                
                # Wait up to 15 seconds for the button to become enabled (media uploading)
                for _ in range(15):
                    if not post_btn.is_disabled():
                        break
                    time.sleep(random.uniform(0.8, 1.5))
                    
                post_btn.click(position={"x": random.randint(10, 40), "y": random.randint(5, 15)}, force=True)
                time.sleep(random.uniform(4.0, 6.5))
            except Exception as e:
                log(f"Could not find or click the Post button, falling back to hotkey: {e}")
                page.locator(combined_editor).first.focus()
                page.keyboard.press("Control+Enter")
                time.sleep(random.uniform(4.0, 6.5))
                
            log(f"🎉 [{profile['id']}] Content published successfully!")

            if comment_text:
                comments_to_post = [c.strip() for c in comment_text.split('---') if c.strip()]
                if comments_to_post:
                    log(f"[{profile['id']}] Waiting for post to appear to add {len(comments_to_post)} comment(s)...")
                    try:
                        try:
                            page.locator('button:has-text("Got it"), button:has-text("Got It")').first.click(timeout=3000)
                            time.sleep(1)
                        except:
                            pass
                        
                        toast_link = page.locator('div[data-testid="toast"] a[href*="/status/"]').first
                        try:
                            toast_link.wait_for(state="visible", timeout=8000)
                            toast_link.click(force=True)
                        except Exception:
                            log(f"[{profile['id']}] Toast not found, finding our post in the feed...")
                            try:
                                profile_href = page.locator('a[data-testid="AppTabBar_Profile_Link"]').get_attribute('href')
                                if profile_href:
                                    first_tweet = page.locator(f'article[data-testid="tweet"] a[dir="auto"][href^="{profile_href}/status/"]').first
                                    if first_tweet.count() == 0:
                                        first_tweet = page.locator(f'article[data-testid="tweet"] a[href*="{profile_href}/status/"]').first
                                    first_tweet.click(force=True)
                            except Exception as inner_e:
                                log(f"[{profile['id']}] Could not locate our post in feed: {inner_e}")
                        time.sleep(random.uniform(2.0, 4.0))
                        
                        reply_selectors = [
                            'div[data-testid="tweetTextarea_0RichTextInputContainer"]',
                            'div[data-testid="tweetTextarea_0RichTextField"]',
                            'div[data-testid="tweetTextarea_0"]',
                            '.public-DraftEditor-content'
                        ]
                        
                        for idx, c_text in enumerate(comments_to_post):
                            reply_area = page.locator(", ".join(reply_selectors)).first
                            reply_area.wait_for(state="visible", timeout=10000)
                            human_typing(page, ", ".join(reply_selectors), c_text)
                            time.sleep(random.uniform(0.8, 1.5))
                            
                            reply_btn = page.locator('button[data-testid="tweetButtonInline"]').first
                            try:
                                for _ in range(10):
                                    if not reply_btn.is_disabled(): break
                                    time.sleep(1)
                                reply_btn.click(position={"x": random.randint(10, 30), "y": random.randint(5, 15)}, timeout=5000)
                            except Exception:
                                log(f"[{profile['id']}] Reply button disabled/unclickable, falling back to hotkey.")
                                reply_area.focus()
                                page.keyboard.press("Control+Enter")
                            
                            time.sleep(random.uniform(2.0, 4.0))
                            log(f"[{profile['id']}] Comment {idx+1} added successfully.")
                    except Exception as e:
                        try: page.screenshot(path=f"debug_comments_{profile['id']}.png")
                        except: pass
                        log(f"[{profile['id']}] Could not add comments: {e} (Screenshot saved to debug_comments_{profile['id']}.png)")

            time.sleep(random.uniform(3.0, 5.0))
            return True
            
        except Exception as e:
            log(f"Browser launch error: {e}")
            return False
        finally:
            if context: 
                try: context.close()
                except: pass

def run_worker():
    log("Started background worker...")
    while True:
        try:
            # Check for background auto-responder tasks first
            check_auto_responder()
            
            queue = []
            if os.path.exists("scheduled_queue.json"):
                try:
                    with open("scheduled_queue.json", "r") as f:
                        content = f.read().strip()
                        if content:
                            queue = json.loads(content)
                except Exception as read_err:
                    log(f"Warning: Could not read queue file right now (might be actively writing): {read_err}")
                    time.sleep(random.uniform(4.0, 6.5))
                    continue
                
                now = datetime.now()
                executed_job_ids = []
                for job in queue:
                    job_time = datetime.fromisoformat(job["scheduled_datetime"])
                    if now >= job_time:
                        executed_job_ids.append(job["id"])
                        log(f"Executing job {job['id']} scheduled for {job['scheduled_datetime']}")
                        
                        # Load data
                        profiles_data = []
                        if os.path.exists("profiles.json"):
                            with open("profiles.json", "r") as f:
                                profiles_data = json.load(f)
                        
                        communities_cache = {}
                        if os.path.exists("communities_cache.json"):
                            with open("communities_cache.json", "r") as f:
                                communities_cache = json.load(f)
                        
                        active_drafts = job.get("active_drafts", {})
                        active_comments = job.get("active_comments", {})
                        pool_selections = job.get("pool_selections", {})
                        bulk_json_drafts = job.get("bulk_json_drafts", [])
                        uploaded_images = job.get("uploaded_images", {})
                        
                        # Get accounts to post to
                        keys_to_process = list(active_drafts.keys()) + (list(communities_cache.keys()) if bulk_json_drafts else [])
                        # Deduplicate while preserving order
                        unique_keys = []
                        for k in keys_to_process:
                            if k not in unique_keys:
                                unique_keys.append(k)

                        def process_chunk(chunk):
                            for p_id in chunk:
                                if p_id not in active_drafts and not bulk_json_drafts: continue
                                
                                log(f"Initiating Profile: {p_id}")
                                prof_data = next((p for p in profiles_data if p["id"] == p_id), None)
                                if not prof_data: continue
                                
                                pool = pool_selections.get(p_id, [])
                                if not pool:
                                    log(f"No communities selected for {p_id}.")
                                    continue
                                    
                                to_post = random.sample(pool, min(2, len(pool)))
                                profile_comms = communities_cache.get(p_id, {})
                                
                                drafted_text = active_drafts.get(p_id, "")
                                comment_text = active_comments.get(p_id, "")
                                img_path = uploaded_images.get(p_id)
                                
                                for i, comm_name in enumerate(to_post):
                                    target_url = profile_comms.get(comm_name, {}).get("url") if isinstance(profile_comms.get(comm_name), dict) else profile_comms.get(comm_name)
                                    if not target_url or "suggested" in target_url:
                                        continue
                                    
                                    if bulk_json_drafts:
                                        drafted_text = random.choice(bulk_json_drafts)
                                    
                                    log(f"Posting to '{comm_name}' (Random Selection #{i+1})...")
                                    
                                    success = process_profile(prof_data, drafted_text, img_path, target_url, comment_text)
                                    if success:
                                        record_community_post(p_id, target_url)
                                    else:
                                        log(f"Post failed for {comm_name}, skipping record.")
                                    
                                    wait_time = random.randint(15, 30)
                                    log(f"Pacing: Waiting {wait_time}s before next post...")
                                    time.sleep(wait_time)

                        # Chunk the accounts into groups of 10
                        chunk_size = 10
                        chunks = [unique_keys[i:i + chunk_size] for i in range(0, len(unique_keys), chunk_size)]
                        
                        log(f"Queueing {len(unique_keys)} accounts in {len(chunks)} chunks of 10...")
                        
                        # Run 2 chunks simultaneously
                        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                            executor.map(process_chunk, chunks)
                                
                    
                # Save remaining jobs by re-reading to avoid race conditions with UI
                if executed_job_ids:
                    try:
                        with open("scheduled_queue.json", "r") as f:
                            latest_queue = json.load(f)
                        
                        final_remaining = [j for j in latest_queue if j["id"] not in executed_job_ids]
                        
                        with open("scheduled_queue.json", "w") as f:
                            json.dump(final_remaining, f, indent=4)
                    except Exception as err:
                        log(f"Error updating queue: {err}")
        except Exception as e:
            log(f"Worker iteration error: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    run_worker()
