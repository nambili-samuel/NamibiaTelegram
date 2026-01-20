#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import feedparser
import requests
from io import BytesIO
from PIL import Image
import re
from datetime import datetime
from bs4 import BeautifulSoup
import json
import time

# Force UTF-8 encoding for stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

RSS_URL = os.environ.get("RSS_URL")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Track ALL posted links, not just the last one
STATE_FILE = "posted_links.json"
MAX_IMAGE_SIZE = 10_000_000  # 10MB (Telegram limit)
# How many RSS entries to check each run (to avoid spamming)
MAX_ENTRIES_TO_PROCESS = 10
# Minimum time between posts to avoid rate limits (seconds)
POST_DELAY = 2

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def load_posted_links():
    """Load all previously posted article links"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Backward compatibility: if it's a string (old format), convert to dict
                if isinstance(data, str):
                    return {data: datetime.now().isoformat()}
                return data
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_posted_links(links_dict):
    """Save all posted article links with timestamps"""
    # Keep only the last 1000 entries to prevent file from growing too large
    if len(links_dict) > 1000:
        # Sort by timestamp and keep most recent
        sorted_items = sorted(links_dict.items(), key=lambda x: x[1], reverse=True)
        links_dict = dict(sorted_items[:1000])
    
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(links_dict, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(links_dict)} links saved")

def mark_as_posted(link):
    """Mark a link as posted with current timestamp"""
    posted_links = load_posted_links()
    posted_links[link] = datetime.now().isoformat()
    save_posted_links(posted_links)
    print(f"✅ Link marked: {link[:50]}...")

def optimize_image(image_data):
    """Optimize image to fit within size limit while maintaining quality"""
    try:
        img = Image.open(BytesIO(image_data))
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
            img = background
        
        # Resize if too large (maintain aspect ratio)
        max_dimension = 2000
        if max(img.size) > max_dimension:
            ratio = max_dimension / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save with progressive optimization
        output = BytesIO()
        quality = 85
        
        while quality > 20:
            output.seek(0)
            output.truncate()
            img.save(output, format='JPEG', quality=quality, optimize=True, progressive=True)
            
            if output.tell() <= MAX_IMAGE_SIZE:
                print(f"✅ Image optimized: {len(image_data)} -> {output.tell()} bytes (quality: {quality})")
                return output.getvalue()
            
            quality -= 5
        
        print("⚠ Image could not be optimized, size limit exceeded")
        return None
        
    except Exception as e:
        print(f"❌ Image optimization error: {e}")
        return None

def fetch_image(url):
    """Fetch and optimize image from URL"""
    if not url:
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        print(f"📥 Downloading image: {url}")
        r = requests.get(url, timeout=15, headers=headers, stream=True)
        r.raise_for_status()
        
        content = r.content
        print(f"✅ Image downloaded: {len(content)} bytes")
        
        # If image is already small enough, return it
        if len(content) <= MAX_IMAGE_SIZE:
            return content
        
        # Otherwise, optimize it
        return optimize_image(content)
        
    except Exception as e:
        print(f"❌ Image download error ({url}): {e}")
        return None

def clean_html(text):
    """Remove HTML tags and clean text"""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&#8217;', "'")
    text = text.replace('&#8220;', '"')
    text = text.replace('&#8221;', '"')
    text = text.replace('&#8216;', "'")
    text = text.replace('&quot;', '"')
    text = text.replace('&apos;', "'")
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    # Remove CDATA markers
    text = text.replace('<![CDATA[', '')
    text = text.replace(']]>', '')
    return text.strip()

def fetch_article_thumbnail(article_url):
    """Fetch featured image from article page"""
    if not article_url or article_url == '#':
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        print(f"🌐 Opening article page: {article_url}")
        response = requests.get(article_url, timeout=15, headers=headers)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            print(f"⚠ Article page failed to load: HTTP {response.status_code}")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Method 1: Open Graph image (most reliable for WordPress)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            url = og_image['content']
            print(f"✅ Thumbnail found (og:image): {url}")
            return url
        
        # Method 2: Twitter card image
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            url = twitter_image['content']
            print(f"✅ Thumbnail found (twitter:image): {url}")
            return url
        
        # Method 3: WordPress featured image
        featured_img = soup.select_one('.wp-post-image, .featured-image img, article img, .entry-content img')
        if featured_img and featured_img.get('src'):
            url = featured_img['src']
            # Skip tiny images
            if 'placeholder' not in url.lower() and '1x1' not in url.lower():
                print(f"✅ Thumbnail found (featured image): {url}")
                return url
        
        # Method 4: First large image in content
        content_images = soup.select('article img, .entry-content img, .post-content img')
        for img in content_images:
            src = img.get('src') or img.get('data-src')
            if src and 'placeholder' not in src.lower() and '1x1' not in src.lower():
                # Check if image has reasonable dimensions
                width = img.get('width', '0')
                height = img.get('height', '0')
                try:
                    if int(width) >= 300 or int(height) >= 300:
                        print(f"✅ Thumbnail found (content image): {src}")
                        return src
                except:
                    print(f"✅ Thumbnail found (content image): {src}")
                    return src
        
        print("⚠ No thumbnail found on article page")
        return None
        
    except Exception as e:
        print(f"❌ Article page reading error: {e}")
        return None

def extract_youtube_thumbnail(entry, link):
    """Extract high-quality thumbnail from YouTube"""
    video_id = None
    
    # Try to get video ID from entry
    if hasattr(entry, 'yt_videoid'):
        video_id = entry.yt_videoid
    elif hasattr(entry, 'id'):
        # YouTube RSS sometimes has video ID in the id field
        id_str = str(entry.id)
        if 'yt:video:' in id_str:
            video_id = id_str.split('yt:video:')[-1]
    
    # Extract from link if not found
    if not video_id and 'v=' in link:
        video_id = link.split('v=')[1].split('&')[0]
    
    if video_id:
        print(f"✅ YouTube video ID: {video_id}")
        
        # Try different quality thumbnails in order of preference
        thumbnail_urls = [
            f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
            f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        ]
        
        for url in thumbnail_urls:
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                r = requests.head(url, timeout=5, headers=headers, allow_redirects=True)
                if r.status_code == 200:
                    print(f"✅ YouTube thumbnail found: {url}")
                    return url
            except:
                continue
    
    # Fallback to media_thumbnail
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get('url')
        if url:
            print(f"✅ YouTube media_thumbnail found: {url}")
            return url
    
    print("⚠ YouTube thumbnail not found")
    return None

def create_beautiful_post(title, link, category="", summary=""):
    """Create a beautiful, professional Telegram post with proper formatting for Namibian news"""
    
    # Decode HTML entities in title
    title = clean_html(title)
    summary = clean_html(summary)
    
    # Add appropriate emoji based on category
    category_emojis = {
        'SPORTS': '⚽',
        'SPORT': '⚽',
        'FOOTBALL': '⚽',
        'RUGBY': '🏉',
        'CRICKET': '🏏',
        'BUSINESS': '💼',
        'ECONOMY': '💰',
        'FINANCE': '💵',
        'POLITICS': '🏛️',
        'ELECTION': '🗳️',
        'GOVERNMENT': '🏛️',
        'HEALTH': '🏥',
        'EDUCATION': '📚',
        'TECHNOLOGY': '💻',
        'SCIENCE': '🔬',
        'ENTERTAINMENT': '🎭',
        'CULTURE': '🎨',
        'JOBS': '💼',
        'EMPLOYMENT': '👔',
        'CAREER': '📊',
        'NEWS': '📰',
        'BREAKING': '🚨',
        'LATEST': '🆕',
        'WEATHER': '🌤️',
        'CRIME': '🚔',
        'JUSTICE': '⚖️',
    }
    
    # Try to find matching category
    emoji = '📰'  # Default
    for cat_key, cat_emoji in category_emojis.items():
        if cat_key in category.upper():
            emoji = cat_emoji
            break
    
    # Create post with beautiful formatting using Telegram HTML
    # Namibia flag emoji
    namibia_flag = '🇳🇦'
    
    post_text = f"<b>{namibia_flag} {emoji} Namibia News</b>\n\n"
    post_text += f"<b>{title}</b>\n\n"
    
    # Add intro/summary if available
    if summary:
        # Limit summary to 200 characters
        if len(summary) > 200:
            summary = summary[:197] + "..."
        post_text += f"<i>{summary}</i>\n\n"
    
    if category:
        post_text += f"📂 <i>{category}</i>\n\n"
    
    post_text += f"🔗 <a href='{link}'>Read full article</a>"
    
    return post_text

def send_telegram_message(text, image_data=None):
    """Send message to Telegram with optional image"""
    try:
        if image_data:
            # Send photo with caption
            files = {
                'photo': ('image.jpg', BytesIO(image_data), 'image/jpeg')
            }
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': text,
                'parse_mode': 'HTML'
            }
            response = requests.post(
                f"{TELEGRAM_API_URL}/sendPhoto",
                data=data,
                files=files,
                timeout=30
            )
        else:
            # Send text only
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            response = requests.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                data=data,
                timeout=30
            )
        
        response.raise_for_status()
        result = response.json()
        
        if result.get('ok'):
            return True
        else:
            print(f"❌ Telegram API hatası: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Telegram gönderim hatası: {e}")
        return False

def post_to_telegram(entry):
    """Post a single entry to Telegram"""
    title = clean_html(entry.title)
    link = entry.link
    summary = clean_html(entry.get("summary", entry.get("description", "")))
    
    # Extract category
    categories = []
    if hasattr(entry, 'tags'):
        categories = [tag.term for tag in entry.tags]
    category = categories[0] if categories else "General"
    
    print(f"\n{'='*60}")
    print(f"📌 Processing: {title[:80]}...")
    print(f"   Category: {category}")
    print(f"   Link: {link}")
    print(f"{'='*60}")
    
    # Detect source type and extract thumbnail
    is_youtube = 'youtube.com' in RSS_URL.lower() or 'youtu.be' in RSS_URL.lower()
    is_google_news = 'news.google.com' in RSS_URL.lower()
    
    thumbnail_url = None
    
    if is_youtube:
        thumbnail_url = extract_youtube_thumbnail(entry, link)
    elif is_google_news:
        # For Google News, try media_content first
        if hasattr(entry, 'media_content') and entry.media_content:
            media_url = entry.media_content[0].get('url')
            if media_url:
                print(f"✅ Google News media_content found: {media_url}")
                thumbnail_url = media_url
        # Then try enclosures
        elif hasattr(entry, 'enclosures') and entry.enclosures:
            enclosure_url = entry.enclosures[0].get('url') or entry.enclosures[0].get('href')
            if enclosure_url:
                print(f"✅ Google News enclosure found: {enclosure_url}")
                thumbnail_url = enclosure_url
    else:
        # For other feeds, try RSS enclosure first, then fetch from article page
        if hasattr(entry, 'enclosures') and entry.enclosures:
            enclosure_url = entry.enclosures[0].get('url') or entry.enclosures[0].get('href')
            if enclosure_url:
                print(f"✅ RSS enclosure found: {enclosure_url}")
                thumbnail_url = enclosure_url
        
        # Try media_content
        if not thumbnail_url and hasattr(entry, 'media_content') and entry.media_content:
            media_url = entry.media_content[0].get('url')
            if media_url:
                print(f"✅ RSS media_content found: {media_url}")
                thumbnail_url = media_url
        
        # If no enclosure, fetch from article page
        if not thumbnail_url:
            thumbnail_url = fetch_article_thumbnail(link)
    
    # Fetch thumbnail image
    image_data = None
    if thumbnail_url:
        print(f"📸 Processing thumbnail...")
        image_data = fetch_image(thumbnail_url)
        
        if image_data:
            print(f"✅ Thumbnail ready")
        else:
            print(f"⚠ Thumbnail could not be downloaded, continuing...")
    else:
        print(f"⚠ Thumbnail not found, continuing...")
    
    # Create beautiful post text
    post_text = create_beautiful_post(title, link, category, summary)
    
    # Post to Telegram
    print(f"\n📤 Sending to Telegram...")
    
    success = send_telegram_message(post_text, image_data)
    
    if success:
        mark_as_posted(link)
        
        print(f"\n✅ SUCCESSFULLY POSTED!")
        print(f"📌 Title: {title}")
        print(f"📂 Category: {category}")
        print(f"🔗 Link: {link}")
        print(f"🖼️ Thumbnail: {'Yes ✔' if image_data else 'No ✗'}")
        print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
    else:
        print(f"\n❌ POSTING FAILED!")
        return False

# Parse RSS feed with UTF-8 support
print(f"\n{'='*60}")
print(f"📰 Processing RSS Feed: {RSS_URL}")
print(f"{'='*60}\n")

feed = feedparser.parse(RSS_URL)

if not feed.entries:
    print("⚠ No content found in RSS feed.")
    sys.exit(0)

print(f"✅ RSS feed loaded: {len(feed.entries)} items found\n")

# Load previously posted links
posted_links = load_posted_links()
print(f"📊 Previously posted links: {len(posted_links)}")

# Test Telegram connection
print(f"\n🔐 Testing Telegram connection...")
try:
    response = requests.get(f"{TELEGRAM_API_URL}/getMe", timeout=10)
    response.raise_for_status()
    bot_info = response.json()
    if bot_info.get('ok'):
        bot_name = bot_info['result']['first_name']
        print(f"✅ Telegram connection successful: {bot_name}\n")
    else:
        print(f"❌ Telegram connection error: {bot_info}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Telegram connection error: {e}")
    sys.exit(1)

# Process entries in reverse order (oldest to newest) to maintain chronological order
# But limit to most recent entries to avoid processing too many
entries_to_process = feed.entries[:MAX_ENTRIES_TO_PROCESS]
print(f"⏳ Items to process: {len(entries_to_process)}")

new_posts_count = 0

# Process from newest to oldest (so newest appears first)
for i, entry in enumerate(entries_to_process):
    link = entry.link
    
    # Skip if already posted
    if link in posted_links:
        title = clean_html(entry.title)[:60]
        print(f"\n⏭ Already posted: {title}...")
        continue
    
    # Post to Telegram
    success = post_to_telegram(entry)
    if success:
        new_posts_count += 1
        
        # Add delay between posts to avoid rate limits (except for last post)
        if i < len(entries_to_process) - 1:
            print(f"\n⏳ Waiting {POST_DELAY} seconds...")
            time.sleep(POST_DELAY)

print(f"\n{'='*60}")
print(f"📊 PROCESS COMPLETED")
print(f"{'='*60}")
print(f"Total items checked: {len(entries_to_process)}")
print(f"New items posted: {new_posts_count}")
print(f"Already posted items: {len(entries_to_process) - new_posts_count}")
print(f"Total saved links: {len(load_posted_links())}")
print(f"{'='*60}\n")

if new_posts_count == 0:
    print("ℹ️ No new content found.")