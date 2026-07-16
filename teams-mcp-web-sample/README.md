# Teams MCP Web Sample

사용자가 웹에서 요청을 입력하면 **Work IQ Teams** MCP 서버(`mcp_TeamsServer`)를 통해
응답을 받는 샘플 웹 앱입니다. Teams 채팅/채널/팀/멤버/메시지 작업만 다룹니다.

```
브라우저(채팅 UI) → Express 서버 → (Entra OAuth 토큰) → Teams MCP (streamable HTTP)
```

## 🚀 빠른 시작 (앱 실행)

사전 준비: **Node.js 18+**, 그리고 아래 [Entra 앱 등록](#사전-준비--entra-앱-등록-필수)이 완료된
`.env` 파일. (이미 이 저장소에는 `.env`가 채워져 있습니다.)

```bash
cd teams-mcp-web-sample
npm install        # 최초 1회 (의존성 설치)
npm start          # http://localhost:3000
```

- 브라우저에서 **http://localhost:3000** 접속 → 우측 상단 **Microsoft 로그인**.
- 로그인 후 좌측에 Teams MCP 도구 목록이 뜨면 정상(상태등 초록).
- 종료: 실행 중인 터미널에서 `Ctrl + C`.

> 로그인/도구 사용법과 문제 해결은 아래 [실행](#실행) 이후 섹션을 참고하세요.
> 전체 구조·인증 흐름은 [`ARCHITECTURE.md`](./ARCHITECTURE.md),
> 연동 작업 순서는 [`SETUP-LOG.md`](./SETUP-LOG.md)에 정리돼 있습니다.

## 아키텍처

| 계층 | 내용 |
|------|------|
| 인증 | Entra ID OAuth 2.0 Authorization Code + PKCE (`@azure/msal-node`) |
| MCP  | `@modelcontextprotocol/sdk` `StreamableHTTPClientTransport` + Bearer 토큰 |
| 서버 | Express, 세션에 토큰 보관 |
| UI   | 바닐라 JS 채팅 + 도구 직접 실행 패널 |
| LLM  | (선택) Azure OpenAI(Foundry) / OpenAI 툴콜링 에이전트 — 없으면 도구 패널만 사용. Azure는 **Entra ID 키리스 인증** 지원 |

> 📐 시스템 구성·인증 모델·요청 흐름(mermaid 다이어그램 포함)은 [`ARCHITECTURE.md`](./ARCHITECTURE.md)를 참고하세요.

대상 MCP 엔드포인트:
```
https://agent365.svc.cloud.microsoft/agents/tenants/00000000-0000-0000-0000-000000000000/servers/mcp_TeamsServer
```
- 인증 서버: `https://login.microsoftonline.com/organizations/v2.0`
- 스코프: `<resource>/.default` (+ `offline_access`)

## 사전 준비 — Entra 앱 등록 (필수)

이 MCP 리소스는 커스텀 API라서 **본인 테넌트의 앱 등록(App registration)** 이 필요합니다.

1. [Entra 관리 센터](https://entra.microsoft.com) → **App registrations → New registration**
   - Redirect URI: **Web** 유형, `http://localhost:3000/auth/callback`
2. 등록 후 **Application (client) ID** 를 복사 → `.env`의 `CLIENT_ID`.
3. **API permissions → Add a permission → APIs my organization uses** 에서
   `mcp_TeamsServer`(또는 `agent365` / Work IQ Teams 리소스)를 찾아 **위임(Delegated)** 권한 추가.
4. **Grant admin consent** 클릭(테넌트 관리자 필요할 수 있음).
5. (공개 클라이언트로 쓸 경우) **Authentication → Allow public client flows** 를 켜거나,
   비밀 클라이언트로 쓰려면 **Certificates & secrets** 에서 secret 생성 후 `.env`의 `CLIENT_SECRET`.

> 참고: 조직 정책상 해당 리소스가 "APIs my organization uses"에 안 보이면
> 관리자에게 Work IQ Teams(preview) 노출/동의를 요청해야 합니다.

## 실행

```bash
cd teams-mcp-web-sample
cp .env.example .env      # CLIENT_ID 등 채우기
npm install
npm start                 # http://localhost:3000
```

1. 브라우저에서 `http://localhost:3000` → **Microsoft 로그인**.
2. 로그인되면 좌측에 Teams MCP 도구 목록이 뜹니다(연결 표시등이 초록).
3. 사용 방법:
   - **도구 직접 실행(LLM 불필요):** 좌측 도구 클릭 → arguments(JSON) 입력 → 실행.
   - **자연어 채팅(LLM 필요):** `.env`에 Azure OpenAI 또는 OpenAI 키를 넣으면
     "내 Teams 채팅 목록 보여줘" 같은 문장으로 요청 가능.

## 자연어 채팅용 LLM (선택)

`.env`에서 아래 중 하나를 설정하세요.

**Azure OpenAI (Foundry) — Entra ID 키리스 인증 (권장)**
```
AZURE_OPENAI_ENDPOINT=https://<your>.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT=<배포 이름, 예: gpt-5.4>
AZURE_OPENAI_API_VERSION=2025-04-01-preview
# AZURE_OPENAI_API_KEY 는 비워둡니다 → Entra ID 인증 사용
```
- 키를 비우면 서버 실행 신원(`DefaultAzureCredential`: 로컬은 `az login`,
  배포는 Managed Identity)으로 토큰을 발급해 호출합니다.
- 해당 신원에 Foundry 리소스의 데이터플레인 역할
  (`Cognitive Services OpenAI User` 또는 `Foundry User`)이 필요합니다.
- 키를 쓰고 싶다면 `AZURE_OPENAI_API_KEY` 를 채우면 키 인증으로 동작합니다.

**OpenAI**
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

미설정 시 채팅창은 안내 메시지만 표시하고, 도구 패널은 정상 동작합니다.

## 제공 도구 (mcp_TeamsServer)

- **채팅:** createChat, getChat, updateChat, deleteChat, listChats, addChatMember,
  listChatMembers, postMessage, getChatMessage, listChatMessages, updateChatMessage,
  deleteChatMessage
- **팀/채널:** getTeam, listTeams, createChannel, createPrivateChannel, getChannel,
  updateChannel, listChannels, listChannelMembers, addChannelMember, updateChannelMember,
  postChannelMessage, listChannelMessages, replyToChannelMessage

(실제 노출되는 도구/이름은 서버 preview 버전에 따라 다를 수 있습니다. 좌측 목록이 실제 값입니다.)

## API 라우트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET  | `/auth/login` | Entra 로그인 시작 |
| GET  | `/auth/callback` | 코드 교환 |
| POST | `/auth/logout` | 로그아웃 |
| GET  | `/api/status` | 로그인/MCP 연결/도구 수 |
| GET  | `/api/tools` | MCP 도구 목록 |
| POST | `/api/tool` | `{name, args}` 도구 직접 호출 |
| POST | `/api/chat` | `{message}` 자연어 에이전트 |

## 문제 해결

- **401 / 로그인 후에도 연결 안 됨:** 앱 등록의 API 권한 + admin consent 확인.
  스코프가 `<resource>/.default`라서 권한이 사전 구성돼 있어야 합니다.
- **`invalid_client` / redirect 오류:** Redirect URI가 `http://localhost:3000/auth/callback`와
  정확히 일치하는지, `REDIRECT_URI`/`PORT`가 맞는지 확인.
- **`AADSTS65001` (동의 필요):** 관리자 동의(Grant admin consent) 미완료.
- **도구 목록이 비어 있음:** 토큰은 발급됐지만 리소스 권한 부족 — 위임 권한/consent 재확인.

> 이 Teams MCP 서버는 **preview** 기능입니다. 도구 이름·파라미터가 변경될 수 있으니
> 하드코딩하지 말고 `/api/tools` 결과를 사용하세요.
