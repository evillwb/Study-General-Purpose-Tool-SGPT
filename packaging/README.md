# Building SGPT.exe

`SGPT.exe` is the whole app in one file (Python, the app, OCR models and libraries), made
with [PyInstaller](https://pyinstaller.org).

| File | What it is |
| --- | --- |
| `sgpt_exe.py` | What the .exe runs: keeps files in `Documents\SGPT`, picks a free port (8765 and up), opens the browser, and keeps the window open if something goes wrong. |
| `sgpt.spec` | PyInstaller settings: which packages and data files to include. |
| `sgpt.ico` | The icon. |
| `version_info.txt` | File details Windows shows under Properties → Details: publisher **E**, product name, version. |

## Automatic builds (GitHub Actions)

`.github/workflows/build-exe.yml` runs the tests, builds the .exe on Windows and checks
that it starts.

- **Every push:** the .exe is attached to the run as the **SGPT-windows** artifact
  (Actions tab → the run → Artifacts).
- **Pushes to `main`:** the **SGPT for Windows (latest)** release is also updated, with a
  direct download link.

## Building it yourself (Windows)

PyInstaller can only build a Windows .exe on Windows.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller packaging\sgpt.spec --noconfirm
```

The result is `dist\SGPT.exe` (about 200 MB). The same command on macOS or Linux builds
an app for that system instead.

If you add a new package to `requirements.txt` and the .exe says
`No module named …`, add the package to the `collect_all` list in `sgpt.spec`.

## Digital signature

Every build is signed with publisher **E**, and Windows shows it under
**Properties → Digital Signatures**.

By default the build makes a new **self-signed** "E" certificate each time. Windows
doesn't trust self-signed certificates, so the "Windows protected your PC" warning stays.
Only a certificate from a trusted certificate authority removes it. Options:

- A code-signing certificate from a certificate authority (paid, often yearly).
- [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/) (low monthly cost).
- [SignPath Foundation](https://signpath.org) (free for open-source projects).

To use your own certificate (a `.pfx` file), add two repository secrets under
**Settings → Secrets and variables → Actions**:

| Secret | Value |
| --- | --- |
| `SGPT_SIGN_PFX` | The `.pfx` file as base64. In PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx")) \| Set-Clipboard` |
| `SGPT_SIGN_PASSWORD` | The `.pfx` password |

The build then signs with it instead.

To keep one self-signed "E" certificate for every build instead of a new one each time,
make it once in PowerShell and add it as the secrets above:

```powershell
$cert = New-SelfSignedCertificate -Subject "CN=E" -Type CodeSigningCert `
  -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
Export-PfxCertificate -Cert $cert -FilePath cert.pfx `
  -Password (ConvertTo-SecureString "choose-a-password" -AsPlainText -Force)
```
