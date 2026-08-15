import streamlit as st
import json
import os
import random
import time
import subprocess
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth

def human_pause(min_seconds: float = 2.0, max_seconds: float = 4.0):
    """Simulates user read-time and layout stability checks."""
    time.sleep(random.uniform(min_seconds, max_seconds))

def is_session_locked(user_data_dir):
    """Checks if the browser profile is currently locked by another process."""
    lock_file = os.path.join(user_data_dir, "SingletonLock")
    if os.path.lexists(lock_file):
        try:
            target = os.readlink(lock_file)
            parts = target.rsplit('-', 1)
            if len(parts) == 2:
                pid = int(parts[1])
                try:
                    os.kill(pid, 0)
                    st.warning("The browser profile is currently in use. Please close all browser windows to continue.")
                    return True # Process is still alive and locked
                except OSError:
                    pass # Process is dead, safe to remove lock                    pass
            # If we reach here, process is dead or we couldn't parse PID
            try:
                os.remove(lock_file)
                cookie_file = os.path.join(user_data_dir, "SingletonCookie")
                if os.path.lexists(cookie_file):
                    os.remove(cookie_file)
            except: pass
            return False
        except Exception as e:
            st.warning(f"Warning: Could not parse lock file, forcing removal: {e}")
            try:
                os.remove(lock_file)
            except: pass
            return False
    return False


def can_post_to_community(p_id, comm_url, max_daily_posts):
    if max_daily_posts <= 0: return True
    history_file = "daily_post_history.json"
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except: pass
    
    import datetime as dt
    now = dt.datetime.now()
    cutoff = now - dt.timedelta(days=1)
    
    if p_id not in history: return True
    timestamps = history[p_id].get(comm_url, [])
    valid_count = sum(1 for ts in timestamps if dt.datetime.fromisoformat(ts) > cutoff)
    return valid_count < max_daily_posts

def record_community_post(p_id, comm_url):
    history_file = "daily_post_history.json"
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except: pass
    
    if p_id not in history: history[p_id] = {}
    if comm_url not in history[p_id]: history[p_id][comm_url] = []
    
    import datetime as dt
    history[p_id][comm_url].append(dt.datetime.now().isoformat())
    with open(history_file, "w") as f:
        json.dump(history, f)

def fetch_joined_communities(profile):
    """Scrapes joined community metadata with strict filtering."""
    user_data_dir = profile.get("user_data_dir")
    communities = {}
    
    with sync_playwright() as p:
        context = None
        if is_session_locked(user_data_dir):
            return communities
            
        try:
            launch_args = {
                "user_data_dir": user_data_dir,
                "executable_path": "/usr/bin/google-chrome-stable",
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--disable-features=Translate", "--disable-sync"],
                "ignore_default_args": ["--enable-automation"]
            }
            if profile.get("proxy_url"):
                launch_args["proxy"] = {"server": profile.get("proxy_url")}
            context = p.chromium.launch_persistent_context(**launch_args)
            if profile.get("auth_token"):
                context.add_cookies([{"name": "auth_token", "value": profile.get("auth_token"), "domain": ".x.com", "path": "/"}])
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            
            # FIX: Never use networkidle on X. Use "commit" and a hard sleep.
            page.goto("https://x.com/i/communities", wait_until="domcontentloaded", timeout=60000)
            time.sleep(6) # Give React time to paint the UI
            
            # FIX: Restore the sidebar clicker in case X redirects to the homepage
            if "home" in page.url or "compose" in page.url:
                try:
                    page.locator('a[aria-label="Communities"]').first.click()
                    time.sleep(random.uniform(4.0, 6.5))
                except:
                    pass
            
            # Use a more specific locator to avoid navigation buttons, "See more", and hashtag links
            selector = 'a[href*="/i/communities/"]:not([href*="/hashtag/"]):not([href="/i/communities/discover"]):not([href="/i/communities/create"])'
            
            try:
                page.wait_for_selector(selector, timeout=15000, state="attached")
            except:
                pass # Don't crash, let it try to pull anyway
                
            elements = page.locator(selector)
            
            comm_list = []
            for i in range(elements.count()):
                el = elements.nth(i)
                href = el.get_attribute("href")
                # Clean up text: get only the first line, filter out noise
                title = el.inner_text().split("\n")[0].strip()
                
                # STRICT FILTER: Exclude system keywords
                invalid_keywords = ["see more", "communities", "discover", "create", "home", "notifications"]
                if href and title and not any(word in title.lower() for word in invalid_keywords):
                    comm_list.append((title, href))
            
            if comm_list:
                urls_to_fetch = [f"https://x.com{href}" for title, href in comm_list]
                js_code = """
                    async (urls) => {
                        let results = [];
                        const sleep = ms => new Promise(r => setTimeout(r, ms));
                        
                        for (let url of urls) {
                            try {
                                const response = await fetch(url, {credentials: 'omit'});
                                const html = await response.text();
                                const match = html.match(/<meta[^>]*name="twitter:data1"[^>]*content="([^"]+)"/);
                                results.push({ url, count: (match && match[1]) ? match[1] : "0" });
                                
                                // Wait 0.8 to 2 seconds between each fetch
                                await sleep(Math.floor(Math.random() * 1200) + 800); 
                            } catch (e) {
                                results.push({ url, count: "0" });
                            }
                        }
                        return results;
                    }
                """
                try:
                    results = page.evaluate(js_code, urls_to_fetch)
                    counts_dict = {res["url"]: res.get("count", "0") for res in results}
                except Exception as e:
                    counts_dict = {}
                
                for title, href in comm_list:
                    full_url = f"https://x.com{href}"
                    num_str = counts_dict.get(full_url, "0").upper().replace(',', '')
                    members = 0
                    try:
                        if 'K' in num_str:
                            members = int(float(num_str.replace('K', '')) * 1000)
                        elif 'M' in num_str:
                            members = int(float(num_str.replace('M', '')) * 1000000)
                        else:
                            members = int(float(num_str))
                    except ValueError:
                        pass
                    communities[title] = {"url": href, "members": members}
                    
        except Exception as e:
            st.warning(f"Sync failed for {profile['id']}: {e}")
        finally:
            if context: context.close()
            
    return communities if communities else None

