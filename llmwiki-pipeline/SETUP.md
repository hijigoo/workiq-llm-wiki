# SETUP.md — 테넌트 / Entra ID 상세 설정 & 문제 해결

이 문서는 `README.md`의 빠른 경로를 넘어, **신규 테넌트에서 처음부터** LLM Wiki Pipeline을
동작시키는 데 필요한 Entra ID(앱 등록·권한·동의) 설정과 흔한 오류 해결을 다룹니다.

> 이 프로젝트는 `../samples/{teams,mail}-mcp-web-sample`의 실제 연동 기록(`SETUP-LOG.md`)을
> 기반으로 합니다. 샘플은 웹 리다이렉트를 쓰는 **authorization-code + PKCE(기밀 클라이언트)**
> 였고, 이 파이썬 파이프라인은 **device-code(공개 클라이언트)** 를 기본으로 씁니다.

---

## 0. 핵심 식별자

| 항목 | 값 |
|------|----|
| MCP 리소스 앱 (**Agent Tools**) appId | `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1` |
| Agent Tools identifierUri (토큰 audience) | `https://agent365.svc.cloud.microsoft` |
| Teams 위임 권한 `McpServers.Teams.All` (permission ID) | `5efd4b9c-e459-40d4-a524-35db033b072f` |
| Mail 위임 권한 `McpServers.Mail.All` (permission ID) | **테넌트별로 다름** — 아래 3-B에서 조회 |
| Teams 서버 ID / URL | `mcp_TeamsServer` — `.../tenants/<TENANT_ID>/servers/mcp_TeamsServer` |
| Mail 서버 ID / URL | `mcp_MailTools` — `.../tenants/<TENANT_ID>/servers/mcp_MailTools` |
| 인증 서버 | `https://login.microsoftonline.com/organizations/v2.0` |
| 코드가 요청하는 스코프 | `<mcp_server_url>/.default` (소스별) |

참고 문서:
- Teams: <https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-teams-work-iq>
- Mail: <https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-mail-work-iq>

---

## 1. 사전 요건 (막히면 대개 여기)

- 테넌트에 Work IQ MCP가 **프로비저닝**되어 있어야 합니다. `az ad sp` 조회(3-A)에서 Agent Tools
  서비스 주체가 **없거나** 스코프가 없으면, 이는 ID를 추측해 해결할 문제가 아니라 **테넌트
  프로비저닝/가용성 문제**입니다 — 관리자/담당자에게 확인하세요.
- 로그인 계정에 **Exchange Online 사서함**(Mail)과 **Teams 접근**(Teams: 팀/채팅 멤버십)이 있어야
  실제 데이터가 조회됩니다.
- **관리자 동의** 권한: 일반적으로 Cloud Administrator 또는 Application Administrator면 이 위임
  권한 동의가 가능합니다(테넌트 정책이 더 엄격할 수 있음).
- 라이선스/과금: Work IQ 미리보기는 표면(surface)마다 요건이 다릅니다(Copilot Studio 미리보기는
  Microsoft 365 Copilot 라이선스를, 최신 Work IQ CLI 가이드는 사용량 기반 과금과 사용자 할당을
  언급). **하나의 라이선스로 단정하지 말고** 위 Learn 문서로 현재 표면의 요건을 확인하세요.

---

## 2. (선택) 엔드포인트 인증 요건 확인 — 401 프로브

메타데이터로 인증 서버/스코프를 직접 확인하고 싶을 때:

```bash
TENANT_ID=<your-tenant-id>

# 401 + www-authenticate 헤더 확인
curl -i -X POST \
  "https://agent365.svc.cloud.microsoft/agents/tenants/$TENANT_ID/servers/mcp_TeamsServer"

# 보호 리소스 메타데이터 (authorization_servers, scopes 등)
curl -s "https://agent365.svc.cloud.microsoft/.well-known/oauth-protected-resource/agents/tenants/$TENANT_ID/servers/mcp_TeamsServer"
```

---

## 3. 앱 등록 · 권한 · 동의

### 3-A. 전용 앱 등록 만들기

```bash
az login --tenant "$TENANT_ID"

az ad app create --display-name "LLM Wiki Pipeline" --sign-in-audience AzureADMyOrg
CLIENT_ID=<appId>

# 이 테넌트에 클라이언트 서비스 주체(= Enterprise Application) 생성
az ad sp create --id "$CLIENT_ID"
```

