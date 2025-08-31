# Code signing and notarization (overview)

## macOS (Developer ID Application)

- Prereqs: Apple Developer account, Developer ID Application certificate installed in login keychain.
- Sign and notarize app bundle (example commands):

```bash
# Sign
codesign --deep --force --options runtime \
  --sign "Developer ID Application: Your Company (TEAMID)" \
  dist/XBRLValidatorGUI/XBRLValidatorGUI

# Create ZIP for notarization
cd dist && zip -r XBRLValidatorGUI.zip XBRLValidatorGUI && cd -

# Notarize (requires Xcode or notarytool configured)
xcrun notarytool submit dist/XBRLValidatorGUI.zip \
  --keychain-profile "AC_PASSWORD_PROFILE" --wait

# Staple
xcrun stapler staple dist/XBRLValidatorGUI/XBRLValidatorGUI
```

- Verify: `spctl --assess --verbose=4 dist/XBRLValidatorGUI/XBRLValidatorGUI`

## Windows (EV/OV code signing)

- Prereqs: EV/OV code signing certificate and timestamp server URL.
- Sign EXE using signtool (installed with Windows SDK):

```powershell
$exe = "dist/XBRLValidatorGUI/XBRLValidatorGUI.exe"
signtool sign /tr http://timestamp.sectigo.com /td SHA256 /fd SHA256 \
  /a /f path\to\cert.pfx /p YOUR_PASSWORD $exe
```

- Verify: `signtool verify /pa /v $exe`

Notes:
- During packaging ensure all third-party licenses are included in distribution.
- Automate signing steps in CI with secure secret storage for credentials.
