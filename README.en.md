# FFGraber

[한국어](README.md)

A Windows desktop tool that extracts final download URLs from FuckingFast file links using Chrome or Edge. It provides a desktop UI and a CLI. Actual file downloads are blocked.

## Getting started

Install Python 3.10+ and Google Chrome or Microsoft Edge. Extract the release ZIP into a writable folder and run `start.bat`. The first launch creates a local virtual environment and installs the dependencies. Internet access is needed to install packages and browser drivers.

Paste one FuckingFast URL per line and click **Start extraction**. Complete any verification in the browser; extraction resumes automatically.

## Copying and pasting

- Copy hyperlinks from a web page and press **Ctrl+V** in the input box. Hyperlink titles are converted to actual URLs. HTML anchor text is also supported. If the source application copies only a title with no URL data, use its **Copy link address** command.
- **Ctrl+V** replaces selected text or inserts at the cursor. **Paste from clipboard** replaces the whole input. **Ctrl+Z** undoes pasting. The original clipboard is preserved.
- The **Copy extracted links** button above the **Extracted URLs** tab copies successful final download URLs. It becomes available after the first success and shows the number of unique links. You can copy completed results while extraction is still running.
- **Copy all successful URLs** / **Ctrl+Shift+C** also copies successful URLs. **Copy selected URLs**, **Ctrl+C** in the result table, or its right-click menu copies successful selected items. Failed entries and duplicate URLs are excluded.
- **Copy FF page links** copies source page URLs. **Save TXT / JSON** exports URLs or detailed records.

## Languages

Select **한국어** or **English** in the **Language** selector at the top right. Switching languages preserves the input, results, selection, and browser choice. The preference is saved in `%APPDATA%\FFGraber\settings.json` on Windows. Third-party browser and driver diagnostics may retain their original wording.

```powershell
start.bat --language en
```

## CLI

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m ffgraber --language en --help
.\.venv\Scripts\python.exe -m ffgraber --language en --input links.txt --output results.json --browser chrome
.\.venv\Scripts\python.exe -m ffgraber --language en --gui --input links.txt
```

The input file must be UTF-8, with one URL per line. `--language ko` selects Korean; otherwise the saved preference is used, defaulting to Korean. `--host-only` collects source FF links without opening a browser or resolving final URLs. The default per-page timeout is 180 seconds. `--version` displays the installed version.

Final URLs may expire or depend on the originating IP or session. Stop and retry controls preserve partial results. The default reference engine uses Selenium and undetected-chromedriver, intercepts XHR redirect headers, and refuses to visit file pages if browser download blocking cannot be enabled.

Live final-URL extraction has not been verified successfully in the development environment; earlier attempts were blocked by `ERR_NETWORK_ACCESS_DENIED`. This release does not claim full live-site verification.

Reference: [zouhirdev/fitgirl-ff-link-extractor](https://github.com/zouhirdev/fitgirl-ff-link-extractor). Reference sources, development tests, test inputs, verification artifacts, and virtual environments are excluded from the published repository and source package.