> **왜 전용 앱?** 운영 중인 기밀(웹) 앱을 그대로 공개 클라이언트로 바꾸지 마세요. 공개/기밀
> 흐름은 공존 가능하지만, 의도치 않게 보안 자세를 바꿀 수 있습니다.

**device-code(공개 클라이언트) 활성화 — 필수:**

```bash
az ad app update --id "$CLIENT_ID" --is-fallback-public-client true
az ad app show  --id "$CLIENT_ID" --query isFallbackPublicClient -o tsv   # → true
```

- device-code에는 **redirect URI, client secret, implicit-grant 체크박스, Web 플랫폼 설정이
  필요 없습니다.** (`--is-fallback-public-client true`가 첫 번째 선택지이며, 일반 `--set`보다 명확)

### 3-B. Agent Tools 서비스 주체와 Mail 권한 ID 조회

```bash
# Agent Tools 서비스 주체 확인 (없으면 테넌트 프로비저닝 문제 — 1번 참고)
az ad sp show --id ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --query "{name:displayName, appId:appId}" -o table

# 위임 스코프 목록에서 Mail 권한 ID 찾기
az ad sp show --id ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --query "oauth2PermissionScopes[].{value:value, id:id}" -o table
# → value == 'McpServers.Mail.All' 행의 id 를 사용
MAIL_PERM_ID=<위에서 찾은 id>
TEAMS_PERM_ID=5efd4b9c-e459-40d4-a524-35db033b072f
```

### 3-C. 위임 권한 추가 + 관리자 동의

```bash
az ad app permission add --id "$CLIENT_ID" \
  --api ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --api-permissions "$TEAMS_PERM_ID=Scope" "$MAIL_PERM_ID=Scope"

az ad app permission admin-consent --id "$CLIENT_ID"
```

**포털 방식(대안):** Entra 관리센터 → App registrations → 내 앱 → **API permissions →
Add a permission → APIs my organization uses** → `ea9ffc3e-...`(Agent Tools) 검색 →
**Delegated** → `McpServers.Teams.All`, `McpServers.Mail.All` 선택 → 추가 →
**Grant admin consent for \<테넌트\>**.

### 3-D. 동의 검증

```bash
# 클라이언트 SP의 objectId
CLIENT_SP=$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)

# 클라이언트↔리소스 사이에 부여된 위임 스코프(oauth2PermissionGrant) 확인
az rest --method GET \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$CLIENT_SP/oauth2PermissionGrants" \
  --query "value[].scope" -o tsv
# → 'McpServers.Teams.All McpServers.Mail.All' 이 보이면 정상
```

> **용어 정리**
> - **Enterprise Application = 클라이언트의 서비스 주체(SP)** 자체입니다. 관리자 동의는 SP를
>   "생성"한다기보다, **클라이언트 SP와 리소스 SP 사이의 `oauth2PermissionGrant`를
>   생성/갱신**합니다.
> - **`.default`** 는 앱에 **정적으로 구성된 권한**을 요청하고, **실제로 부여된 위임 스코프**를
>   토큰에 담습니다. 이 리소스에서는 관리자 동의가 신뢰할 수 있는 경로입니다.
> - Mail/Teams는 **서로 다른 보호 리소스 URL·스코프 문자열**이지만 **하나의 Entra 리소스 앱
>   (동일 audience)** 입니다. 따라서 토큰의 유효성은 `aud` + 포함된 `scp` 에 달려 있습니다 —
>   Mail 스코프만 든 토큰은 Teams 서버에서 스코프 부족으로 거부됩니다(그 반대도 동일).

---

## 4. Enterprise Application 추가 점검

- **Assignment required?** 이 값이 *Yes* 이면 사용자/그룹이 앱에 **할당**되어야 로그인됩니다.
  Entra 관리센터 → Enterprise applications → 내 앱 → **Properties / Users and groups**.
- **Conditional Access(조건부 액세스)** 정책이 device-code 흐름을 차단할 수 있습니다. 차단되면
  관리자와 예외/대체 흐름을 협의하세요. (이때 `client_credentials`는 위임 스코프만 있는 환경에서
  **믿을 만한 대체가 아닙니다** — 5번 참고.)
- **동의 전파 지연**: 권한/동의 변경이 반영되기까지 수 분 걸릴 수 있습니다.

---

