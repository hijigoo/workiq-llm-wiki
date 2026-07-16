# Work IQ Teams MCP 연동 작업 정리 (순서대로)

이 문서는 **Work IQ Teams MCP 서버(`mcp_TeamsServer`)** 를 샘플 웹 앱에 연동하기까지
실제로 수행한 작업을 순서대로 정리한 기록입니다.

- 테넌트: `YOURTENANT` / `00000000-0000-0000-0000-000000000000`
- 관리자 계정: `admin@yourtenant.onmicrosoft.com`
- 결과물: `teams-mcp-web-sample/` (Express + Vanilla JS)

> 자리표시자 `{tenantId}` = `00000000-0000-0000-0000-000000000000`
> 실제 비밀값(client secret 등)은 이 문서에 포함하지 않습니다.

---

## 0. 목표 정의

- 일반 WorkIQ MCP(`https://workiq.svc.cloud.microsoft/mcp`, 전체 M365)가 아니라,
  **Teams 전용** MCP 서버(`mcp_TeamsServer`)만 사용.
- 사용자가 웹에서 요청 → Teams MCP를 통해 응답받는 별도 샘플 웹 구축.

참고 문서: <https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-teams-work-iq>

| 항목 | 값 |
|------|-----|
| Server ID | `mcp_TeamsServer` |
| 엔드포인트 | `https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_TeamsServer` |
| 스코프 | `McpServers.Teams.All` |
| 상태 | Preview |

---

## 1. 엔드포인트 인증 요건 파악

MCP 엔드포인트에 인증 없이 요청 → **401** 과 함께 OAuth 메타데이터 위치 확인.

```bash
# 401 + www-authenticate 확인
curl -i -X POST \
  "https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_TeamsServer"

# 보호 리소스 메타데이터
curl -s "https://agent365.svc.cloud.microsoft/.well-known/oauth-protected-resource/agents/tenants/{tenantId}/servers/mcp_TeamsServer"
```

확인된 사항:
- 인증 서버: `https://login.microsoftonline.com/organizations/v2.0`
- 스코프: `<resource>/.default` (+ `openid profile offline_access`)
- 토큰 전달: `Authorization: Bearer` 헤더
- 리소스는 Entra에서 **Agent Tools** 앱으로 해석됨
  - appId `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`
  - identifierUri `https://agent365.svc.cloud.microsoft`
  - Teams 위임 권한 `McpServers.Teams.All` = `5efd4b9c-e459-40d4-a524-35db033b072f`

---

## 2. Entra 앱 등록 생성

웹앱이 사용자 대신 토큰을 받도록 **앱 등록(App registration)** 생성.

```bash
# 앱 등록 (Web redirect)
az ad app create \
  --display-name "Teams MCP Web Sample" \
  --web-redirect-uris "http://localhost:3000/auth/callback"

# 서비스 주체(SP) 생성
az ad sp create --id <appId>

# 클라이언트 시크릿 발급 (값은 .env로만 저장, 출력 노출 금지)
az ad app credential reset --id <appId>
```

결과:
- 앱 이름: **Teams MCP Web Sample**
- Application (client) ID: `11111111-1111-1111-1111-111111111111`
- Redirect URI(Web): `http://localhost:3000/auth/callback`
- client secret: 발급 후 `.env`에만 저장

---

## 3. API 권한 추가 + 관리자 동의

Teams MCP 리소스(**Agent Tools**)에 대한 **위임 권한** 추가 후 관리자 동의.

```bash
# 위임 권한 추가: McpServers.Teams.All (Scope)
az ad app permission add \
  --id <appId> \
  --api ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --api-permissions 5efd4b9c-e459-40d4-a524-35db033b072f=Scope

# 관리자 동의(테넌트 전체)
az ad app permission admin-consent --id <appId>
```

검증: 동의 후 `oauth2PermissionGrants`에 `McpServers.Teams.All`(AllPrincipals) 부여 확인.

---

## 4. 토큰 audience 수용 확인

앱-전용(client_credentials) 토큰으로 호출해 **audience가 수용되는지** 확인.

```bash
# 토큰 발급
curl -s -X POST "https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token" \
  -d "client_id=<appId>" \
  --data-urlencode "client_secret=<secret>" \
  -d "grant_type=client_credentials" \
  --data-urlencode "scope=https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_TeamsServer/.default"
```

- 결과: **403** `Access denied: Scope 'McpServers.Teams.All' is not present in the request`
- 해석: **audience는 수용됨**, 다만 앱-전용 토큰엔 위임 `scp`가 없음
  → **사용자 로그인(위임)** 으로 `.default`를 받으면 `scp: McpServers.Teams.All` 포함되어 정상 동작.

---

## 5. 샘플 웹 앱 구축

`teams-mcp-web-sample/` 생성 (Node.js ESM + Express).

```
src/config.js   # .env 로드, 스코프(<MCP_URL>/.default), llmProvider()
src/auth.js     # MSAL Authorization Code + PKCE, 무음 토큰 갱신
src/mcp.js      # @modelcontextprotocol/sdk StreamableHTTP 클라이언트(Bearer 부착)
src/agent.js    # (선택) LLM 툴콜링 루프
src/server.js   # Express 라우트 + 정적 서빙
public/         # 채팅 UI + 도구 직접 실행 패널
```

```bash
cd teams-mcp-web-sample
npm install
```

주요 의존성: `@azure/msal-node`, `@modelcontextprotocol/sdk`, `express`,
`express-session`, `dotenv`, `openai`.

---

## 6. `.env` 채우기

```bash
cp .env.example .env
```

