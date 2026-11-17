# Windows PowerShell 5.1+: run using your normal Windows account.
[CmdletBinding(SupportsShouldProcess=$true)]
param()
$ErrorActionPreference = 'Stop'
$certificateBase64 = 'MIIDUTCCAjmgAwIBAgIUKq+sb2mlzBKLCNq9AT/IaZmHWK0wDQYJKoZIhvcNAQELBQAwIzEhMB8GA1UEAwwYQXV0b0V2YWwtVW5pZmllZC1HYXRld2F5MB4XDTI2MTExNjAzMDY0NloXDTI3MTExNjAzMDY0NlowIzEhMB8GA1UEAwwYQXV0b0V2YWwtVW5pZmllZC1HYXRld2F5MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2fkbxTH6pnpeset62DhA0/Ba/x0N2AkRoYLEg4R2BpisHZyUigJOCc8Qet3RFBRT6NOM3KQD8tPRHobxTklhiQuUn6sXqpqE68QXK4H9TNekYKpT5/XWC4H5Zgg1tw13BbY7XwalBtyv4kwK1Oi9fIh4rn33bN7kcYJVqPDZ4eghokAEK9TqiiUYfstMj5Y2FYceL6CAhigtjDRzvj+H+5K4O4S4GqMTddSVX32jDJ+Hfkpf0uIgN/c5xjl00bZug1xk19rfrMO2hwt4bTqPySvpcMbpIVTiV3V2bg9e9OgBNqS6dQ7cJsk7czBYpSMj0cl3yXdP87CUxMiBhQ8pFQIDAQABo30wezAdBgNVHQ4EFgQUJe+6ZEfLBzRaqAUiVSkAgqsy5mwwHwYDVR0jBBgwFoAUJe+6ZEfLBzRaqAUiVSkAgqsy5mwwDwYDVR0TAQH/BAUwAwEB/zAoBgNVHREEITAfhwSz1gIDghdsYW5nZnVzZS5hdXRvZXZhbC5sb2NhbDANBgkqhkiG9w0BAQsFAAOCAQEAxbodYOvAX5H+RJc/DDs615EoGJt6daiYJPTZGEnFwyeeklrbXhIyG51JG/hmEPhkbbZRxad0Fume496eT5EDxIQZZq/me1gszxxgPuuUn3csdWM2PzFHDrpNCD6RLzdkOVfYugmbSw9+VBzfGvKVzqLS0p9Dbvsnm39Po7TMzTHhAX3kr+gFfhtm0XkkyOKPb3tuhG327G9kp0stKJMxHVgElL166qU0kjujtv4sjXgnYjugxbKTVSKcGEirdTLdpMVW27qT2Hl7aUfF5W36bIV/zdX/FGXM37bU9/ywi8lCR+mVyPHnMZOWh8OFTdvc93Bf6auRuyxdhS+KRsX/SA=='
$expectedHash = '85A864DA5B153AC1B3503A903F49E4274B7701373CD503786011FB95AC90B6C7'
$bytes = [Convert]::FromBase64String($certificateBase64)
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new($bytes)
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','') } finally { $sha.Dispose() }
if ($hash -ne $expectedHash -or $certificate.NotAfter -le (Get-Date)) { throw 'Certificate fingerprint or expiration check failed.' }
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$state = Get-ItemProperty $key
$pacPath = $null
$pac = $null
if ($state.AutoConfigURL -and $state.AutoConfigURL.StartsWith('file:', [StringComparison]::OrdinalIgnoreCase)) {
    $pacPath = [Uri]::UnescapeDataString(($state.AutoConfigURL -replace '^file:/+', '')).Replace('/', '\')
    $pac = [IO.File]::ReadAllText($pacPath)
    $regex = [regex]::new('function\s+FindProxyForURL\s*\(\s*url\s*,\s*host\s*\)\s*\{')
    if (-not $regex.IsMatch($pac)) { throw 'Local PAC entrypoint not recognized; no changes made.' }
}
if (-not $PSCmdlet.ShouldProcess('Current-user proxy and certificate trust', 'Configure AutoEval access')) { return }
$backup = Join-Path $env:LOCALAPPDATA ('AutoEval\first-visit-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$state | Select-Object ProxyEnable,ProxyServer,ProxyOverride,AutoConfigURL | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'proxy-settings.json') -Encoding UTF8
if ($pacPath) { Copy-Item -LiteralPath $pacPath -Destination (Join-Path $backup 'proxy.pac') }
$overrides = @($state.ProxyOverride -split ';' | Where-Object { $_ })
foreach ($target in @('179.214.2.3','langfuse.autoeval.local')) {
    if ($overrides -notcontains $target) { $overrides += $target }
}
Set-ItemProperty -Path $key -Name ProxyOverride -Value ($overrides -join ';')
if ($pacPath -and -not $pac.Contains('// AutoEval exact-host bypass')) {
    $rule = "`r`n    // AutoEval exact-host bypass`r`n    if (host === '179.214.2.3' || host === 'langfuse.autoeval.local') { return 'DIRECT'; }"
    $pac = $regex.Replace($pac, [Text.RegularExpressions.MatchEvaluator]{ param($match) $match.Value + $rule }, 1)
    [IO.File]::WriteAllText($pacPath, $pac, [Text.UTF8Encoding]::new($false))
} elseif ($state.AutoConfigURL -and -not $pacPath) {
    Write-Warning 'Remote PAC is managed externally. If bypass is ignored, ask the VPN administrator for exact-host DIRECT rules.'
}
$store = [Security.Cryptography.X509Certificates.X509Store]::new('Root','CurrentUser')
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    if (-not ($store.Certificates | Where-Object Thumbprint -eq $certificate.Thumbprint)) { $store.Add($certificate) }
} finally { $store.Close() }
if (-not ('AutoEvalFirstVisit.Native' -as [type])) {
    Add-Type 'namespace AutoEvalFirstVisit { public static class Native { [System.Runtime.InteropServices.DllImport("wininet.dll")] public static extern bool InternetSetOption(System.IntPtr h, int o, System.IntPtr p, int l); } }'
}
[AutoEvalFirstVisit.Native]::InternetSetOption([IntPtr]::Zero,39,[IntPtr]::Zero,0) | Out-Null
[AutoEvalFirstVisit.Native]::InternetSetOption([IntPtr]::Zero,37,[IntPtr]::Zero,0) | Out-Null
Clear-DnsClientCache
Write-Host "Backup: $backup"
Write-Host 'VPN and default corporate proxy remain unchanged. Restart Chrome after setup.'
$failed = $false
foreach ($url in @('https://179.214.2.3/', 'https://179.214.2.3:8443/api/public/health')) {
    $request = [Net.HttpWebRequest]::Create($url)
    $request.Timeout = 15000
    $response = $null
    try { $response = $request.GetResponse() }
    catch [Net.WebException] {
        if ($_.Exception.Response) { $response = $_.Exception.Response }
        else { Write-Warning "$url : $($_.Exception.Status). Check VPN and proxy policy."; $failed = $true; continue }
    }
    try {
        $status = [int]$response.StatusCode
        Write-Host "$url -> HTTP $status"
        if (($url.EndsWith('/health') -and $status -ne 200) -or $status -notin @(200,401)) { $failed = $true }
    } finally { if ($response) { $response.Close() } }
}
Write-Host 'Demo: https://179.214.2.3/  Langfuse: https://179.214.2.3:8443/'
Write-Host 'Login credentials are issued separately. This script contains no passwords or private keys.'
if ($failed) { throw "Setup saved, but connectivity validation failed. Backup: $backup" }
