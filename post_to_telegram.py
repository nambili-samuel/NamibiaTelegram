#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import feedparser
import requests
from io import BytesIO
from PIL import Image
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import json
import time
import hashlib

# Force UTF-8 encoding for stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

RSS_URL = os.environ.get("RSS_URL")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Track ALL posted links and content hashes
STATE_FILE = "posted_links.json"
MAX_IMAGE_SIZE = 10_000_000  # 10MB (Telegram limit)
# How many RSS entries to check each run
MAX_ENTRIES_TO_PROCESS = 10
# Minimum time between posts to avoid rate limits (seconds)
POST_DELAY = 2
# Maximum age of articles to post (in hours) - prevents posting old content
MAX_ARTICLE_AGE_HOURS = 48  # Only post articles from last 48 hours
# Content similarity threshold for duplicate detection
MIN_CONTENT_LENGTH = 100  # Minimum characters for valid content

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def load_posted_links():
    """Load all previously posted article links and content hashes"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Backward compatibility: if it's a string (old format), convert to dict
                if isinstance(data, str):
                    return {data: {"timestamp": datetime.now().isoformat(), "hash": None}}
                # Ensure all entries have hash field
                for link, info in data.items():
                    if isinstance(info, str):  # Old format with just timestamp
                        data[link] = {"timestamp": info, "hash": None}
                return data
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_posted_links(links_dict):
    """Save all posted article links with timestamps and content hashes"""
    # Keep only the last 2000 entries to prevent file from growing too large
    if len(links_dict) > 2000:
        # Sort by timestamp and keep most recent
        sorted_items = sorted(
            links_dict.items(), 
            key=lambda x: x[1].get('timestamp', ''), 
            reverse=True
        )
        links_dict = dict(sorted_items[:2000])
    
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(links_dict, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(links_dict)} links saved")

def generate_content_hash(title, summary=""):
    """Generate a hash of content to detect duplicate articles with different URLs"""
    # Normalize text: lowercase, remove special chars, extra spaces
    normalized = re.sub(r'[^\w\s]', '', (title + " " + summary).lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return hashlib.md5(normalized.encode()).hexdigest()

def is_duplicate_content(title, summary, posted_links):
    """Check if content is duplicate based on hash comparison"""
    content_hash = generate_content_hash(title, summary)
    
    for link, info in posted_links.items():
        stored_hash = info.get('hash')
        if stored_hash and stored_hash == content_hash:
            print(f"⚠️ Duplicate content detected (different URL): {title[:50]}...")
            return True
    return False

def mark_as_posted(link, title, summary=""):
    """Mark a link as posted with current timestamp and content hash"""
    posted_links = load_posted_links()
    content_hash = generate_content_hash(title, summary)
    
    posted_links[link] = {
        "timestamp": datetime.now().isoformat(),
        "hash": content_hash
    }
    save_posted_links(posted_links)
    print(f"✅ Link marked: {link[:50]}...")

def get_article_publish_date(entry):
    """Extract and parse article publish date from RSS entry"""
    # Try different date fields
    date_fields = ['published_parsed', 'updated_parsed', 'created_parsed']
    
    for field in date_fields:
        if hasattr(entry, field):
            date_struct = getattr(entry, field)
            if date_struct:
                try:
                    return datetime(*date_struct[:6])
                except:
                    continue
    
    # Try parsing date strings
    date_string_fields = ['published', 'updated', 'created']
    for field in date_string_fields:
        if hasattr(entry, field):
            date_str = getattr(entry, field)
            if date_str:
                try:
                    # Try common date formats
                    from email.utils import parsedate_to_datetime
                    return parsedate_to_datetime(date_str)
                except:
                    continue
    
    return None

def is_article_fresh(entry, max_hours=MAX_ARTICLE_AGE_HOURS):
    """Check if article is recent enough to post"""
    publish_date = get_article_publish_date(entry)
    
    if not publish_date:
        # If no date found, assume it's recent (better to post than miss)
        print(f"⚠️ No publish date found, assuming fresh content")
        return True
    
    age = datetime.now() - publish_date.replace(tzinfo=None)
    age_hours = age.total_seconds() / 3600
    
    if age_hours > max_hours:
        print(f"⏳ Article too old: {age_hours:.1f} hours (max: {max_hours})")
        return False
    
    print(f"✅ Fresh article: {age_hours:.1f} hours old")
    return True

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

def extract_rich_summary(entry, link):
    """Extract a rich, detailed summary from the article"""
    # Try entry summary/description first
    summary = clean_html(entry.get("summary", entry.get("description", "")))
    
    # If summary is too short, try to fetch from article page
    if len(summary) < MIN_CONTENT_LENGTH:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            response = requests.get(link, timeout=10, headers=headers)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Try Open Graph description
                og_desc = soup.find('meta', property='og:description')
                if og_desc and og_desc.get('content'):
                    desc = og_desc['content'].strip()
                    if len(desc) > len(summary):
                        summary = desc
                        print(f"✅ Rich summary from og:description: {len(summary)} chars")
                
                # Try meta description
                if len(summary) < MIN_CONTENT_LENGTH:
                    meta_desc = soup.find('meta', attrs={'name': 'description'})
                    if meta_desc and meta_desc.get('content'):
                        desc = meta_desc['content'].strip()
                        if len(desc) > len(summary):
                            summary = desc
                            print(f"✅ Rich summary from meta description: {len(summary)} chars")
                
                # Try first paragraph from article content
                if len(summary) < MIN_CONTENT_LENGTH:
                    content_selectors = [
                        '.entry-content p', 
                        'article p', 
                        '.post-content p',
                        '.article-content p',
                        'main p'
                    ]
                    for selector in content_selectors:
                        paragraphs = soup.select(selector)
                        for p in paragraphs:
                            text = p.get_text().strip()
                            if len(text) > MIN_CONTENT_LENGTH:
                                summary = text
                                print(f"✅ Rich summary from article content: {len(summary)} chars")
                                break
                        if len(summary) >= MIN_CONTENT_LENGTH:
                            break
        except Exception as e:
            print(f"⚠️ Could not fetch rich summary: {e}")
    
    return summary

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

def get_source_info(rss_url):
    """Extract source name and details from RSS URL"""
    source_map = {
        'jobs4na.com': {'name': 'Jobs4NA', 'emoji': '💼', 'type': 'Jobs & Careers'},
        'news.google.com': {'name': 'Google News', 'emoji': '🌐', 'type': 'News Aggregator'},
        'namibiansun.com': {'name': 'Namibian Sun', 'emoji': '☀️', 'type': 'News'},
        'eaglefm.com.na': {'name': 'Eagle FM', 'emoji': '📻', 'type': 'Radio & News'},
        'neweralive.na': {'name': 'New Era', 'emoji': '📰', 'type': 'News'},
        'thebrief.com.na': {'name': 'The Brief', 'emoji': '📋', 'type': 'News'},
        'namibian.com.na': {'name': 'The Namibian', 'emoji': '📑', 'type': 'News'},
    }
    
    for domain, info in source_map.items():
        if domain in rss_url.lower():
            return info
    
    return {'name': 'Namibia News', 'emoji': '📰', 'type': 'News'}

def create_beautiful_post(title, link, category="", summary="", source_info=None, publish_date=None):
    """Create a beautiful, professional Telegram post with rich intro content for Namibian news"""
    
    # Decode HTML entities in title
    title = clean_html(title)
    summary = clean_html(summary)
    
    # Add appropriate emoji based on category or keywords
    category_emojis = {
        'SPORTS': '⚽', 'SPORT': '⚽', 'FOOTBALL': '⚽', 'RUGBY': '🏉', 'CRICKET': '🏏',
        'BUSINESS': '💼', 'ECONOMY': '💰', 'FINANCE': '💵', 'TRADE': '📊',
        'POLITICS': '🏛️', 'ELECTION': '🗳️', 'GOVERNMENT': '🏛️', 'PARLIAMENT': '🏛️',
        'HEALTH': '🏥', 'MEDICAL': '⚕️', 'COVID': '😷', 'HOSPITAL': '🏥',
        'EDUCATION': '📚', 'SCHOOL': '🎓', 'UNIVERSITY': '🎓', 'STUDENT': '📖',
        'TECHNOLOGY': '💻', 'TECH': '⚙️', 'DIGITAL': '🌐', 'INNOVATION': '💡',
        'ENTERTAINMENT': '🎭', 'CULTURE': '🎨', 'MUSIC': '🎵', 'FILM': '🎬',
        'JOBS': '💼', 'EMPLOYMENT': '👔', 'CAREER': '📊', 'HIRING': '🤝',
        'NEWS': '📰', 'BREAKING': '🚨', 'LATEST': '🆕', 'UPDATE': '📢',
        'WEATHER': '🌤️', 'CLIMATE': '🌍', 'ENVIRONMENT': '🌱',
        'CRIME': '🚔', 'JUSTICE': '⚖️', 'LAW': '📜', 'COURT': '🏛️',
        'TOURISM': '✈️', 'TRAVEL': '🗺️', 'WILDLIFE': '🦁', 'SAFARI': '🐘',
        'MINING': '⛏️', 'INDUSTRY': '🏭', 'AGRICULTURE': '🌾', 'FISHING': '🎣',
    }
    
    # Try to find matching category
    emoji = '📰'  # Default
    for cat_key, cat_emoji in category_emojis.items():
        if cat_key in category.upper() or cat_key in title.upper():
            emoji = cat_emoji
            break
    
    # Namibia flag emoji
    namibia_flag = '🇳🇦'
    
    # Build the post with enhanced intro section
    post_text = f"<b>{namibia_flag} {emoji} NAMIBIA NEWS UPDATE</b>\n"
    post_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Add source information if available
    if source_info:
        source_emoji = source_info.get('emoji', '📰')
        source_name = source_info.get('name', 'News')
        source_type = source_info.get('type', 'News')
        post_text += f"{source_emoji} <b>{source_name}</b> • <i>{source_type}</i>\n"
    
    # Add publish date/freshness indicator
    if publish_date:
        age = datetime.now() - publish_date.replace(tzinfo=None)
        age_hours = age.total_seconds() / 3600
        
        if age_hours < 1:
            age_minutes = age.total_seconds() / 60
            freshness = f"🔴 BREAKING • {int(age_minutes)} minutes ago"
        elif age_hours < 6:
            freshness = f"🔥 HOT • {int(age_hours)} hours ago"
        elif age_hours < 24:
            freshness = f"🆕 NEW • {int(age_hours)} hours ago"
        else:
            freshness = f"📅 {int(age_hours / 24)} days ago"
        
        post_text += f"{freshness}\n"
    else:
        post_text += "🆕 FRESH CONTENT\n"
    
    post_text += "\n"
    
    # Main headline
    post_text += f"<b>📌 {title}</b>\n\n"
    
    # Enhanced summary/intro section
    if summary and len(summary) >= MIN_CONTENT_LENGTH:
        # Limit summary to 350 characters for better readability
        if len(summary) > 350:
            summary = summary[:347] + "..."
        post_text += f"<i>{summary}</i>\n\n"
    else:
        # If no rich summary, add a brief note
        post_text += "<i>Read the full article for complete details...</i>\n\n"
    
    # Category tag
    if category:
        post_text += f"🏷️ {category}\n"
    
    post_text += "\n"
    post_text += f"🔗 <a href='{link}'>Read Full Article →</a>\n"
    post_text += "━━━━━━━━━━━━━━━━━━━━"
    
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
            print(f"❌ Telegram API error: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Telegram send error: {e}")
        return False

def post_to_telegram(entry, source_info):
    """Post a single entry to Telegram with freshness checks"""
    title = clean_html(entry.title)
    link = entry.link
    
    print(f"\n{'='*60}")
    print(f"📌 Processing: {title[:80]}...")
    print(f"   Link: {link}")
    print(f"{'='*60}")
    
    # Check if article is fresh enough
    if not is_article_fresh(entry):
        print(f"⏭️ Skipping old article")
        return False
    
    # Extract rich summary
    summary = extract_rich_summary(entry, link)
    
    # Check for duplicate content (same article, different URL)
    posted_links = load_posted_links()
    if is_duplicate_content(title, summary, posted_links):
        print(f"⏭️ Skipping duplicate content")
        return False
    
    # Extract category
    categories = []
    if hasattr(entry, 'tags'):
        categories = [tag.term for tag in entry.tags]
    category = categories[0] if categories else "General"
    
    # Get publish date
    publish_date = get_article_publish_date(entry)
    
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
            print(f"⚠️ Thumbnail could not be downloaded, continuing...")
    else:
        print(f"⚠️ Thumbnail not found, continuing...")
    
    # Create beautiful post text with enhanced intro
    post_text = create_beautiful_post(title, link, category, summary, source_info, publish_date)
    
    # Post to Telegram
    print(f"\n📤 Sending to Telegram...")
    
    success = send_telegram_message(post_text, image_data)
    
    if success:
        mark_as_posted(link, title, summary)
        
        print(f"\n✅ SUCCESSFULLY POSTED!")
        print(f"📌 Title: {title}")
        print(f"📂 Category: {category}")
        print(f"🔗 Link: {link}")
        print(f"🖼️ Thumbnail: {'Yes ✔' if image_data else 'No ✗'}")
        print(f"📝 Summary length: {len(summary)} chars")
        if publish_date:
            print(f"📅 Published: {publish_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"⏰ Posted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return True
    else:
        print(f"\n❌ POSTING FAILED!")
        return False

# Main execution
print(f"\n{'='*60}")
print(f"🤖 NAMIBIA NEWS TELEGRAM BOT")
print(f"{'='*60}")
print(f"📰 Processing RSS Feed: {RSS_URL}")
print(f"⏰ Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}\n")

# Parse RSS feed
feed = feedparser.parse(RSS_URL)

if not feed.entries:
    print("⚠️ No content found in RSS feed.")
    sys.exit(0)

print(f"✅ RSS feed loaded: {len(feed.entries)} items found")

# Load previously posted links
posted_links = load_posted_links()
print(f"📊 Previously posted: {len(posted_links)} articles")
print(f"🔍 Content hash tracking: Enabled")
print(f"⏳ Max article age: {MAX_ARTICLE_AGE_HOURS} hours")

# Get source information
source_info = get_source_info(RSS_URL)
print(f"📡 Source: {source_info['name']} ({source_info['type']})")

# Test Telegram connection
print(f"\n🔐 Testing Telegram connection...")
try:
    response = requests.get(f"{TELEGRAM_API_URL}/getMe", timeout=10)
    response.raise_for_status()
    bot_info = response.json()
    if bot_info.get('ok'):
        bot_name = bot_info['result']['first_name']
        print(f"✅ Connected to bot: {bot_name}\n")
    else:
        print(f"❌ Telegram connection error: {bot_info}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Telegram connection error: {e}")
    sys.exit(1)

# Process entries (newest first)
entries_to_process = feed.entries[:MAX_ENTRIES_TO_PROCESS]
print(f"⏳ Processing {len(entries_to_process)} most recent items\n")

new_posts_count = 0
skipped_old = 0
skipped_duplicate_url = 0
skipped_duplicate_content = 0

for i, entry in enumerate(entries_to_process):
    link = entry.link
    
    # Skip if already posted (URL check)
    if link in posted_links:
        title = clean_html(entry.title)[:60]
        print(f"\n⏭️ Already posted (URL): {title}...")
        skipped_duplicate_url += 1
        continue
    
    # Post to Telegram (includes freshness and content duplicate checks)
    success = post_to_telegram(entry, source_info)
    if success:
        new_posts_count += 1
        
        # Add delay between posts to avoid rate limits
        if i < len(entries_to_process) - 1 and new_posts_count < len(entries_to_process):
            print(f"\n⏳ Waiting {POST_DELAY} seconds before next post...")
            time.sleep(POST_DELAY)

# Final summary
print(f"\n{'='*60}")
print(f"📊 EXECUTION SUMMARY")
print(f"{'='*60}")
print(f"✅ New articles posted: {new_posts_count}")
print(f"⏭️ Skipped (already posted URL): {skipped_duplicate_url}")
print(f"📊 Total articles in database: {len(load_posted_links())}")
print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}\n")

if new_posts_count == 0:
    print("ℹ️ No new fresh content found. All articles are either old or already posted.")
else:
    print(f"🎉 Successfully posted {new_posts_count} fresh article(s) to Telegram!")
