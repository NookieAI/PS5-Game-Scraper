# Auto-Updater Setup (one-time)

The app auto-checks `https://github.com/NookieAI/PS5-Game-Scraper/releases/latest/download/latest.json` 8 seconds after launch and prompts the user to install if a newer signed release is available. Tauri requires signed updates — unsigned releases will NOT trigger the updater on user machines.

This file walks through the one-time setup. After you complete these steps once, every future `git tag vX.Y.Z && git push --tags` automatically builds, signs, and publishes a new release that existing installs will pick up.

## Step 1 — Install the Tauri CLI (skip if already installed)

```bash
cargo install tauri-cli --version "^2" --locked
```

Verify it works:
```bash
cargo tauri --version
# tauri-cli 2.x.x
```

## Step 2 — Generate the signing keypair

```bash
cargo tauri signer generate -w ~/.tauri/ps5-browser.key
```

You'll be prompted for an optional password. Either leave it blank (simplest) or set one (more secure but you'll also need to store it as a separate secret).

The command produces TWO outputs:
- **Private key** saved to `~/.tauri/ps5-browser.key` — KEEP SECRET, never commit.
- **Public key** printed to stdout — public, embedded in the app binary.

Example public key output:
```
Your public key was saved at ~/.tauri/ps5-browser.key.pub
Public key:
dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDhDM0M0...
```

Copy the printed public key (the long base64 string after `Public key:`).

## Step 3 — Embed the public key in `tauri.conf.json`

Open `src-tauri/tauri.conf.json` and replace the placeholder:

```jsonc
"plugins": {
  "updater": {
    "endpoints": [
      "https://github.com/NookieAI/PS5-Game-Scraper/releases/latest/download/latest.json"
    ],
    "pubkey": "REPLACE_WITH_PUBLIC_KEY_FROM_SETUP_AUTOUPDATER.md",
    //          ^^^ paste your public key here as a single string
    "windows": { "installMode": "passive" }
  }
}
```

Commit + push the change. The public key in source is fine — it's PUBLIC.

## Step 4 — Add the private key as a GitHub repo secret

1. Go to `https://github.com/NookieAI/PS5-Game-Scraper/settings/secrets/actions`
2. Click **New repository secret**
3. Name: `TAURI_SIGNING_PRIVATE_KEY`
4. Value: paste the ENTIRE contents of `~/.tauri/ps5-browser.key` (NOT the .pub file)
5. Click **Add secret**

If you set a password on the key in step 2, also add:
- Name: `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- Value: the password you chose

## Step 5 — Verify by cutting a release

```bash
git tag v1.0.0
git push --tags
```

Watch the workflow run. When it completes, the release page should contain:
- `PS5.Game.Browser_1.0.0_x64-setup.exe` (Windows installer)
- `PS5.Game.Browser_1.0.0_x64-setup.nsis.zip` + `.sig` (signed Windows update bundle)
- `PS5.Game.Browser_1.0.0_aarch64.dmg` + `.app.tar.gz` + `.sig` (macOS ARM64)
- `PS5.Game.Browser_1.0.0_x64.dmg` + `.app.tar.gz` + `.sig` (macOS Intel)
- `PS5.Game.Browser_1.0.0_amd64.AppImage` + `.sig` (Linux)
- `PS5.Game.Browser_1.0.0_amd64.deb` (Linux package)
- **`latest.json`** ← this is the manifest the running app checks

## How updates work after this

1. User runs version `v1.0.0` of the app.
2. You release `v1.0.1`: `git tag v1.0.1 && git push --tags`. Workflow builds + signs.
3. Next time the user opens v1.0.0, 8 seconds after boot it fetches `latest.json`, finds v1.0.1 with valid signature, prompts user.
4. User accepts → bundle downloaded + signature verified against embedded public key → installed in place → app restarts on v1.0.1.

## Troubleshooting

**Workflow build fails with "signing key not found":** the secret name must be EXACTLY `TAURI_SIGNING_PRIVATE_KEY` (case-sensitive). Check Settings → Secrets.

**Updater never prompts:** check the running app's URL with devtools (if enabled). Confirm the endpoint URL is reachable and returns valid JSON. Confirm the version in `latest.json` is strictly greater than the running version (Tauri uses semver compare).

**"Failed to verify signature":** the public key in `tauri.conf.json` doesn't match the private key used to sign. Regenerate both, re-embed public, re-store private as secret.

**Lost the private key:** generate a new one, embed the new public key, update the secret, and users on the old version will need to manually download the new release once (their app won't auto-update across key rotations).

## Security notes

- The private key is the ONLY way to push updates to your users. If it leaks, attackers can push malicious code to every installed instance. Treat it like a production credential.
- The public key in `tauri.conf.json` is fine to commit — it's literally public.
- Tauri uses minisign (Ed25519) for signing. Industry-standard, fast, secure.
- Updates are TLS-fetched + signature-verified. A MITM cannot push a malicious update unless they also have your private key.
