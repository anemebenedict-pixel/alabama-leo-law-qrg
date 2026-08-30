# Alabama LEO Law QRG v4 — GitHub Pages Edition

## First deployment
1. Create a public GitHub repository, for example `alabama-leo-law-qrg`.
2. Upload **all files and folders inside this ZIP** to the repository root. Be sure `.github`, `data`, `icons`, and `scripts` are included.
3. Commit to `main`.
4. GitHub → **Settings → Pages** → **Source: GitHub Actions**.
5. GitHub → **Actions** → **Update Alabama Code Index** → **Run workflow**.
6. When that finishes, it commits the full section/catchline index and the Pages deploy workflow runs automatically.
7. GitHub → **Settings → Pages** → open the published URL.
8. On iPhone Safari: Share → **Add to Home Screen**.

## How full-Code search works
GitHub Pages cannot run server-side code. This edition uses a GitHub Actions crawler to build `data/code-index.json` from the official Alabama Legislature Code table of contents. The app searches that static index locally by section number and official catchline/title.

If a keyword appears only inside a statute's body and not in the catchline, use **Search Official Full Text**. Selecting a result always opens the current controlling statutory text on the official Alabama Legislature site.

## Automatic updates
The Code-index workflow runs weekly on Monday and can be run manually at any time.

## QRG layer
The officer-oriented QRG remains available with plain-language summaries and general punishment references for common criminal/traffic statutes. Those summaries are simplified references and never replace the official Code, effective-date versions, case law, enhancements, or agency/local policy.
