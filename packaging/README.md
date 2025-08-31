Packaging and signing

macOS (app, signing, notarization)
- Build app: `python -m scripts.build_gui`
- Sign app (requires secrets and keychain configured):
  - `codesign --deep --force --options runtime --sign "Developer ID Application: YOUR NAME (TEAMID)" dist/XBRLValidatorGUI/XBRLValidatorGUI`
- Notarize (requires Apple ID/app-specific password):
  - `xcrun notarytool submit dist/XBRLValidatorGUI.app --apple-id APPLE_ID --team-id TEAM_ID --password APP_PASSWORD --wait`
- Staple: `xcrun stapler staple dist/XBRLValidatorGUI.app`

Windows (EXE, signing, MSI)
- Build EXE: `packaging/build_win.ps1 -PythonExe python`
- Sign EXE (requires signtool and PFX):
  - `signtool sign /tr http://timestamp.sectigo.com /td SHA256 /fd SHA256 /f codesign.pfx /p PASSWORD dist\XBRLValidatorGUI\XBRLValidatorGUI.exe`
- MSI: integrate WiX Toolset or Inno Setup to wrap `dist\XBRLValidatorGUI` contents.

DMG creation (macOS)
- Create DMG from `dist/XBRLValidatorGUI`: for example using `create-dmg` or `hdiutil create`.

License file placement
- App reads from `config/license.json` or `~/.xbrl_validator/license.json` or env `XBRL_VALIDATOR_LICENSE`.

