import json
import os
import subprocess
import sys

def load_profiles():
    try:
        with open("profiles.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("profiles.json not found!")
        sys.exit(1)

def main():
    profiles = load_profiles()
    
    print("Select an account to manually log in to:")
    for i, profile in enumerate(profiles):
        print(f"[{i + 1}] {profile.get('id', 'Unknown')} ({profile.get('username', 'No email')})")
        
    try:
        choice = input("\nEnter the number of the account (or 'q' to quit): ")
        if choice.lower() == 'q':
            sys.exit(0)
            
        index = int(choice) - 1
        if index < 0 or index >= len(profiles):
            print("Invalid choice.")
            sys.exit(1)
            
        selected = profiles[index]
        user_data_dir = selected.get("user_data_dir")
        
        if not user_data_dir:
            print("No user_data_dir found for this profile.")
            sys.exit(1)
            
        # Ensure it's an absolute path to avoid issues
        abs_user_data_dir = os.path.abspath(user_data_dir)
        
        print(f"\nLaunching regular Chrome for {selected['id']}...")
        print("Log in normally. The phone prompt should work since Playwright isn't interfering.")
        print("When you are done logging in, completely close the Chrome window.")
        
        # Launch real Chrome without Playwright flags
        subprocess.run([
            "/usr/bin/google-chrome-stable",
            f"--user-data-dir={abs_user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check"
        ])
        
        print("\nChrome closed. You can now use this profile with your Playwright app.")
        
    except ValueError:
        print("Invalid input.")
    except KeyboardInterrupt:
        print("\nExiting.")

if __name__ == "__main__":
    main()