| 키 | 값 |
|----|----|
| `TENANT_ID` | `00000000-0000-0000-0000-000000000000` |
| `CLIENT_ID` | `11111111-1111-1111-1111-111111111111` |
| `CLIENT_SECRET` | (2단계에서 발급, 비공개) |
| `MCP_SERVER_URL` | `https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_TeamsServer` |
| `REDIRECT_URI` | `http://localhost:3000/auth/callback` |
| `SESSION_SECRET` | (랜덤 문자열) |

---

## 7. 실행 & 로그인 검증

```bash
npm start   # http://localhost:3000
```

1. 브라우저에서 `http://localhost:3000` 접속 → **Microsoft 로그인**
   (`admin@yourtenant.onmicrosoft.com`).
2. 로그인 후 상태 확인:
   - 상태등 초록(mcpConnected), 좌측 도구 목록 **36개** 표시.
   - `GET /api/status` → `signedIn: true`, `mcpConnected: true`.
3. 도구 직접 실행 검증: `ListChannelMessages` 로 채널 메시지 조회
   (`teamId` → `ListTeams`, `channelId` → `ListChannels` 순으로 확보).

---

## 8. 프런트엔드 버그 수정

- **CSS 버그**: `.modal`, `.login-gate`, `.btn` 의 `display` 값이 `hidden` 속성을
  덮어써 팝업/버튼이 항상 표시됨 → `[hidden] { display: none !important; }` 리셋으로 해결.
- **크래시 가드**: 도구 미선택 상태에서 "실행" 클릭 시 `currentTool` null 참조 오류 방지.
- **로그인 게이트**: 미로그인 시 채팅/도구 실행 차단 + 로그인 안내 카드 표시.
- 캐시 방지용 정적 리소스 버전 태그(`?v=2`) 추가.

---

## 9. 자연어 채팅용 LLM 연동 (Azure OpenAI / Foundry, Entra 키리스)

Foundry의 **gpt-5.4** 배포를 **API 키 없이 Entra ID 토큰**으로 연동.

```bash
# 9-1. Foundry 리소스/배포 확인
az cognitiveservices account list \
  --query "[].{name:name,rg:resourceGroup,kind:kind,endpoint:properties.endpoint}" -o table
az cognitiveservices account deployment list -n your-foundry-resource -g your-resource-group \
  --query "[].{deployment:name,model:properties.model.name,version:properties.model.version}" -o table

# 9-2. 데이터플레인 역할 확인 (로그인 사용자 = Foundry User)
az role assignment list \
  --scope "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/your-resource-group/providers/Microsoft.CognitiveServices/accounts/your-foundry-resource" \
  --query "[].{principal:principalName,role:roleDefinitionName}" -o table

# 9-3. Entra 토큰으로 추론 호출 검증
TOKEN=$(az account get-access-token --resource "https://cognitiveservices.azure.com" --query accessToken -o tsv)
curl -s "https://your-foundry-resource.cognitiveservices.azure.com/openai/deployments/gpt-5.4/chat/completions?api-version=2025-04-01-preview" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"say ok"}],"max_completion_tokens":50}'

# 9-4. 의존성 설치
npm install @azure/identity@^4
```

확인 값:
- 리소스: `your-foundry-resource` (rg `your-resource-group`, `eastus2`)
- 엔드포인트: `https://your-foundry-resource.cognitiveservices.azure.com/`
- 배포: `gpt-5.4` (model gpt-5.4, version 2026-03-05)
- API version: `2025-04-01-preview`
- 스코프: `https://cognitiveservices.azure.com/.default`
- 역할: `Foundry User` (추론 호출 정상)

코드 변경:
- `src/agent.js`: `AzureOpenAI` + `DefaultAzureCredential` +
  `getBearerTokenProvider(...)` — 키가 있으면 키, 없으면 Entra 토큰.
- `src/config.js`: `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT` 만으로
  Azure 활성화(키 불필요), `azureTokenScope` 추가.

`.env` (LLM 부분):
```
AZURE_OPENAI_ENDPOINT=https://your-foundry-resource.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-5.4
AZURE_OPENAI_API_VERSION=2025-04-01-preview
AZURE_OPENAI_API_KEY=            # 비움 → Entra ID 인증
```

검증:
- 인프로세스 스모크 테스트로 `entra-ok` 응답 확인.
- 서버 재시작 후 `GET /api/status` → `llm: "azure"`.

---

## 10. 최종 사용 방법

- **도구 직접 실행(LLM 불필요)**: 좌측 도구 클릭 → arguments(JSON) → 실행.
- **자연어 채팅(gpt-5.4)**: "내 Teams 채팅 목록 보여줘",
  "General 채널 메시지 보여줘" 등 입력 → 에이전트가 도구 자동 호출.

> Teams MCP 데이터 접근은 **로그인 사용자 위임 토큰**, LLM 호출은
> **서버 실행 신원(DefaultAzureCredential)** — 두 신원이 분리되어 있습니다.
> 상세 구조는 [`ARCHITECTURE.md`](./ARCHITECTURE.md) 참고.

---

## 부록 — 핵심 식별자 모음

| 항목 | 값 |
|------|----|
| Tenant ID | `00000000-0000-0000-0000-000000000000` |
| 웹앱 Client ID | `11111111-1111-1111-1111-111111111111` |
| MCP 리소스(Agent Tools) appId | `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1` |
| Teams 위임 권한 ID | `5efd4b9c-e459-40d4-a524-35db033b072f` |
| Subscription | `22222222-2222-2222-2222-222222222222` |
| Foundry 리소스 | `your-foundry-resource` (rg `your-resource-group`) |
| LLM 배포 | `gpt-5.4` |
