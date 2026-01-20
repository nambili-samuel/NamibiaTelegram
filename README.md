# RSS to Telegram Bot - Namibia News 🇳🇦

This bot automatically posts Namibian news from multiple RSS feeds to your Telegram group. All posts include beautiful formatting, thumbnails, headings, intro text, and the Namibia flag.

## 🎯 Features

- ✅ Automatic news posting from 4 different Namibian RSS sources:
  - 📰 Google News - Namibia Sports
  - 📰 EIN News - Namibia
  - 📰 The Namibian
  - 💼 Jobs4NA
- ✅ All posts include thumbnail images
- ✅ Beautiful HTML formatting with:
  - 🇳🇦 Namibia flag
  - 📌 Category-based icons
  - 📝 Article headlines
  - 📄 Article intro/summary
  - 🔗 Read more links
- ✅ Prevents duplicate posts
- ✅ Runs every 10 minutes automatically
- ✅ Rate limit protection
- ✅ Image optimization

## 📋 Setup Steps

### 1. Create Telegram Bot

1. Start a conversation with [@BotFather](https://t.me/BotFather) on Telegram
2. Send the `/newbot` command
3. Choose a name for your bot (e.g., "Namibia News Bot")
4. Choose a username for your bot (e.g., "namibia_news_bot")
5. BotFather will give you a **bot token**. Save it!

### 2. Get Chat ID

**For a group:**
1. Add your bot to the group as admin
2. Send a message in the group
3. Visit this URL: `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
   (Replace BOT_TOKEN with your actual token)
4. Find your chat ID in the response: `"chat":{"id":-100XXXXXXXXX}`
5. Save the chat ID (e.g., `-1001234567890`)

**For a channel:**
1. Add your bot to the channel as admin
2. Post a message in the channel
3. Follow the same steps as above

**To send to yourself:**
1. Start a conversation with [@userinfobot](https://t.me/userinfobot)
2. The bot will send you your chat ID (e.g., `123456789`)

### 3. GitHub Repository Setup

1. Fork this repository or create a new one
2. Add these files to your repository:
   - `post_to_telegram.py`
   - `.github/workflows/rss-to-telegram.yml`

### 4. Configure GitHub Secrets

In your repository, go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

1. **TELEGRAM_BOT_TOKEN**
   - Value: Your bot token from BotFather (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

2. **TELEGRAM_CHAT_ID**
   - Value: Your group/channel/personal chat ID (e.g., `-1001234567890` or `123456789`)

### 5. Enable Workflow

1. Go to the **Actions** tab in your repository
2. Enable the workflow
3. Click **Run workflow** to test it immediately

## 🚀 How It Works

The bot automatically:
- Checks **4 different Namibian RSS feeds** every 10 minutes:
  1. **Google News - Namibia Sports** - Latest sports news
  2. **EIN News - Namibia** - General Namibian news
  3. **The Namibian** - Official newspaper feed
  4. **Jobs4NA** - Job listings and career news
- Finds new articles
- Posts them to your Telegram group with thumbnails
- Saves posted articles in `posted_links.json` (shared across all sources)

## 🎨 Message Format

```
🇳🇦 ⚽ Namibia News

Article Headline Goes Here

Brief summary or introduction of the article...

📂 Sports

🔗 Read full article
```

## 📸 Thumbnail Sources

The bot searches for thumbnails in this order:
1. RSS enclosure (image in feed)
2. Google News media_content
3. Open Graph image (og:image meta tag)
4. Twitter Card image
5. Featured image on article page
6. First large image in article content

## ⚙️ Customization

### Change RSS Feeds
Edit `rss-to-telegram.yml` to add or change feeds:

```yaml
- name: Run RSS bot - Your Source Name
  env:
    RSS_URL: https://example.com/feed
    TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
    TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
  run: |
    python post_to_telegram.py
```

**Current Sources:**
1. `https://news.google.com/news/rss/headlines/section/q/namibia%20sports/namibia%20sports?ned=us&hl=en`
2. `http://www.einnews.com/rss/ENeMt6E9jOtjDuWx`
3. `https://www.namibian.com.na/feed/`
4. `https://www.jobs4na.com/feed/`

### Change Check Frequency
Edit `rss-to-telegram.yml`:

```yaml
schedule:
  - cron: "*/10 * * * *"  # Every 10 minutes (you can change this)
```

Examples:
- `*/5 * * * *` - Every 5 minutes
- `*/15 * * * *` - Every 15 minutes
- `*/30 * * * *` - Every 30 minutes
- `0 * * * *` - Every hour

### Customize Category Emojis
Edit the `category_emojis` dictionary in `post_to_telegram.py`.

### Change Post Limit
In `post_to_telegram.py`:

```python
MAX_ENTRIES_TO_PROCESS = 10  # How many articles to process per run
```

## 🔍 Troubleshooting

### "Unauthorized" Error
- Check your bot token
- Get a new token from BotFather

### "Chat not found" Error
- Verify your chat ID is correct
- Make sure the bot is added to the group/channel as admin

### "Message is too long" Error
- The bot automatically truncates long summaries
- You can adjust limits in the `create_beautiful_post` function

### No Images Being Posted
- Check if the RSS feed contains images
- Check internet connectivity
- Verify Telegram's 10MB image size limit isn't exceeded

### Bot Posting Duplicates
- Ensure `posted_links.json` is being committed
- Check that GitHub Actions has write permissions

## 📝 View Logs

1. Go to the **Actions** tab in your repository
2. Click on the latest workflow run
3. Click on the "post-to-telegram" job
4. View detailed logs

## 🤝 Contributing

Pull requests are welcome!

## 📄 License

MIT License - Free to use!

---

**Note:** When the bot runs for the first time, it checks the last 10 items from each RSS feed but only posts new ones. All sources share one `posted_links.json` file, so the same article won't be posted twice even if it appears in multiple feeds."# NamibiaTelegram" 
"# NamibiaTelegram" 
"# Test" 
