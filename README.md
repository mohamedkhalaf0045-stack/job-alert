# LinkedIn UAE Job Alert

This is a simple Windows app that checks LinkedIn public job listings for:

- `IT Systems administrator`
- `Senior IT Support`
- `IT support`
- `IT HelpDesk`

It searches in `United Arab Emirates`, keeps a cache of jobs it has already seen, and shows a Windows notification when a new listing appears.
It can also use your signed-in LinkedIn cookie to filter out jobs that already show as applied, and it can send instant Telegram messages with the job link.

## Run In Background While Locked

If you want alerts to keep working while the laptop is locked:

1. Start the background worker with [Start-LinkedInJobWorker-Hidden.vbs](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/Start-LinkedInJobWorker-Hidden.vbs).
2. Optionally install the logon task with [Install-LinkedInJobWorkerTask.ps1](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/Install-LinkedInJobWorkerTask.ps1).
3. Check background activity in [worker.log](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/worker.log).

Notes:

- This keeps working while Windows is locked, as long as the machine stays awake and connected to the internet.
- If the laptop goes to sleep or hibernates, no checks can run until it wakes up again.
- Stop the worker with [Stop-LinkedInJobWorker.ps1](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/Stop-LinkedInJobWorker.ps1).

## Run it

1. Double-click [Run-LinkedInJobAlert.bat](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/Run-LinkedInJobAlert.bat).
2. Click `Start`.
3. Leave the app open while it monitors jobs.

## Use your LinkedIn account

If you want the app to hide jobs you already applied to:

1. Sign in to LinkedIn in your browser.
2. Open browser developer tools and copy the `Cookie` header for a LinkedIn jobs page request.
3. Paste it into the `LinkedIn cookie header` box in the app.
4. Leave `Hide jobs already marked as applied` enabled.

Notes:

- The app does not ask for your LinkedIn password.
- It uses the cookie string from your already signed-in browser session.
- If the cookie expires, paste a fresh one.

## Telegram alerts

To get instant Telegram alerts:

1. Create a Telegram bot with `@BotFather`.
2. Start a chat with your bot.
3. Get your bot token and chat ID.
4. Paste them into the app and click `Test Telegram`.

When a new job is found, the app will send the title, company, location, and direct link to Telegram.

## Notes

- The first scan seeds the local cache and does not notify for already-existing jobs. That avoids a flood of alerts on first launch.
- After that, new jobs found in later scans will trigger notifications.
- Double-click any row in the app to open the job posting in your browser.
- The cache file is [seen-jobs.json](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/seen-jobs.json) and is created automatically after the first scan.
- The persistent jobs database is [jobs.db](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/jobs.db).

## Customize

- Edit the keywords box in the app to add or remove job titles.
- Change the check interval if you want faster or slower polling.
- Keep the location as `United Arab Emirates` or replace it with a more specific UAE location if needed.
- Settings are saved to [settings.json](/C:/Users/Mohamed%20Khalaf/Documents/Codex/2026-05-06/create-a-simple-windows-app-to/settings.json).
- Retrieved jobs are deduplicated and updated in the SQLite database using `job_id` as the primary key and `url` as a unique field.