def fetch_joined_communities_manual(profile):
    """Scrapes communities with a visible browser and a 60-second delay for manual login/captcha resolution."""
    user_data_dir = profile.get("user_data_dir")
    communities = {}
    
    with sync_playwright() as p:
        context = None
        page = None
        if is_session_locked(user_data_dir):
            return communities
            
        try:
            launch_args = {
                "user_data_dir": user_data_dir,
                "executable_path": "/usr/bin/google-chrome-stable",
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--disable-features=Translate", "--disable-sync"],
                "ignore_default_args": ["--enable-automation"]
            }
            if profile.get("proxy_url"):
                launch_args["proxy"] = {"server": profile.get("proxy_url")}
            context = p.chromium.launch_persistent_context(**launch_args)
            if profile.get("auth_token"):
                context.add_cookies([{"name": "auth_token", "value": profile.get("auth_token"), "domain": ".x.com", "path": "/"}])
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            
            st.info("Opening browser. Please manually navigate to the Communities tab or resolve any login walls.")
            try:
                # Use "commit" so it doesn't wait for heavy background trackers
                page.goto("https://x.com/i/communities", wait_until="domcontentloaded", timeout=60000)
            except PlaywrightTimeoutError:
                # If it still times out, ignore the error and let the 30-second manual UI countdown continue
                pass
            except Exception as e:
                st.warning(f"Network navigation interrupted, but continuing manual fallback... ({e})")
            
            # 60-second wait for manual interaction
            progress = st.progress(0)
            for i in range(60):
                time.sleep(random.uniform(0.8, 1.5))
                progress.progress((i + 1) / 60, text=f"Waiting for manual approval... {60 - i} seconds remaining.")
            
            st.info("Scanning DOM tree...")
            # Use a more specific locator to avoid navigation buttons, "See more", and hashtag links
            selector = 'a[href*="/i/communities/"]:not([href*="/hashtag/"]):not([href="/i/communities/discover"]):not([href="/i/communities/create"])'
            elements = page.locator(selector)
            if elements.count() == 0:
                st.warning("Manual sync failed: No communities found on screen after 60 seconds.")
                
            comm_list = []
            for i in range(elements.count()):
                el = elements.nth(i)
                try:
                    href = el.get_attribute("href")
                    if not href or href.strip() == "/i/communities" or href.strip() == "/i/communities/":
                        continue
                    raw_text = el.inner_text().strip()
                    if not raw_text or "Communities" in raw_text:
                        continue
                    title = raw_text.split("\n")[0]
                    if title and href:
                        comm_list.append((title, href))
                except Exception:
                    continue
            
            if comm_list:
                st.info(f"Found {len(comm_list)} communities. Fetching member counts...")
            if comm_list:
                urls_to_fetch = [f"https://x.com{href}" for title, href in comm_list]
                js_code = """
                    async (urls) => {
                        return await Promise.all(urls.map(async (url) => {
                            try {
                                const response = await fetch(url, {credentials: 'omit'});
                                const html = await response.text();
                                const match = html.match(/<meta[^>]*name="twitter:data1"[^>]*content="([^"]+)"/);
                                return { url, count: (match && match[1]) ? match[1] : "0" };
                            } catch (e) {
                                return { url, count: "0" };
                            }
                        }));
                    }
                """
                try:
                    results = page.evaluate(js_code, urls_to_fetch)
                    counts_dict = {res["url"]: res.get("count", "0") for res in results}
                except Exception as e:
                    counts_dict = {}
                
                for title, href in comm_list:
                    full_url = f"https://x.com{href}"
                    num_str = counts_dict.get(full_url, "0").upper().replace(',', '')
                    members = 0
                    try:
                        if 'K' in num_str:
                            members = int(float(num_str.replace('K', '')) * 1000)
                        elif 'M' in num_str:
                            members = int(float(num_str.replace('M', '')) * 1000000)
                        else:
                            members = int(float(num_str))
                    except ValueError:
                        pass
                    communities[title] = {"url": href, "members": members}
        except Exception as e:
            st.error(f"Manual browser could not be opened: {e}")
        finally:
            if context:
                try:
                    context.close()
                except:
                    pass
    return communities


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
    """Executes the automated posting sequence using headless persistent contexts."""
    user_data_dir = profile.get("user_data_dir")
    
    with sync_playwright() as p:
        context = None
        if is_session_locked(user_data_dir):
            return
            
        try:
            launch_args = {
                "user_data_dir": user_data_dir,
                "executable_path": "/usr/bin/google-chrome-stable",
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--disable-features=Translate", "--disable-sync"],
                "ignore_default_args": ["--enable-automation"]
            }
            if profile.get("proxy_url"):
                launch_args["proxy"] = {"server": profile.get("proxy_url")}
            context = p.chromium.launch_persistent_context(**launch_args)
            if profile.get("auth_token"):
                context.add_cookies([{"name": "auth_token", "value": profile.get("auth_token"), "domain": ".x.com", "path": "/"}])
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            context.set_default_navigation_timeout(60000)
            
            if selected_group_url and selected_group_url.startswith("/i/communities/"):
                st.info(f"[{profile['id']}] Navigating to community...")
                # FIX: Remove networkidle here as well!
                page.goto(f"https://x.com{selected_group_url}", wait_until="domcontentloaded", timeout=60000, referer="https://x.com/home")
            else:
                st.error(f"Invalid community URL: {selected_group_url}")
                return False
            
            time.sleep(random.uniform(3.0, 5.0))
            
            # 1. Automatically join the community if not a member!
            try:
                join_btn = page.get_by_role("button", name="Join", exact=True)
                if join_btn.count() > 0 and join_btn.first.is_visible():
                    st.info(f"[{profile['id']}] Account is not a member. Clicking Join...")
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
            
            st.info(f"[{profile['id']}] Waiting for community page to stabilize...")
            time.sleep(random.uniform(3.0, 5.0))
            
            # Extract community name from page title to force it later
            full_title = page.title()
            import re
            raw_name = full_title.split(' / X')[0].replace(' Community', '').strip()
            community_name = re.sub(r'^\(\d+\+?\)\s*', '', raw_name)
            st.info(f"[{profile['id']}] Identified community as: {community_name}")
            
            st.info(f"[{profile['id']}] Triggering compose modal...")
            page.keyboard.press('n')
            time.sleep(random.uniform(2.0, 4.0))
            
            # FORCE the audience to be the community if it defaulted to Everyone
            try:
                audience_btn = page.locator('div[aria-label="Choose audience"], button[aria-label="Choose audience"], div[role="button"][aria-label="Choose audience"]').first
                if audience_btn.is_visible(timeout=5000):
                    current_audience = audience_btn.inner_text()
                    if "Everyone" in current_audience and community_name:
                        st.info(f"[{profile['id']}] Audience defaulted to 'Everyone'. Forcing community selection...")
                        audience_btn.click(force=True)
                        time.sleep(random.uniform(1.0, 2.0))
                        
                        # Find the menu item containing the community name
                        menu_item = page.locator(f'[role="menuitem"]:has-text("{community_name}")').first
                        if menu_item.is_visible(timeout=5000):
                            menu_item.click(force=True)
                            time.sleep(random.uniform(0.5, 1.5))
                            st.success(f"[{profile['id']}] Successfully forced audience to: {community_name}")
                        else:
                            st.warning(f"[{profile['id']}] Could not find '{community_name}' in audience dropdown! Aborting to prevent main feed spam.")
                            page.keyboard.press('Escape')
                            return False
                    else:
                        st.success(f"[{profile['id']}] Audience is correctly set to: {current_audience}")
            except Exception as e:
                st.warning(f"[{profile['id']}] Audience verification skipped/failed: {e}")
                    
            st.info(f"[{profile['id']}] Directing text payload to dashboard composer...")
            
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
                st.error("Composer element missing.")
                return False

            human_typing(page, combined_editor, user_tweet_text)
            time.sleep(random.uniform(0.8, 1.5))
            
            if uploaded_media_path and os.path.exists(uploaded_media_path):
                st.info(f"[{profile['id']}] Attaching local media upload stream...")
                file_input = page.locator('input[data-testid="fileInput"]')
                file_input.set_input_files(uploaded_media_path)
                time.sleep(random.uniform(4.0, 6.5))
            
            st.info(f"[{profile['id']}] Clicking the Post button...")
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
                st.warning(f"Could not find or click the Post button, falling back to hotkey: {e}")
                page.locator(combined_editor).first.focus()
                page.keyboard.press("Control+Enter")
                time.sleep(random.uniform(4.0, 6.5))
                
            st.success(f"[{profile['id']}] Content published successfully.")

            if comment_text:
                comments_to_post = [c.strip() for c in comment_text.split('---') if c.strip()]
                if comments_to_post:
                    st.info(f"[{profile['id']}] Waiting for post to appear to add {len(comments_to_post)} comment(s)...")
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
                            st.warning(f"[{profile['id']}] Toast not found, finding our post in the feed...")
                            try:
                                page.wait_for_timeout(2000)
                                profile_href = page.locator('a[data-testid="AppTabBar_Profile_Link"]').get_attribute('href')
                                if profile_href:
                                    first_tweet = page.locator(f'article[data-testid="tweet"] a[dir="auto"][href^="{profile_href}/status/"]').first
                                    if first_tweet.count() == 0:
                                        first_tweet = page.locator(f'article[data-testid="tweet"] a[href*="{profile_href}/status/"]').first
                                    if first_tweet.count() == 0:
                                        st.warning(f"[{profile['id']}] Not found in feed, refreshing page...")
                                        page.reload(wait_until="domcontentloaded")
                                        page.wait_for_timeout(4000)
                                        first_tweet = page.locator(f'article[data-testid="tweet"] a[dir="auto"][href^="{profile_href}/status/"]').first
                                        if first_tweet.count() == 0:
                                            first_tweet = page.locator(f'article[data-testid="tweet"] a[href*="{profile_href}/status/"]').first
                                    first_tweet.click(force=True)
                            except Exception as inner_e:
                                st.error(f"[{profile['id']}] Could not locate our post in feed: {inner_e}")
                                raise Exception("Aborting comment: could not navigate to post status page.")
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
                                st.warning(f"[{profile['id']}] Reply button disabled/unclickable, falling back to hotkey.")
                                reply_area.focus()
                                page.keyboard.press("Control+Enter")
                                
                            time.sleep(random.uniform(2.0, 4.0))
                            st.success(f"[{profile['id']}] Comment {idx+1} added successfully.")
                    except Exception as e:
                        try: page.screenshot(path=f"debug_comments_{profile['id']}.png")
                        except: pass
                        st.warning(f"[{profile['id']}] Could not add comments: {e} (Screenshot saved as debug_comments_{profile['id']}.png)")

            time.sleep(random.uniform(3.0, 5.0))
            return True
            
        except Exception as e:
            st.error(f"Browser launch error: {e}")
            return False
        finally:
            if context: 
                try:
                    context.close()
                except Exception:
                    pass

