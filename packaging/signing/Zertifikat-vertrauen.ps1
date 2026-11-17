<#
  Der Gutachter - selbstsigniertes Code-Signing-Zertifikat auf DIESEM PC vertrauen.

  Einmalig ausfuehren (Rechtsklick > "Mit PowerShell ausfuehren"). Fragt nach
  Administratorrechten. Danach zeigt Windows bei Installer und Programm den
  Herausgeber "Der Gutachter (selbstsigniert)" an, und jede spaetere Version ist
  nachweislich vom selben Herausgeber und unveraendert.

  Das Zertifikat taugt NUR zum Signieren von Programmen (Code Signing), nicht fuer
  Webseiten oder E-Mail. Entfernen: certlm.msc > "Vertrauenswuerdige
  Herausgeber" und "Vertrauenswuerdige Stammzertifizierungsstellen" >
  "Der Gutachter (selbstsigniert)" loeschen.
#>
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$cer = Join-Path $PSScriptRoot "DerGutachter-Codesigning.cer"
if (-not (Test-Path $cer)) { throw "Zertifikatsdatei nicht gefunden: $cer" }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $cer
Write-Host "Zertifikat:   $($cert.Subject)"
Write-Host "Gueltig bis:  $($cert.NotAfter)"
Write-Host "SHA-256:      $($cert.GetCertHashString('SHA256'))"
Write-Host ""
Write-Host "Bitte den SHA-256-Fingerabdruck mit dem vom Herausgeber genannten vergleichen."
$ok = Read-Host "Fingerabdruck stimmt ueberein und Zertifikat vertrauen? (j/n)"
if ($ok -ne "j") { Write-Host "Abgebrochen."; exit 1 }

Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
Write-Host "Fertig. Der Gutachter wird auf diesem PC als vertrauenswuerdiger Herausgeber erkannt."
Read-Host "Enter zum Schliessen"
