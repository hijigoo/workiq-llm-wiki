# Work IQ Mail MCP 연동 작업 정리 (순서대로)

이 문서는 **Work IQ Mail MCP 서버(`mcp_MailTools`)** 를 샘플 웹 앱에 연동한 **실제 작업 기록**입니다.
동일 구조의 `teams-mcp-web-sample`을 Mail MCP로 옮긴 버전이며, **Entra 앱은 새로 만들지 않고
기존 `teams-mcp-web-sample` 앱 등록을 그대로 재사용**했습니다(Teams·Mail 모두 같은 "Agent Tools"
리소스라 토큰 audience가 동일). 다만 Mail MCP는 **`McpServers.Mail.All` 위임 권한을 별도로
추가·동의**해야 동작합니다. 또한 기본 포트를 3000 → **3001** 로 변경했습니다.

- 테넌트: `YOURTENANT` / `00000000-0000-0000-0000-000000000000`
- 관리자 계정: `admin@yourtenant.onmicrosoft.com`
- 재사용 앱: **Teams MCP Web Sample**, Client ID `11111111-1111-1111-1111-111111111111`
- 결과물: `mail-mcp-web-sample/` (Express + Vanilla JS), 포트 **3001**

> `{tenantId}` = `00000000-0000-0000-0000-000000000000`
> client secret 등 비밀값은 문서에 포함하지 않고 `.env`(gitignore)에만 저장합니다.

---

## 0. 목표 정의

- 일반 WorkIQ MCP(`https://workiq.svc.cloud.microsoft/mcp`, 전체 M365)가 아니라,
  **Mail 전용** MCP 서버(`mcp_MailTools`)만 사용.
- 사용자가 웹에서 요청 → Mail MCP를 통해 응답받는 별도 샘플 웹 구축.

참고 문서: <https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-mail-work-iq>

| 항목 | 값 |
|------|-----|
| Server ID | `mcp_MailTools` |
| 엔드포인트 | `https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_MailTools` |
| 스코프 | `McpServers.Mail.All` (preview — 실제 명칭은 테넌트에서 확인) |
| 상태 | Preview |

---

## 1. 엔드포인트 인증 요건 파악

MCP 엔드포인트에 인증 없이 요청 → **401** 과 함께 OAuth 메타데이터 위치 확인.

```bash
# 401 + www-authenticate 확인
curl -i -X POST \
  "https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_MailTools"

# 보호 리소스 메타데이터
curl -s "https://agent365.svc.cloud.microsoft/.well-known/oauth-protected-resource/agents/tenants/{tenantId}/servers/mcp_MailTools"
```

확인된 사항:
- 인증 서버: `https://login.microsoftonline.com/organizations/v2.0`
- 스코프: `<resource>/.default` (+ `openid profile offline_access`)
- 토큰 전달: `Authorization: Bearer` 헤더
- 리소스는 Entra에서 **Agent Tools** 앱으로 해석됨
  - appId `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`
  - identifierUri `https://agent365.svc.cloud.microsoft`
  - Mail 위임 권한 `McpServers.Mail.All` = `<mail-delegated-permission-id>` (테넌트에서 확인)

---

## 2. Entra 앱 등록 — 기존 앱 재사용

**새 앱을 만들지 않고** 기존 `teams-mcp-web-sample`용 앱 등록을 그대로 사용했습니다.
Teams·Mail MCP 서버는 동일한 **Agent Tools**(`agent365`) 리소스 앱에 속하므로
토큰 audience가 이미 일치해 앱을 재사용할 수 있습니다.

- 재사용 앱: **Teams MCP Web Sample**
- Application (client) ID: `11111111-1111-1111-1111-111111111111`
- client secret: 기존 앱의 secret을 그대로 `.env`에 사용(confidential 클라이언트)

포트를 3000 → **3001** 로 바꿨기 때문에, 기존 앱의 **Authentication → Redirect URIs** 에
`http://localhost:3001/auth/callback` 를 **추가**했습니다(기존 3000용은 유지 가능).

> 새 앱으로 진행하려면:
> ```bash
> az ad app create --display-name "Mail MCP Web Sample" \
>   --web-redirect-uris "http://localhost:3001/auth/callback"
> az ad sp create --id <appId>
> az ad app credential reset --id <appId>   # secret은 .env로만 저장
> ```

---

## 3. Mail 위임 권한 추가 + 관리자 동의 (핵심)

재사용한 앱에는 `McpServers.**Teams**.All` 만 동의돼 있어, 그대로 로그인하면 Mail MCP가
아래 오류로 거부합니다.

```
Forbidden — Access denied: Scope 'McpServers.Mail.All' is not present in the request.
```

`.default` 스코프는 **앱에 사전 동의된 권한만** 토큰(`scp`)에 담기 때문입니다. 따라서 기존 앱에
`McpServers.Mail.All` 을 추가로 동의해야 합니다.