def process_auto_responder(profile, universal_msg, check_priority=True, check_hidden=True, unlock_password="2004", skip_older_than_hours=2.0):
    """Auto-replies to messages in Priority and Hidden tabs."""
    user_data_dir = profile.get("user_data_dir")
    final_reply = universal_msg
    
    with sync_playwright() as p:
        context = None
        if is_session_locked(user_data_dir):
            st.error(f"Browser locked for {profile['id']}")
            return False
            
        try:
            launch_args = {
                "user_data_dir": user_data_dir,
                "executable_path": "/usr/bin/google-chrome-stable",
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--disable-features=Translate", "--disable-sync"],
                "ignore_default_args": ["--enable-automation"]
            }
            if profile.get("proxy_url"):
                launch_args["proxy"] = {"server": profile.get("proxy_url")}
            context = p.chromium.launch_persistent_context(**launch_args)
            if profile.get("auth_token"):
                context.add_cookies([{"name": "auth_token", "value": profile.get("auth_token"), "domain": ".x.com", "path": "/"}])
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            context.set_default_navigation_timeout(60000)
            
            # X Message Requests URL
            # Scrape main inbox first to build a whitelist of already-accepted users
            st.info(f"[{profile['id']}] Scraping main inbox for already-accepted users...")
            page.goto("https://x.com/messages", wait_until="domcontentloaded")
            human_pause(4.0, 6.0)
            
            try:
                pwd_input = page.locator('input[type="password"], input[name="pin"], input[placeholder*="password" i], input[placeholder*="pin" i]').first
                pwd_input.wait_for(state="visible", timeout=3000)
                st.info(f"[{profile['id']}] Found standard chat lock screen on main inbox. Entering password...")
                pwd_input.fill(unlock_password)
                human_pause(1.5, 3.0)
                page.keyboard.press("Enter")
                human_pause(3.0, 5.0)
            except Exception:
                try:
                    passcode_text = page.get_by_text("Enter Passcode").first
                    passcode_text.wait_for(state="visible", timeout=10000)
                    st.info(f"[{profile['id']}] Found Encrypted DM Passcode screen. Typing PIN...")
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
                page.wait_for_selector('[data-testid^="dm-conversation-item-"], [data-testid="conversation"]', timeout=5000)
                # Scrape while scrolling to catch virtualized DOM elements
                for _ in range(12):
                    main_convos = page.locator('[data-testid^="dm-conversation-item-"], [data-testid="conversation"]')
                    for i in range(main_convos.count()):
                        try:
                            name = main_convos.nth(i).inner_text().split('\n')[0].strip()
                            accepted_users_whitelist.add(name)
                        except Exception: pass
                    page.keyboard.press("PageDown")
                    human_pause(1.0, 2.0)
                st.success(f"[{profile['id']}] Whitelisted {len(accepted_users_whitelist)} users from main inbox.")
            except Exception:
                st.warning(f"[{profile['id']}] Main inbox is empty or loading took too long. Proceeding...")
                try: page.screenshot(path=f"debug_inbox_{profile['id']}.png")
                except: pass

            # X Message Requests URL
            st.info(f"[{profile['id']}] Navigating to message requests...")
            page.goto("https://x.com/messages/requests", wait_until="domcontentloaded")
            human_pause(4.0, 6.0)
            
            try:
                pwd_input = page.locator('input[type="password"], input[name="pin"], input[placeholder*="password" i], input[placeholder*="pin" i]').first
                pwd_input.wait_for(state="visible", timeout=3000)
                st.info(f"[{profile['id']}] Found standard chat lock screen. Entering password...")
                pwd_input.fill(unlock_password)
                human_pause(1.5, 3.0)
                page.keyboard.press("Enter")
                human_pause(3.0, 5.0)
            except Exception:
                try:
                    passcode_text = page.get_by_text("Enter Passcode").first
                    passcode_text.wait_for(state="visible", timeout=10000)
                    st.info(f"[{profile['id']}] Found Encrypted DM Passcode screen. Typing PIN...")
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
                st.info(f"[{profile['id']}] Processing '{tab_name}' tab...")
                try:
                    # Give X more time to render the UI, targeting only visible elements
                    selector = f"[role='tab']:has-text('{tab_name}'), a:has-text('{tab_name}'), span:text-is('{tab_name}')"
                    if tab_name == "Hidden":
                        selector += ", button[data-testid='dm-message-requests-other-button'], [role='tab']:has-text('Other'), a:has-text('Other'), span:text-is('Other')"
                    tab_locator = page.locator(selector).first
                    
                    tab_found = False
                    try:
                        # Wait up to 5 seconds for the tab to appear (X can be slow)
                        tab_locator.wait_for(state="visible", timeout=5000)
                        tab_locator.click()
                        human_pause(2.0, 4.0)
                        tab_found = True
                    except Exception:
                        st.warning(f"Could not find the '{tab_name}' tab on screen. Your account might not use tabs. Processing visible requests anyway...")
                        processed_unified_list = True
                        # Proceed to process the unified list of requests instead of skipping
                    
                    processed_users = set()
                    
                    # Find conversation list
                    # X uses data-testid="conversation" for each chat in the list
                    while True:
                        try:
                            # Wait up to 10 seconds for conversations OR the empty state to load
                            page.wait_for_selector('[data-testid^="dm-conversation-item-"], [data-testid^="dm-message-request-item-"], [data-testid="conversation"], [data-testid="dm-message-requests-empty"]', timeout=10000)
                        except: pass
                        
                        convos = page.locator('[data-testid^="dm-conversation-item-"], [data-testid^="dm-message-request-item-"], [data-testid="conversation"]')
                        if convos.count() == 0:
                            st.info(f"[{profile['id']}] No more pending conversations found in {tab_name}.")
                            break
                            
                        # Extract handles/names from visible convos
                        visible_convo_names = []
                        for idx in range(convos.count()):
                            try:
                                txt = convos.nth(idx).inner_text()
                                name = txt.split('\n')[0].strip()
                                visible_convo_names.append((idx, name))
                            except Exception: pass                       
                        
                        unprocessed_index = -1
                        current_convo_name = None
                        for i in range(convos.count()):
                            try:
                                # Get the username/text from the first line
                                name = convos.nth(i).inner_text().split('\n')[0].strip()
                            except:
                                name = f"unknown_{i}"
                            
                            if name in accepted_users_whitelist:
                                processed_users.add(name)
                                st.info(f"Skipping {name} as they are already in the main inbox (accepted).")
                                continue
                                
                            if name not in processed_users:
                                unprocessed_index = i
                                current_convo_name = name
                                break
                                
                        if unprocessed_index == -1:
                            st.write(f"No more pending conversations found in {tab_name}.")
                            break
                            
                        convo = convos.nth(unprocessed_index)
                        
                        # PRE-SCREEN: 5-Hour Window & Handled Check
                        try:
                            # 1. 5-Hour Time Check using X's <time> element
                            time_el = convo.locator('time').first
                            if time_el.count() > 0:
                                dt_str = time_el.get_attribute('datetime')
                                if dt_str:
                                    dt_str = dt_str.replace('Z', '+00:00')
                                    from datetime import datetime, timezone
                                    msg_time = datetime.fromisoformat(dt_str)
                                    now = datetime.now(timezone.utc)
                                    diff = now - msg_time
                                    if skip_older_than_hours > 0 and diff.total_seconds() > skip_older_than_hours * 3600:
                                        st.write(f"Message from {current_convo_name} is older than {skip_older_than_hours} hours. Skipping.")
                                        processed_users.add(current_convo_name)
                                        continue
                                        
                            # 2. Handled Check
                            convo_text = convo.inner_text().lower()
                            if "you accepted the request" in convo_text or "you sent" in convo_text or "you:" in convo_text:
                                st.write("Conversation shows as already handled in the list. Skipping instantly.")
                                processed_users.add(current_convo_name)
                                continue
                        except Exception as e:
                            st.write(f"Error during pre-screen check for {current_convo_name}: {e}")
                            print(f"Error during pre-screen check for {current_convo_name}: {e}")
                        convo.click()
                        human_pause(1.5, 3.0)
                        
                        # Handle hidden/suspicious content by clicking 'View' if it exists
                        try:
                            view_btn = page.get_by_role("button", name="View", exact=True).last
                            view_btn.wait_for(state="visible", timeout=1500)
                            view_btn.click()
                            st.write("Clicked 'View' to reveal hidden/suspicious message.")
                            human_pause(1.0, 2.0)
                        except Exception:
                            pass
                        
                        # Check if it's a fresh request by looking for the Accept button
                        needs_reply = False
                        
                        # NEW SAFETY CHECK: Look if we already sent our exact reply
                        try:
                            # Extract the first few words to avoid issues with X turning links into HTML cards
                            first_words = " ".join(final_reply.split()[:3])
                            if page.get_by_text(first_words).count() > 0:
                                st.write("Our automated reply is already present in this chat. Skipping to prevent double messages.")
                                processed_users.add(current_convo_name)
                                continue
                        except Exception:
                            pass
                            
                        try:
                            # Use a stricter selector for the Accept button
                            accept_btn = page.get_by_role("button", name="Accept", exact=True).last
                            # Wait 3 seconds to see if the Accept button appears
                            accept_btn.wait_for(state="visible", timeout=3000)
                            accept_btn.click()
                            human_pause(1.5, 3.0)
                            needs_reply = True
                        except:
                            pass # No Accept button means it's already accepted or not a valid request
                            
                        if not needs_reply:
                            st.write("Conversation is already accepted or missing 'Accept'. Skipping to prevent duplicate replies.")
                            processed_users.add(current_convo_name)
                            continue # Skip reply and move to the next conversation index without reloading the page
                            
                        st.write(f"Replying with: {final_reply}")
                        
                        # Focus editor and reply
                        try:
                            # Give the chat pane a few seconds to fully render
                            human_pause(1.5, 3.0)
                            
                            all_textboxes = page.locator('div[role="textbox"], textarea')
                            visible_boxes = []
                            for i in range(all_textboxes.count()):
                                box = all_textboxes.nth(i)
                                if box.is_visible():
                                    visible_boxes.append(box)
                            
                            if not visible_boxes:
                                raise Exception("No visible text input fields found on screen.")
                                
                            # The chat composer is always the lowest textbox on the screen, so we take the last visible one
                            editor = visible_boxes[-1]
                            editor.click(timeout=3000)
                            human_pause(0.5, 1.5)
                            
                            # 1 & 2. Unified String Compilation & Atomic UI Injection
                            editor.fill(final_reply)
                            human_pause(0.5, 1.0)
                            editor.press("Space")
                            editor.press("Backspace")
                            
                            # 3. Submission Synchronization
                            # Introduce explicit wait state to allow frontend event hooks to process the payload
                            human_pause(1.5, 3.0)
                            
                            # Explicitly target and click the physical 'Send' button for 100% reliability
                            try:
                                send_btn = page.locator('div[data-testid="dmComposerSendButton"], button[aria-label="Send"], div[aria-label="Send"]').last
                                send_btn.wait_for(state="visible", timeout=3000)
                                send_btn.click(timeout=3000)
                            except Exception:
                                # Fallback to Enter key if the button cannot be located
                                editor.press("Enter")
                                
                            # CRITICAL: Wait long enough for the network request to finish!
                            # If we navigate away too quickly, the browser aborts the API call.
                            human_pause(4.0, 6.0)
                            
                        except Exception as e:
                            st.warning(f"Could not find message input for this conversation: {e}")
                        
                        processed_users.add(current_convo_name)
                        
                        # Go back to requests list
                        page.goto("https://x.com/messages/requests", wait_until="domcontentloaded")
                        human_pause(3.0, 5.0)
                        
                        # Click the tab again to continue
                        try:
                            selector = f"[role='tab']:has-text('{tab_name}'), a:has-text('{tab_name}'), span:text-is('{tab_name}')"
                            if tab_name == "Hidden":
                                selector += ", button[data-testid='dm-message-requests-other-button'], [role='tab']:has-text('Other'), a:has-text('Other'), span:text-is('Other')"
                            tab_locator = page.locator(selector).first
                            tab_locator.wait_for(state="visible", timeout=5000)
                            tab_locator.click()
                            human_pause(2.0, 4.0)
                        except Exception:
                            st.warning(f"Could not re-select the '{tab_name}' tab. Moving to next.")
                            
                        # We reloaded the page, so the DOM shifted. Reset the processed list to start from the top again.
                        # processed_users.clear() # Preserved across reloads to prevent O(N^2) checking
                            
                except Exception as e:
                    st.warning(f"Finished or encountered issue in {tab_name} tab: {e}")
                    
        except Exception as e:
            st.error(f"Browser launch failed: {e}")
        finally:
            if context:
                try:
                    context.close()
                except:
                    pass

