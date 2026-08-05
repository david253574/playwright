import sys
from bs4 import BeautifulSoup

with open('sync_debug_source.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f, 'html.parser')

links = soup.select('a[href*="/i/communities/"]:not([href*="/hashtag/"]):not([href="/i/communities/discover"]):not([href="/i/communities/create"])')
for a in links:
    if a.parent:
        print("---")
        print("HREF:", a.get('href'))
        print("PARENT TEXT:", repr(a.parent.get_text(separator=' | ', strip=True)))