**포털(이번에 실제 사용한 방법):**
1. Entra 관리센터 → App registrations → `72848081-…499c`
2. **API permissions → Add a permission → APIs my organization uses**
3. `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`(Agent Tools / `agent365`) 검색 →
   **Delegated** → `McpServers.Mail.All` 추가
4. **Grant admin consent for <테넌트>** 클릭
5. 앱에서 **로그아웃 후 재로그인** (새 토큰에 스코프 반영)

**az CLI(대안):**
```bash
az ad app permission add --id 11111111-1111-1111-1111-111111111111 \
  --api ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --api-permissions <mail-delegated-permission-id>=Scope
az ad app permission admin-consent --id 11111111-1111-1111-1111-111111111111
```

검증: 동의 후 재로그인하면 토큰 `scp` 에 `McpServers.Mail.All` 포함 →
`GET /api/status` 의 `mcpConnected: true`, 좌측 도구 목록(약 10종) 표시.

---

## 4. 토큰 audience 수용 확인

앱-전용(client_credentials) 토큰으로 호출해 **audience가 수용되는지** 확인.

```bash
# 토큰 발급
curl -s -X POST "https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token" \
  -d "client_id=<appId>" \
  --data-urlencode "client_secret=<secret>" \
  -d "grant_type=client_credentials" \
  --data-urlencode "scope=https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_MailTools/.default"
```

- 결과: **403** `Access denied: Scope 'McpServers.Mail.All' is not present in the request`
- 해석: **audience는 수용됨**, 다만 앱-전용 토큰엔 위임 `scp`가 없음
  → **사용자 로그인(위임)** 으로 `.default`를 받으면 `scp: McpServers.Mail.All` 포함되어 정상 동작.

---

## 5. 샘플 웹 앱 구축

`mail-mcp-web-sample/` 생성 (Node.js ESM + Express).

```
src/config.js   # .env 로드, 스코프(<MCP_URL>/.default), llmProvider()
src/auth.js     # MSAL Authorization Code + PKCE, 무음 토큰 갱신
src/mcp.js      # @modelcontextprotocol/sdk StreamableHTTP 클라이언트(Bearer 부착)
src/agent.js    # (선택) LLM 툴콜링 루프
src/server.js   # Express 라우트 + 정적 서빙
public/         # 채팅 UI + 도구 직접 실행 패널
```

```bash
cd mail-mcp-web-sample
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
| `CLIENT_ID` | `11111111-1111-1111-1111-111111111111` (기존 Teams 앱 재사용) |
| `CLIENT_SECRET` | 기존 Teams 앱의 secret (비공개, `.env`에만 저장) |
| `MCP_SERVER_URL` | `https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_MailTools` |
| `REDIRECT_URI` | `http://localhost:3001/auth/callback` |
| `SESSION_SECRET` | (랜덤 문자열) |

---

## 7. 실행 & 로그인 검증

```bash
npm start   # http://localhost:3001
```

1. 브라우저에서 `http://localhost:3001` 접속 → **Microsoft 로그인**
   (`admin@yourtenant.onmicrosoft.com`).
2. 로그인 후 상태 확인:
   - 상태등 초록(mcpConnected), 좌측에 메일 도구 목록(약 10종) 표시.
   - `GET /api/status` → `signedIn: true`, `mcpConnected: true`.
3. 도구 직접 실행 검증: `mcp_MailTools_graph_mail_searchMessages` 로 메일 검색
   (또는 `listSent` 로 보낸 편지함 조회 → 반환된 `id` 로 `getMessage` 확인).

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
- **자연어 채팅(gpt-5.4)**: "안 읽은 메일 검색해줘",
  "○○에게 회신 보내줘" 등 입력 → 에이전트가 도구 자동 호출.

> Mail MCP 데이터 접근은 **로그인 사용자 위임 토큰**, LLM 호출은
> **서버 실행 신원(DefaultAzureCredential)** — 두 신원이 분리되어 있습니다.
> 상세 구조는 [`ARCHITECTURE.md`](./ARCHITECTURE.md) 참고.

---

## 부록 — 핵심 식별자 모음

| 항목 | 값 |
|------|----|
| Tenant ID | `00000000-0000-0000-0000-000000000000` |
| 웹앱 Client ID | `11111111-1111-1111-1111-111111111111` (기존 Teams 앱 재사용) |
| MCP 리소스(Agent Tools) appId | `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1` |
| Mail 위임 권한 | `McpServers.Mail.All` (포털에서 추가·관리자 동의) |
| Subscription | `22222222-2222-2222-2222-222222222222` |
| Foundry 리소스 | `your-foundry-resource` (rg `your-resource-group`) |
| LLM 배포 | `gpt-5.4` |
