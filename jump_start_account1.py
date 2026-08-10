import json
from background_worker import process_profile

def jump_start():
    print("Loading data...")
    with open("profiles.json", "r") as f:
        profiles = json.load(f)
        
    with open("scheduled_queue.json", "r") as f:
        queue = json.load(f)
        
    job = queue[0]
    p_id = "account1"
    
    prof_data = next((p for p in profiles if p["id"] == p_id), None)
    if not prof_data:
        print(f"Profile {p_id} not found.")
        return
        
    drafted_text = job["active_drafts"].get(p_id, "")
    comment_text = job["active_comments"].get(p_id, "")
    
    with open("communities_cache.json", "r") as f:
        communities_cache = json.load(f)
        
    comm_name = job["pool_selections"][p_id][0]
    target_url = communities_cache[p_id][comm_name]
    if isinstance(target_url, dict):
        target_url = target_url.get("url")
        
    print(f"Jumping starting {p_id} to post to {comm_name}...")
    success = process_profile(prof_data, drafted_text, None, target_url, comment_text)
    if success:
        print("Successfully posted!")
    else:
        print("Failed to post.")

if __name__ == "__main__":
    jump_start()