## 5. `client_credentials`(앱 전용)에 대하여 — 고급 / 대개 불가

- `AUTH_MODE=client_credentials` + `CLIENT_SECRET` 로 앱 전용 토큰을 시도할 수 있지만,
  이는 Agent Tools가 **애플리케이션 역할(app roles)** 을 노출하고 테넌트가 그것을 부여한
  경우에만 동작합니다.
- **위임 스코프(McpServers.*.All)만 있는 상태**에서는 secret이 있어도 동작하지 않습니다. 앱 전용
  토큰에는 위임 `scp`가 없어 서버가 `403 Access denied: Scope '...' is not present` 로 거부합니다.
  (샘플 `SETUP-LOG.md`의 4단계에서 실측: audience는 수용되나 위임 scp 부재로 403.)
- 요약: 대부분의 테넌트에서는 **device-code(위임)** 를 사용하세요.

---

## 6. 로그인 · 검증 (device-code)

1. 노트북 `01_setup_mcp.ipynb` 실행 → 소스별 로그인 메시지(`https://microsoft.com/devicelogin`
   + 코드) 출력 → 브라우저에서 로그인.
2. 성공 시 `.token_cache.json` 생성. 이후 노트북·웹앱이 조용히 재사용.
3. 툴 목록이 조회되면(예: Teams 수십 종, Mail 약 10종) 연결 정상.
4. 웹앱: `cd app && uvicorn main:app --reload` 후 `GET /api/status` 로 `llm`/소스 상태 확인.

**권한을 바꾼 뒤(재동의 포함)에는 반드시 토큰을 새로 발급:**

```bash
# 앱/노트북을 종료한 뒤
rm -f .token_cache.json
# 01 노트북(또는 터미널 로그인)으로 다시 로그인
```

> 이 프로젝트에는 "로그아웃" 명령이 없습니다. **캐시 파일을 삭제**하는 것이 곧 재로그인 절차입니다.
> `.token_cache.json`은 자격증명처럼 취급하세요(`chmod 600`, 커밋 금지 — 이미 gitignore됨).

---

## 7. 문제 해결 (증상 → 원인/조치)

| 증상 | 원인 / 조치 |
|------|-------------|
| 로그인 시 `AADSTS7000218` / "client_assertion or client_secret" 요구 | 공개 클라이언트 흐름 미활성화. 3-A의 `--is-fallback-public-client true` 적용 후 재로그인. |
| MCP 호출 `403 Scope 'McpServers.Mail.All' is not present` | 해당 위임 권한 미동의(또는 동의 후 토큰 미갱신). 3-C 동의 → `.token_cache.json` 삭제 → 재로그인. |
| MCP 호출 `401 Unauthorized` | 토큰 만료/부재. 재로그인. URL의 `TENANT_ID`가 맞는지 확인. |
| 툴은 뜨는데 데이터가 비어 있음 | 계정에 사서함/Teams 멤버십/데이터가 없거나 날짜 범위 밖. 계정·범위 확인. |
| 모든 요청이 all-zero 테넌트로 감 | `.env`의 `TENANT_ID` 미설정 또는 URL을 옛 placeholder로 하드코딩. URL은 **비워서** 자동 파생시키세요. |
| device-code가 정책에 막힘 | Conditional Access. 관리자와 협의(4번). |
| `az ad sp show ea9ffc3e-...` 결과 없음 | 테넌트에 Agent Tools 미프로비저닝(1번) — ID 추측 금지. |
| `llm: null` (초안 생성 안 됨) | LLM 미설정. `.env`에 OpenAI 키 또는 Azure 엔드포인트+배포(+역할) 설정. |

---

## 8. LLM 신원(중요)

- MCP 데이터 접근 = **로그인 사용자 위임 토큰(M365)**.
- LLM 호출 = **별개의 신원**. Azure OpenAI는 키가 없으면 `DefaultAzureCredential`(예: `az login`,
  관리 ID)로 인증하며, 그 신원에 데이터플레인 역할(예: *Cognitive Services OpenAI User* /
  *Foundry User*, 스코프 `https://cognitiveservices.azure.com/.default`)이 필요합니다.
- 공개 OpenAI(`OPENAI_API_KEY`)를 쓰면 추출된 **업무 데이터가 외부 제공자로 전송**됩니다 —
  조직의 데이터 정책 준수 여부를 반드시 확인하세요.
