$ErrorActionPreference = "Stop"
$base = "http://localhost:8000/api/v1"

function Api($method, $path, $body, $headers = @{}) {
    $uri = "$base$path"
    $params = @{Uri=$uri; Method=$method; ContentType="application/json"; UseBasicParsing=$true}
    if ($body) { $params.Body = ($body | ConvertTo-Json -Compress) }
    if ($headers.Count -gt 0) { $params.Headers = $headers }
    try {
        $r = Invoke-WebRequest @params
        return @{code=$r.StatusCode; data=($r.Content | ConvertFrom-Json); headers=$r.Headers}
    } catch {
        $resp = $_.Exception.Response
        $code = [int]$resp.StatusCode
        $sr = $resp.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($sr)
        $content = $reader.ReadToEnd()
        try { $data = $content | ConvertFrom-Json } catch { $data = $content }
        return @{code=$code; data=$data; headers=@{}}
    }
}

function Auth($token) { return @{Authorization="Bearer $token"} }
function ApiKey($key) { return @{"X-API-Key"=$key} }

$pass = 0; $fail = 0

function Test($name, $expected_code, $result) {
    $status = if ($result.code -eq $expected_code) { $script:pass++; "PASS" } else { $script:fail++; "FAIL" }
    Write-Host "[$status] $name => HTTP $($result.code) (expected $expected_code)"
    if ($status -eq "FAIL") { Write-Host "       DATA: $($result.data | ConvertTo-Json -Compress -Depth 3)" }
    return $result
}

Write-Host "=== Epic 1 Auth E2E Tests ==="
Write-Host ""

# 1. Register first user -> admin
$r = Test "Register 1st user (admin)" 201 (Api POST "/auth/register" @{email="admin2@test.com";password="Admin123!";full_name="Admin User"})
$adminRole = $r.data.role
Write-Host "       role=$adminRole"

# 2. Register second user -> trader
$r = Test "Register 2nd user (trader)" 201 (Api POST "/auth/register" @{email="trader@test.com";password="Trader123!";full_name="Trader"})
Write-Host "       role=$($r.data.role)"

# 3. Duplicate email
$r = Test "Register duplicate email (409)" 409 (Api POST "/auth/register" @{email="admin2@test.com";password="x";full_name="x"})

# 4. Login admin
$r = Test "Login admin" 200 (Api POST "/auth/login" @{email="admin2@test.com";password="Admin123!"})
$accessToken = $r.data.access_token
$refreshToken = $r.data.refresh_token

# 5. Login bad password
$r = Test "Login bad password (401)" 401 (Api POST "/auth/login" @{email="admin2@test.com";password="wrong"})

# 6. GET /users/me
$r = Test "GET /users/me" 200 (Api GET "/users/me" $null (Auth $accessToken))
Write-Host "       email=$($r.data.email) role=$($r.data.role)"

# 7. PUT /users/me
$r = Test "PUT /users/me (update name)" 200 (Api PUT "/users/me" @{full_name="Admin Updated"} (Auth $accessToken))
Write-Host "       full_name=$($r.data.full_name)"

# 8. Admin list users
$r = Test "GET /users (admin)" 200 (Api GET "/users" $null (Auth $accessToken))
Write-Host "       count=$($r.data.Count)"

# 9. Login as trader
$r = Test "Login trader" 200 (Api POST "/auth/login" @{email="trader@test.com";password="Trader123!"})
$traderToken = $r.data.access_token

# 10. Trader cannot list users (RBAC)
$r = Test "GET /users (trader, 403)" 403 (Api GET "/users" $null (Auth $traderToken))

# 11. Create API key
$r = Test "POST /api-keys" 201 (Api POST "/api-keys" @{name="test-key"} (Auth $accessToken))
$apiKeyId = $r.data.id
$fullKey = $r.data.full_key
Write-Host "       prefix=$($r.data.key_prefix) id=$apiKeyId"

# 12. List API keys
$r = Test "GET /api-keys" 200 (Api GET "/api-keys" $null (Auth $accessToken))
Write-Host "       count=$($r.data.Count)"

# 13. Auth via API key
$r = Test "GET /users/me (API key)" 200 (Api GET "/users/me" $null (ApiKey $fullKey))
Write-Host "       email=$($r.data.email)"

# 14. Revoke API key
$r = Test "DELETE /api-keys/$apiKeyId" 200 (Api DELETE "/api-keys/$apiKeyId" $null (Auth $accessToken))

# 15. Refresh token
$r = Test "POST /auth/refresh" 200 (Api POST "/auth/refresh" @{refresh_token=$refreshToken})
$newAccessToken = $r.data.access_token

# 16. Logout
$r = Test "POST /auth/logout" 200 (Api POST "/auth/logout" $null (Auth $newAccessToken))

# 17. Token blocked after logout
$r = Test "GET /users/me after logout (401)" 401 (Api GET "/users/me" $null (Auth $newAccessToken))

# 18. Rate limit headers
$r = Api GET "/health" $null
$rlRemaining = $r.headers["x-ratelimit-remaining"]
$rlLimit = $r.headers["x-ratelimit-limit"]
Write-Host ""
Write-Host "[INFO] Rate-limit headers: limit=$rlLimit remaining=$rlRemaining"

# Summary
Write-Host ""
Write-Host "=== RESULTS: $pass passed, $fail failed ==="
if ($fail -gt 0) { exit 1 }
