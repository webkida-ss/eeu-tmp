# Extension Release Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a deterministic Chrome Web Store ZIP with the production API URL and least-privilege API host permission without modifying extension source files.

**Architecture:** Add a Python 3.12 standard-library build script because Python is already required by the backend and `zipfile` avoids an additional packaging dependency. The script copies an explicit runtime allowlist into a temporary staging directory, rewrites only the API constant and release host permissions, validates the package, and writes a deterministic ZIP. A subprocess-based unittest verifies successful packaging, source immutability, deterministic output, and rejection of insecure API URLs.

**Tech Stack:** Python 3.12 standard library, `unittest`, Chrome Manifest V3, ZIP.

---

### Task 1: Specify the release artifact contract

**Files:**
- Create: `extension/test/test_build_release.py`

- [ ] **Step 1: Write the failing release-build tests**

The tests must:

- invoke `extension/scripts/build_release.py` as a subprocess;
- build twice with `https://api.example.com`;
- assert both ZIP files have identical SHA-256 digests;
- assert the ZIP contains exactly the runtime allowlist;
- assert `settings.js` contains the production URL and not the development
  default assignment;
- assert `manifest.json` contains only `https://api.example.com/*` in
  `host_permissions`;
- assert the source `settings.js` and `manifest.json` bytes are unchanged;
- reject `http://api.example.com`, credentials, query strings, and fragments.

Use `tempfile.TemporaryDirectory`, `subprocess.run`, `zipfile.ZipFile`, and
`unittest`. The expected runtime entries are:

```python
EXPECTED_ENTRIES = {
    "background.js",
    "content.css",
    "content.js",
    "i18n.js",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
    "manifest.json",
    "panel-ui.css",
    "panel-ui.js",
    "reading-panel.css",
    "reading-panel.js",
    "select-ui.js",
    "settings.js",
    "shared.js",
    "sidepanel.html",
}
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python3 -m unittest extension/test/test_build_release.py -v
```

Expected: FAIL because `extension/scripts/build_release.py` does not exist.

### Task 2: Implement deterministic release packaging

**Files:**
- Create: `extension/scripts/build_release.py`

- [ ] **Step 1: Implement URL validation**

Accept only an absolute HTTPS URL with:

- a hostname;
- no username or password;
- no query string or fragment;
- an optional path, normalized without a trailing slash.

Reject every invalid value with a concise error on stderr and a non-zero exit
code.

- [ ] **Step 2: Implement source staging**

Resolve the extension root from the script location and copy only the runtime
allowlist from Task 1 into a temporary directory. Fail if an allowlisted file
is missing. Do not modify or create files under the source directory.

- [ ] **Step 3: Rewrite release configuration**

Replace exactly one occurrence of:

```javascript
var DEFAULT_API_BASE_URL = 'http://localhost:18765';
```

with the normalized production URL.

Load the staged `manifest.json`, set `host_permissions` to the HTTPS API origin
pattern, and serialize it with two-space indentation and a final newline.
Preserve `content_scripts.matches` because the product must operate on user
selected article pages.

- [ ] **Step 4: Validate the staged artifact**

Fail the build unless:

- the manifest version is `3`;
- the extension version is a non-empty string;
- all referenced PNG icons exist;
- `DEFAULT_API_BASE_URL` equals the requested URL;
- `host_permissions` equals the single expected API origin pattern;
- no test, development server, local profile, or source SVG file is staged.

- [ ] **Step 5: Write a deterministic ZIP**

Write entries in sorted path order. Use a fixed ZIP timestamp of
`1980-01-01T00:00:00`, stable Unix file permissions, and deflate compression.
Create the output parent directory when necessary. Refuse to place the output
inside the extension source tree unless it is under an ignored `dist/`
directory.

- [ ] **Step 6: Run the release-build tests**

Run:

```bash
python3 -m unittest extension/test/test_build_release.py -v
```

Expected: all release-build tests PASS.

### Task 3: Document the release command

**Files:**
- Modify: `README.md`
- Modify: `infra/README.md`

- [ ] **Step 1: Add the canonical build command**

Document:

```bash
python3 extension/scripts/build_release.py \
  --api-base-url "https://YOUR_API_ID.execute-api.ap-northeast-1.amazonaws.com" \
  --output "dist/untangle-0.1.0.zip"
```

State that the command does not modify source files and that the output ZIP is
the Chrome Web Store upload artifact.

- [ ] **Step 2: Remove the manual source-replacement instruction**

Replace the statement that release packaging manually replaces
`DEFAULT_API_BASE_URL` with the canonical build command. Retain the documented
developer-only `chrome.storage.local` override.

- [ ] **Step 3: Run documentation and artifact checks**

Run:

```bash
python3 extension/scripts/build_release.py \
  --api-base-url "https://api.example.com" \
  --output "/tmp/untangle-release.zip"
python3 -m unittest extension/test/test_build_release.py -v
git diff --check
```

Expected:

- the build prints the artifact path, version, and SHA-256 digest;
- all tests PASS;
- `git diff --check` reports no errors.

### Task 4: Inspect the generated package

**Files:**
- No source changes.

- [ ] **Step 1: Verify the artifact contents**

Run a Python standard-library inspection that prints sorted ZIP names and the
release values from `manifest.json` and `settings.js`.

Expected:

- only the 17 runtime entries listed in Task 1 are present;
- `host_permissions` is `["https://api.example.com/*"]`;
- the API constant is `https://api.example.com`;
- no `dev/`, `test/`, `.web-ext-profile/`, or local backend URL is packaged.

- [ ] **Step 2: Record the implementation checkpoint**

Report changed files, test evidence, and remaining external release work.
Do not create a Git commit unless the user explicitly requests one.
