# Nova Metrics Marketing Agent

Runs by itself every 2 days. Zero rand.

**What it does each run**
1. Reads your live website and the last 2 weeks of site commits, so it knows when Solar Intelligence changes.
2. Reads South African solar news headlines.
3. Writes a LinkedIn and a Facebook post in the Nova Metrics voice (brief: `agent/brand.md`).
4. Checks the post against hard rules (no invented numbers, prices, bugs, guarantees, placeholders) and makes the AI rewrite it until it passes.
5. Draws a branded 1080x1080 image.
6. Sends post + image to Make, which emails it to you (review mode) or publishes it (auto mode).
7. Remembers what it posted so it never repeats itself.

Event dates live in `agent/events.json`. Add new events there and it will start promoting them 14 days ahead.

## One-time setup (about 40 minutes)

### 1. GitHub repo (5 min)
- Create a new **public** repository, e.g. `nova-marketing-agent`. Public keeps GitHub Actions free and lets Make fetch the images. The repo holds no secrets.
- Upload everything in this folder, including the hidden `.github` folder.

### 2. Free AI key (5 min)
- Create a free account at console.groq.com, then API Keys, then Create. Copy the key.
- GitHub repo, Settings, Secrets and variables, Actions, **New repository secret**: name `LLM_API_KEY`, value = the key.

### 3. Make.com scenario (20 min)
Sign up free at make.com. Create **one** scenario:
1. **Webhooks, Custom webhook.** Add a webhook and copy its URL. Under Settings, Variables, add repo secret `MAKE_WEBHOOK_URL` with that URL.
2. Run the agent once (step 5) so Make learns the data fields (`linkedin`, `facebook`, `image_url`, `mode`, `headline`, `founder_attention`).
3. Add a **Router** with two routes:
   - Filter `mode` = `review`: **Gmail, Send an email** to yourself. Subject: `Nova post for review`. Body: `{{linkedin}}` and `{{facebook}}`. Attach or link `{{image_url}}`.
   - Filter `mode` = `auto`: **LinkedIn, Create a Company Page Post** (text `{{linkedin}}`, image `{{image_url}}`) and **Facebook Pages, Create a Photo Post** (message `{{facebook}}`, photo URL `{{image_url}}`).
4. Connect LinkedIn and Facebook inside Make when asked (you log in once and click allow).
5. Turn the scenario **on**.

Cost check: about 3 to 4 credits per post, roughly 60 a month, against 1,000 free.

### 4. Settings (2 min)
Repo, Settings, Secrets and variables, Actions, Variables tab:
- `STAND_NO` = SP14
- `MODE` = `review`

### 5. First run
Repo, Actions, "Nova Metrics marketing agent", **Run workflow**, tick force. You should get the email within a few minutes.

## Going fully hands-off
After you have approved about 3 emailed posts and trust the tone, change the `MODE` variable to `auto`. No other change. If a post ever looks wrong, set it back to `review`.

## Optional extras
- `SITE_REPO_TOKEN` secret: a GitHub token with read access, only needed if your website repo is private.
- `USE_DEMO_SCREENSHOTS` variable = `1`: product-demo posts use a screenshot of your demo mode. Verify the first one looks right.
- `LLM_BASE_URL` and `LLM_MODEL` variables switch to another OpenAI-compatible provider (for example Google Gemini's free tier) if Groq changes its limits.

## Honest limits
- Free AI models write well but not as well as Claude. The guardrails block bad claims, not flat writing. Read the first few posts.
- It cannot know what you have not published. Features that are not on your website or in your commit messages will not be mentioned.
- It cannot reply to comments or run Instagram yet.
- LinkedIn and Facebook change their rules. If Make's connection expires, you get an email from Make, and you re-click allow.