# --- Streamlit Dashboard UI Setup ---
st.set_page_config(page_title="Assistive Workspace Dashboard", layout="wide")

# Custom CSS for a professional, sleek UI
st.markdown("""
    <style>
    /* Main Background & Font */
    .stApp {
        background-color: #f8f9fa;
        font-family: 'Inter', sans-serif;
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #1e293b;
        font-weight: 600;
        letter-spacing: -0.5px;
    }
    
    /* Buttons */
    .stButton>button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s ease;
        border: none;
    }
    .stButton>button[kind="primary"] {
        background-color: #2563eb;
        color: white;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.2);
    }
    .stButton>button[kind="primary"]:hover {
        background-color: #1d4ed8;
        box-shadow: 0 6px 8px -1px rgba(37, 99, 235, 0.3);
    }
    
    /* Inputs and Text Areas */
    .stTextArea>div>div>textarea, .stTextInput>div>div>input {
        border-radius: 8px;
        border: 1px solid #e2e8f0;
        background-color: #ffffff;
        padding: 10px;
    }
    .stTextArea>div>div>textarea:focus, .stTextInput>div>div>input:focus {
        border-color: #2563eb;
        box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.2);
    }
    
    /* Dividers */
    hr {
        margin: 2rem 0;
        border-color: #e2e8f0;
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        border-bottom: 2px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        padding-top: 10px;
        padding-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["Publish Dashboard", "Manage Accounts", "Auto-Responder"])

def load_profiles():
    try:
        with open("profiles.json", "r") as f: 
            return json.load(f)
    except FileNotFoundError: 
        return []

def save_profiles(data):
    with open("profiles.json", "w") as f: 
        json.dump(data, f, indent=4)

profiles_data = load_profiles()

# TAB 1: DAILY POSTING INTERFACE
with tab1:
    st.header("Post Content Framework")
    if profiles_data:
        profile_options = {p["id"]: p for p in profiles_data}
        
        # --- FIX: New Bulk Auto-Sync Button ---
        fetch_triggered = st.button("Auto-Sync Linked Accounts", use_container_width=True)
        if fetch_triggered:
            with st.spinner("Fetching communities for all accounts in background..."):
                full_cache = {}
                if os.path.exists("communities_cache.json"):
                    try:
                        with open("communities_cache.json", "r") as f:
                            full_cache = json.load(f)
                    except:
                        pass
                
                failed_accounts = []
                # Loop through every single account automatically
                for profile_id, prof in profile_options.items():
                    comms = fetch_joined_communities(prof)
                    if comms is None:
                        failed_accounts.append(profile_id)
                    elif comms:
                        full_cache[profile_id] = comms
                        
                with open("communities_cache.json", "w") as f: 
                    json.dump(full_cache, f, indent=4)
                    
                if failed_accounts:
                    st.session_state.sync_auth_failed = failed_accounts
                else:
                    st.session_state.sync_auth_failed = []
                    st.success("All accounts synced successfully!")
                
                time.sleep(2)
                st.rerun()
                    
        if st.session_state.get("sync_auth_failed"):
            st.warning(f"Auto-sync was blocked for: {', '.join(st.session_state.sync_auth_failed)}. Please use Manual Sync below.")
            
        st.divider()
        st.subheader("Manual Account Sync (Fallback)")
        selected_id = st.selectbox("Select Profile Handle for Manual Sync", options=list(profile_options.keys()))
        current_profile = profile_options[selected_id]
        
        manual_sync = st.button(f"👁️ Manual Sync via Visible Browser [{current_profile['id']}]")
        if manual_sync:
            with st.spinner(f"Opening browser for {current_profile['id']}... Please resolve the login/captcha, then wait for 60 seconds."):
                comms = fetch_joined_communities_manual(current_profile)
                if comms:
                    full_cache = {}
                    if os.path.exists("communities_cache.json"):
                        try:
                            with open("communities_cache.json", "r") as f:
                                full_cache = json.load(f)
                        except:
                            pass
                    full_cache[current_profile["id"]] = comms
                    with open("communities_cache.json", "w") as f: 
                        json.dump(full_cache, f, indent=4)
                    st.success(f"Manual sync successful for {current_profile['id']}! Loaded {len(comms)} targets.")
                    
                    if isinstance(st.session_state.get("sync_auth_failed"), list) and current_profile["id"] in st.session_state.sync_auth_failed:
                        st.session_state.sync_auth_failed.remove(current_profile["id"])
                        
                    time.sleep(2)
                    st.rerun()
                            
        # --- PHASE 1 & 2: MASTER CACHE & DYNAMIC UI ---
        communities_cache = {}
        if os.path.exists("communities_cache.json"):
            try:
                with open("communities_cache.json", "r") as f: 
                    communities_cache = json.load(f)
            except:
                pass
        
        if "drafted_messages" not in st.session_state:
            st.session_state.drafted_messages = {}
        if "drafted_comments" not in st.session_state:
            st.session_state.drafted_comments = {}
        if "pool_selections" not in st.session_state:
            st.session_state.pool_selections = {}

        if not communities_cache:
            st.info("No communities synced yet. Please run the Sync tool to build your interface.")
        else:
            st.divider()
            st.subheader("Account-Specific Content Router")
            st.write("For each account, draft your message and select communities. The system will randomly pick 2 of your selected communities to post to.")
            
            with st.expander("🤖 Auto-fill from JSON"):
                st.write("Paste a JSON object to instantly fill the message and comment boxes for your accounts.")
                st.code('''{
  "account 1": {
    "message": "My main post text",
    "comments": "Comment 1---Comment 2"
  }
}''', language="json")
                autofill_json = st.text_area("Auto-fill JSON Content", height=150, key="autofill_input")
                if st.button("Apply Auto-fill"):
                    if autofill_json.strip():
                        try:
                            import json
                            import re
                            try:
                                parsed_fill = json.loads(autofill_json)
                            except json.JSONDecodeError:
                                # Fallback: User pasted multiple { } objects instead of one big object
                                fixed_json = "[" + re.sub(r'}\s*\{', '},{', autofill_json.strip()) + "]"
                                parsed_list = json.loads(fixed_json)
                                parsed_fill = {}
                                for item in parsed_list:
                                    parsed_fill.update(item)
                                    
                            for acct, data in parsed_fill.items():
                                if "message" in data:
                                    st.session_state.drafted_messages[acct] = data["message"]
                                    st.session_state[f"input_{acct}"] = data["message"]
                                if "comments" in data:
                                    st.session_state.drafted_comments[acct] = data["comments"]
                                    st.session_state[f"comment_{acct}"] = data["comments"]
                            st.success("Successfully applied Auto-fill!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Invalid JSON format. Make sure it's a valid JSON object. Error: {e}")

            st.divider()
            st.subheader("Filter Accounts")
            selected_publish_accounts = st.multiselect(
                "Select accounts to display and post to (leave empty to show all):",
                options=list(communities_cache.keys()),
                default=[]
            )

            uploaded_images = {}
            for p_id, profile_comms in communities_cache.items():
                if selected_publish_accounts and p_id not in selected_publish_accounts:
                    continue
                st.markdown(f"### Account: {p_id}")
                
                if profile_comms and isinstance(list(profile_comms.values())[0], dict):
                    sorted_comms = dict(sorted(profile_comms.items(), key=lambda item: item[1].get("members", 0), reverse=True))
                else:
                    sorted_comms = profile_comms
                
                comm_names = list(sorted_comms.keys())
                default_selections = comm_names[:min(5, len(comm_names))]
                
                st.session_state.pool_selections[p_id] = st.multiselect(
                    f"Select community pool for {p_id} (will randomly post to 2):",
                    options=comm_names,
                    default=default_selections,
                    key=f"pool_{p_id}"
                )
                
                if f"input_{p_id}" not in st.session_state:
                    st.session_state[f"input_{p_id}"] = st.session_state.drafted_messages.get(p_id, "")
                
                st.session_state.drafted_messages[p_id] = st.text_area(
                    f"Message for {p_id}:", 
                    max_chars=280,
                    key=f"input_{p_id}"
                )
                
                if f"comment_{p_id}" not in st.session_state:
                    st.session_state[f"comment_{p_id}"] = st.session_state.drafted_comments.get(p_id, "")
                    
                st.session_state.drafted_comments[p_id] = st.text_area(
                    f"Comments to add in {p_id} (Separate multiple comments with '---'):", 
                    height=100,
                    key=f"comment_{p_id}"
                )
                
                uploaded_images[p_id] = st.file_uploader(
                    f"Upload Image for {p_id} (Optional)", 
                    type=["jpg", "jpeg", "png"], 
                    key=f"img_{p_id}"
                )
                st.divider()
                
            def reshuffle_callback():
                pass

            st.divider()
            st.subheader("Bulk Image Upload (Optional)")
            st.write("Upload multiple images here. Accounts that don't have a specific image assigned will randomly receive one of these images!")
            bulk_images = st.file_uploader("Upload Bulk Images", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="bulk_images_uploader")
            
            if "bulk_image_assignments" not in st.session_state:
                st.session_state.bulk_image_assignments = {}
            
            if bulk_images:
                col_btn1, col_btn2 = st.columns([0.5, 0.5])
                with col_btn1:
                    apply_btn = st.button("Apply Image Distribution", use_container_width=True)
                with col_btn2:
                    clear_btn = st.button("Clear Distribution", use_container_width=True)
                
                if clear_btn:
                    st.session_state.bulk_image_assignments = {}
                    st.success("Cleared all image auto-fills.")
                elif apply_btn:
                    import random
                    assignments = {}
                    for p_id in communities_cache.keys():
                        if not uploaded_images.get(p_id):
                            img = random.choice(bulk_images)
                            assignments[p_id] = img
                    st.session_state.bulk_image_assignments = assignments
                    st.success(f"Successfully distributed images across {len(assignments)} accounts!")
                
                for acct, img in st.session_state.bulk_image_assignments.items():
                    if not uploaded_images.get(acct) and img in bulk_images:
                        uploaded_images[acct] = img
                        
                if st.session_state.bulk_image_assignments:
                    with st.expander("View Image Distribution Map"):
                        for acct, img in st.session_state.bulk_image_assignments.items():
                            if img in bulk_images:
                                st.text(f"✅ {acct} -> {img.name}")
            else:
                st.session_state.bulk_image_assignments = {}

            st.divider()
            st.subheader("Bulk JSON Upload (Optional)")
            st.write("Paste a JSON list of messages (e.g. `[\"Post 1\", \"Post 2\"]`). If provided, the bot will randomly pick from this list instead of using the individual boxes above, ensuring every post gets a unique text!")
            
            bulk_json_input = st.text_area("Bulk JSON List", value="", height=150, help='Must be a valid JSON array like: ["Hello!", "Hi there!"]')
            bulk_json_drafts = []
            if bulk_json_input.strip():
                try:
                    import json
                    parsed_json = json.loads(bulk_json_input)
                    if isinstance(parsed_json, list) and len(parsed_json) > 0:
                        bulk_json_drafts = parsed_json
                        st.success(f"Successfully loaded {len(bulk_json_drafts)} unique drafts from JSON.")
                    else:
                        st.warning("JSON must be a list of strings.")
                except Exception as e:
                    st.error(f"Invalid JSON format. Make sure it looks like `[\"Text 1\", \"Text 2\"]`. Error: {e}")

            st.divider()
            st.subheader("Execution Settings")
            import datetime
            
            col_set1, col_set2 = st.columns(2)
            with col_set1:
                schedule_date = st.date_input("Schedule Date", value="today")
            with col_set2:
                schedule_time = st.time_input("Schedule Time", value="now")
            
            publish_triggered = st.button("Execute Publish Sequence", type="primary", use_container_width=True)
            
            st.divider()
            st.subheader("Scheduled Queue")
            
            queue_data = []
            if os.path.exists("scheduled_queue.json"):
                try:
                    with open("scheduled_queue.json", "r") as f:
                        queue_data = json.load(f)
                except:
                    pass
            
            if queue_data:
                for idx, job in enumerate(queue_data):
                    col_q1, col_q2 = st.columns([0.8, 0.2])
                    col_q1.write(f"**Job {idx+1}**: Scheduled for {job['scheduled_datetime']} ({len(job['active_drafts'])} posts)")
                    if col_q2.button(f"Cancel Job {idx+1}", key=f"del_job_{job['id']}"):
                        queue_data = [j for j in queue_data if j['id'] != job['id']]
                        with open("scheduled_queue.json", "w") as f:
                            json.dump(queue_data, f, indent=4)
                        st.rerun()
            else:
                st.info("No upcoming scheduled posts.")
            
            # --- PHASE 3: SEQUENTIAL EXECUTION (Index-Based Distribution) ---
            if publish_triggered:
                # Capture state for all accounts
                all_keys = list(communities_cache.keys())
                active_drafts = {k: st.session_state.drafted_messages.get(k, "") for k in all_keys if st.session_state.drafted_messages.get(k, "").strip() or uploaded_images.get(k) is not None}
                active_comments = {k: st.session_state.drafted_comments.get(k, "") for k in all_keys}
                pool_selections = {k: st.session_state.pool_selections.get(k, []) for k in all_keys}
                
                if not active_drafts and not bulk_json_drafts:
                    st.warning("Please draft at least one message or provide a Bulk JSON list before executing.")
                else:
                    scheduled_datetime = datetime.datetime.combine(schedule_date, schedule_time)
                    now = datetime.datetime.now()
                    
                    if scheduled_datetime > now:
                        job_id = str(int(time.time()))
                        
                        # Save images permanently for the background worker
                        uploaded_images_paths = {}
                        os.makedirs("scheduled_uploads", exist_ok=True)
                        for p_id, comm_img in uploaded_images.items():
                            if comm_img:
                                safe_pid = "".join([c for c in p_id if c.isalnum()]).rstrip()
                                img_path = os.path.join("scheduled_uploads", f"{job_id}_{safe_pid}_{comm_img.name}")
                                with open(img_path, "wb") as f: 
                                    f.write(comm_img.getbuffer())
                                uploaded_images_paths[p_id] = img_path
                                
                        new_job = {
                            "id": job_id,
                            "scheduled_datetime": scheduled_datetime.isoformat(),
                            "active_drafts": active_drafts,
                            "active_comments": active_comments,
                            "pool_selections": pool_selections,
                            "bulk_json_drafts": bulk_json_drafts,
                            "uploaded_images": uploaded_images_paths
                        }
                        
                        queue_data.append(new_job)
                        with open("scheduled_queue.json", "w") as f:
                            json.dump(queue_data, f, indent=4)
                            
                        st.success(f"Post sequence queued for {scheduled_datetime.strftime('%Y-%m-%d %H:%M:%S')}.")
                        st.info("Please make sure the background worker is running. (Run `./start_worker.sh` in your terminal)")
                        
                        time.sleep(2)
                        st.rerun()
                        
                    else:
                        st.divider()
                        st.subheader("Execution Log")
                        
                        # Get accounts to post to (must have drafts and selected pool)
                        keys_to_process = list(active_drafts.keys()) + (list(communities_cache.keys()) if bulk_json_drafts else [])
                        unique_keys = []
                        for k in keys_to_process:
                            if k not in unique_keys:
                                unique_keys.append(k)
                                
                        for p_id in unique_keys:
                            if p_id not in active_drafts and not bulk_json_drafts: continue
                            
                            st.markdown(f"### Initiating Profile: {p_id}")
                            prof_data = next((p for p in profiles_data if p["id"] == p_id), None)
                            if not prof_data: continue
                            
                            pool = pool_selections.get(p_id, [])
                            if not pool:
                                st.warning(f"No communities selected for {p_id}.")
                                continue
                                
                            to_post = random.sample(pool, min(2, len(pool)))
                            profile_comms = communities_cache.get(p_id, {})
                            
                            drafted_text = active_drafts.get(p_id, "")
                            comment_text = active_comments.get(p_id, "")
                            comm_img = uploaded_images.get(p_id)
                            
                            for i, comm_name in enumerate(to_post):
                                target_url = profile_comms.get(comm_name, {}).get("url") if isinstance(profile_comms.get(comm_name), dict) else profile_comms.get(comm_name)
                                if not target_url or "suggested" in target_url:
                                    continue
                                
                                if bulk_json_drafts:
                                    drafted_text = random.choice(bulk_json_drafts)
                                
                                st.write(f"Posting to '{comm_name}' (Random Selection #{i+1})...")
                                temp_file_path = None
                                if comm_img:
                                    os.makedirs("temp_uploads", exist_ok=True)
                                    safe_pid = "".join([c for c in p_id if c.isalnum()]).rstrip()
                                    temp_file_path = os.path.join("temp_uploads", f"{safe_pid}_{comm_img.name}")
                                    with open(temp_file_path, "wb") as f: 
                                        f.write(comm_img.getbuffer())
                                
                                success = process_profile(prof_data, drafted_text, temp_file_path, target_url, comment_text)
                                if success:
                                    record_community_post(p_id, target_url)
                                else:
                                    st.warning(f"Post failed for '{comm_name}', skipping record.")
                                
                                if temp_file_path and os.path.exists(temp_file_path): 
                                    os.remove(temp_file_path)
                                
                                wait_time = random.randint(15, 30)
                                p_bar = st.progress(0)
                                for secs in range(wait_time):
                                    time.sleep(random.uniform(0.8, 1.5))
                                    p_bar.progress((secs + 1) / wait_time, text=f"⏳ Pacing: Waiting {wait_time - secs}s before next post...")
                                    
                        st.success("Random Publish Complete.")
    else:
        st.info("Configure a user record target inside the 'Manage Accounts' tab first.")

# TAB 2: ACCOUNT CONFIGURATION ADMIN
with tab2:
    st.header("Account Profile Configuration Database")
    action = st.radio("Database Action", ["Edit Existing Profile", "➕ Add New Profile"])
    
    current_user_data_dir = ""
    current_p_id = ""
    
    # --- FIX: Move selection outside the form so it triggers an immediate UI update ---
    target_prof = {}
    edit_id = None
    if action == "Edit Existing Profile" and profiles_data:
        profile_ids = [p["id"] for p in profiles_data]
        edit_id = st.selectbox("Select Profile ID to Modify", options=profile_ids)
        target_prof = next((p for p in profiles_data if p["id"] == edit_id), {})

    with st.form("profile_management_form"):
        if action == "Edit Existing Profile" and profiles_data:
            p_id = edit_id
            username = st.text_input("Username/Email Address Handle", value=target_prof.get("username", ""))
            auth_token = st.text_input("X Auth Token (Cookie)", value=target_prof.get("auth_token", ""), type="password", help="Paste the 'auth_token' cookie from your browser.")
            proxy_url = st.text_input("Residential Proxy URL (Optional)", value=target_prof.get("proxy_url", ""), help="e.g. http://user:pass@proxy:8000")
            
            current_p_id = p_id
        else:
            p_id = st.text_input("Create Unique Profile ID (e.g. tech_handle)")
            username = st.text_input("Username/Email Address Handle")
            auth_token = st.text_input("X Auth Token (Cookie)", type="password", help="Paste the 'auth_token' cookie from your browser.")
            proxy_url = st.text_input("Residential Proxy URL (Optional)", help="e.g. http://user:pass@proxy:8000")
            
            current_p_id = p_id
            
        submit_save = st.form_submit_button("💾 Save Profile Configuration")
        # Add inside the form, below the submit button
        col1, col2 = st.columns(2)
        with col1:
            delete_btn = st.form_submit_button("🗑️ Delete Selected Profile")
        with col2:
            delete_all_btn = st.form_submit_button("⚠️ Delete ALL Profiles", type="primary")
        
        if submit_save:
            if not p_id or not username or not auth_token:
                st.error("Profile ID, Username, and Auth Token are required.")
            else:
                new_entry = {
                    "id": p_id, 
                    "username": username, 
                    "auth_token": auth_token, 
                    "proxy_url": proxy_url,
                    "user_data_dir": f"./user_data/{p_id}" # Keep for internal caching if needed
                }
                updated_profiles = [p for p in profiles_data if p["id"] != p_id]
                updated_profiles.append(new_entry)
                save_profiles(updated_profiles)
                st.success("Profile attributes committed successfully!")
                time.sleep(0.5)
                st.rerun()
        elif delete_btn and edit_id:
            updated_profiles = [p for p in profiles_data if p["id"] != edit_id]
            save_profiles(updated_profiles)
            
            try:
                if os.path.exists("communities_cache.json"):
                    with open("communities_cache.json", "r") as f:
                        cache = json.load(f)
                    if edit_id in cache:
                        del cache[edit_id]
                        with open("communities_cache.json", "w") as f:
                            json.dump(cache, f, indent=4)
                import shutil
                profile_dir = f"./user_data/{edit_id}"
                if os.path.exists(profile_dir):
                    shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception as e:
                st.warning(f"Profile deleted, but cache cleanup failed: {e}")
                
            st.warning(f"Profile {edit_id} deleted successfully.")
            time.sleep(random.uniform(0.8, 1.5))
            st.rerun()
        elif delete_all_btn:
            save_profiles([])
            
            try:
                if os.path.exists("communities_cache.json"):
                    os.remove("communities_cache.json")
                import shutil
                if os.path.exists("./user_data"):
                    shutil.rmtree("./user_data", ignore_errors=True)
            except Exception as e:
                pass
                
            st.error("All profiles have been permanently deleted.")
            time.sleep(random.uniform(0.8, 1.5))
            st.rerun()

# TAB 3: AUTO-RESPONDER
with tab3:
    st.header("💬 Automated Message Responder")
    st.write("Automatically reply to messages in your **Priority** and **Other (Hidden)** message tabs on X.")
    
    if not profiles_data:
        st.info("Configure a user record target inside the 'Manage Accounts' tab first.")
    else:
        run_all = st.checkbox("Run for ALL Profiles", value=False)
        
        profile_options = {p["id"]: p for p in profiles_data}
        if not run_all:
            selected_responder_ids = st.multiselect("Select Profiles for Auto-Responder", options=list(profile_options.keys()), key="responder_profile_select", default=list(profile_options.keys()))
        
        chat_password = st.text_input("Chat Unlock Password", value="2004", type="password", help="The password to unlock your chats when opening X messages for the first time.")
        universal_message = st.text_area("Universal Reply Message", value="Message received.", height=100)
        
        col_chk1, col_chk2 = st.columns(2)
        with col_chk1:
            process_priority = st.checkbox("Check 'Priority' tab", value=True)
        with col_chk2:
            process_hidden = st.checkbox("Check 'Other' (Hidden) tab", value=True)
            
        skip_older_than_hours = st.number_input("Skip messages older than (hours)", min_value=0.0, value=2.0, step=0.5, help="Messages older than this will be skipped automatically. Set to 0 to process all.")
        
        if st.button("Start Auto-Responder Sequence", type="primary", use_container_width=True):
            if not process_priority and not process_hidden:
                st.warning("Please select at least one tab to check (Priority or Other).")
            else:
                profiles_to_run = profiles_data if run_all else [profile_options[pid] for pid in selected_responder_ids]
                
                with st.spinner(f"Running auto-responder for {len(profiles_to_run)} profile(s)... This will open a visible browser."):
                    for prof in profiles_to_run:
                        st.write(f"Processing profile: {prof['id']}...")
                        process_auto_responder(
                            profile=prof, 
                            universal_msg=universal_message, 
                            check_priority=process_priority, 
                            check_hidden=process_hidden,
                            unlock_password=chat_password,
                            skip_older_than_hours=skip_older_than_hours
                        )
                    st.success("Auto-responder sequence complete.")
        
        st.divider()
        st.subheader("Background Scheduling")
        st.write("Schedule the auto-responder to check automatically in the background using the background worker.")
        
        col_sch1, col_sch2 = st.columns(2)
        with col_sch1:
            check_interval = st.number_input("Check Interval (minutes)", min_value=1, value=60)
        with col_sch2:
            max_checks = st.number_input("Max Checks (0 = Infinite)", min_value=0, value=0)
            
        if st.button("Schedule in Background", type="secondary", use_container_width=True):
            if not process_priority and not process_hidden:
                st.warning("Please select at least one tab to check (Priority or Other).")
            else:
                config = {
                    "interval_minutes": check_interval,
                    "max_checks": max_checks,
                    "run_all": run_all,
                    "selected_profiles": selected_responder_ids if not run_all else [],
                    "universal_msg": universal_message,
                    "check_priority": process_priority,
                    "check_hidden": process_hidden,
                    "unlock_password": chat_password,
                    "skip_older_than_hours": skip_older_than_hours,
                    "checks_completed": 0,
                    "last_checked_iso": None,
                    "is_active": True
                }
                with open("auto_responder_config.json", "w") as f:
                    json.dump(config, f, indent=4)
                st.success(f"Background Auto-Responder Scheduled. (Interval: {check_interval}m)")
                st.info("Make sure `./start_worker.sh` is running.")
                time.sleep(2)
                st.rerun()

        if os.path.exists("auto_responder_config.json"):
            try:
                with open("auto_responder_config.json", "r") as f:
                    cfg = json.load(f)
                if cfg.get("is_active"):
                    st.success(f"Currently active in background! Checked {cfg.get('checks_completed', 0)} times.")
                    if st.button("🛑 Stop Background Auto-Responder", type="primary"):
                        cfg["is_active"] = False
                        with open("auto_responder_config.json", "w") as f:
                            json.dump(cfg, f, indent=4)
                        st.rerun()
            except:
                pass