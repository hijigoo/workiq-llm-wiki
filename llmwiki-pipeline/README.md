# LLM Wiki Pipeline

Teams와 Mail(Microsoft Work IQ **MCP** 서버)에서 **기술·노하우를 자연어로 추출**해
**Markdown 위키 문서**로 만들고, 사용자가 검토·수정 후 커밋하면 이 레포의 `app/wiki/`에
반영되는 파이프라인입니다.

```
자연어 질의 + 날짜 범위
   → extract   (에이전트가 Teams/Mail MCP에서 관련 데이터만 취합)
   → generate  (LLM이 위키 Markdown 초안 생성)
   → review    (웹 UI 또는 노트북에서 검토·수정)
   → commit    (app/wiki/ 에 저장 + git commit — 해당 문서만)
```

> ⚠️ **로컬·단일 사용자 전용.** 웹앱에는 자체 로그인이 없고, 캐시된 **하나의**
> Microsoft 365 신원으로 동작합니다. 서버에 접근할 수 있는 사람은 누구나 그 신원으로
> 데이터를 읽고 커밋할 수 있으니, **loopback(127.0.0.1) 밖으로 노출하지 마세요.**
> 다중 사용자 배포는 사용자별 로그인(authorization-code)과 토큰 격리가 별도로 필요합니다.

---

## 폴더 구조

```
llmwiki-pipeline/
├─ app/
│  ├─ main.py             # FastAPI: 실행/초안/수정/커밋
│  ├─ pipeline/           # 공유 패키지 (app + notebook 공용)
│  │   config·auth·mcp_client·agent·extract·generate·wiki·pipeline
│  ├─ static/             # 리뷰/수정/커밋 웹 UI
│  └─ wiki/               # 생성 문서 출력(커밋 대상)
├─ notebook/
│  ├─ 01_setup_mcp.ipynb          # 연결·인증·툴 목록 (먼저 실행)
│  ├─ 02_seed_sample_data.ipynb   # write 도구로 샘플 전송
│  ├─ 03_fetch_data.ipynb         # (Agent365) MCP 툴 직접 호출
│  ├─ 04_nl_aggregate_to_md.ipynb # (Agent365) 자연어 취합 → Markdown
│  ├─ 05_workiq_fetch_data.ipynb      # (Work IQ MCP) 범용 툴 직접 호출
│  └─ 06_workiq_aggregate_to_md.ipynb # (Work IQ MCP) 자연어 취합 → Markdown
├─ .env.example
├─ requirements.txt
├─ SETUP.md               # 테넌트/Entra 상세 설정 · 문제 해결
└─ README.md
```

---

## 사전 준비 (체크리스트)

- **Python 3.10+** (검증은 3.13). `mcp` 패키지가 3.10 미만을 지원하지 않습니다.
- **테넌트에 Work IQ MCP가 프로비저닝**되어 있고 Mail/Teams 서버(**Agent Tools** 리소스)가 노출됨.
- **로그인 계정**에 사용 가능한 **Exchange 사서함**과 **Teams 접근 권한**(팀/채팅 멤버십)이 있음.
- **관리자 동의** 가능한 사람(예: Cloud/Application Administrator) 확보.
- Work IQ 미리보기의 **라이선스/과금** 요건 충족 — 표면(surface)마다 다르니
  [Learn 문서](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-teams-work-iq)로 확인.
- **LLM**: OpenAI API 키 **또는** Azure OpenAI(Foundry) 엔드포인트+배포.

---

## 설치

```bash
cd llmwiki-pipeline
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # 값 채우기 (아래 + SETUP.md)
```

---

## Entra ID 설정 (빠른 경로)

인증 방법은 두 가지이며 **기본은 방법 1(device-code)** 입니다. 노트북 `01`에서 셀 한 줄로 바꿀 수 있고,
영구 변경은 `.env`의 `AUTH_MODE`로 합니다.

- **방법 1 — device-code(위임, 권장·기본):** 사용자 1회 로그인. 앱 등록에 **공개 클라이언트 흐름**이 필요합니다.
- **방법 2 — client_credentials(앱 전용):** `CLIENT_SECRET` + 애플리케이션 권한(관리자 동의) 필요. 위임 스코프만 허용된 테넌트에서는 대부분 실패합니다(고급 옵션).

아래는 방법 1 최소 happy-path이고, 포털 방식·권한 ID 조회·문제 해결은 **[SETUP.md](./SETUP.md)** 를 보세요.

```bash
az login --tenant <TENANT_ID>

# 1) 전용 앱 등록 (단일 테넌트). 이 한 앱이 Mail·Teams 둘 다 커버합니다.
az ad app create --display-name "LLM Wiki Pipeline" --sign-in-audience AzureADMyOrg
CLIENT_ID=<위 출력의 appId>
az ad sp create --id "$CLIENT_ID"

# 2) device-code용 공개 클라이언트 흐름 허용 (필수)
az ad app update --id "$CLIENT_ID" --is-fallback-public-client true
az ad app show  --id "$CLIENT_ID" --query isFallbackPublicClient -o tsv   # → true

# 3) Agent Tools(ea9ffc3e-8a23-4a7d-836d-234d7c7565c1) 위임 권한 + 관리자 동의
#    Teams 권한 ID = 5efd4b9c-e459-40d4-a524-35db033b072f
#    Mail 권한 ID = 테넌트별로 다름 → 조회 방법은 SETUP.md
az ad app permission add --id "$CLIENT_ID" \
  --api ea9ffc3e-8a23-4a7d-836d-234d7c7565c1 \
  --api-permissions 5efd4b9c-e459-40d4-a524-35db033b072f=Scope
# (Mail 권한도 동일하게 add 후)
az ad app permission admin-consent --id "$CLIENT_ID"
```

- device-code는 **redirect URI도, client secret도 필요 없습니다.**
- `.default` 스코프는 **관리자 동의된 위임 권한만** 토큰에 담습니다. 권한을 추가·동의한 뒤에는
  `.token_cache.json`을 지우고 다시 로그인하세요.
- `client_credentials`(앱 전용)는 고급 옵션이며 대부분의 테넌트에서 동작하지 않습니다(SETUP.md 참고).

**문제 해결 — 로그인은 성공했는데 `AADSTS7000218: ... 'client_assertion' or 'client_secret'` 오류가 뜬다면**
공개 클라이언트 흐름이 꺼져 있는 것입니다(방법 1). 위 CLI(2번) 또는 포털에서 켜세요:

> **Entra/Azure Portal → App registrations**(앱 등록) → *CLIENT_ID와 일치하는 앱* →
> **Manage → Authentication → Advanced settings → "Allow public client flows" → Yes → Save**
>
> ⚠️ **App registrations**(애플리케이션 개체)에서만 이 옵션이 보입니다. **Enterprise applications**
> (서비스 주체)에는 Authentication 메뉴가 없습니다.

`.env`의 핵심 항목:

| 변수 | 설명 |
|------|------|
| `TENANT_ID` | 테넌트(디렉터리) ID |
| `CLIENT_ID` | 위에서 만든 앱의 Application(client) ID |
| `AUTH_MODE` | `device_code`(기본, 권장) 또는 `client_credentials` |
| `MAIL_MCP_SERVER_URL` / `TEAMS_MCP_SERVER_URL` | **비워두면 TENANT_ID로 자동 구성** |
| LLM (택1) | OpenAI: `OPENAI_API_KEY` / Azure: `AZURE_OPENAI_ENDPOINT`+`AZURE_OPENAI_DEPLOYMENT` |

> LLM 신원은 MCP용 M365 위임 신원과 **분리**됩니다. Azure는 키가 없으면
> `DefaultAzureCredential`(`az login`)로 인증하며 데이터플레인 역할(예: *Cognitive Services
> OpenAI User*)이 필요합니다. 공개 OpenAI를 쓰면 추출된 업무 데이터가 외부로 전송되니
> 조직 정책을 확인하세요.

---

## 사용 순서

### 1) 노트북으로 셋업·검증 (`.venv` 커널, 번호 순서대로)

1. `01_setup_mcp.ipynb` — 로그인(1회, device-code) + MCP 툴 목록 확인 → 토큰 캐시 생성
2. `02_seed_sample_data.ipynb` — 샘플 기술/노하우 메일·Teams 메시지 전송(실데이터 write)
3. `03_fetch_data.ipynb` — MCP 툴 직접 호출로 데이터 조회
4. `04_nl_aggregate_to_md.ipynb` — 자연어 취합 → Markdown 생성(선택적 저장/커밋)

**Work IQ MCP 변형(선택)** — 위 `03`·`04`는 Agent365(메일/Teams **개별** 서버, 소스별 도구)를
쓰고, 아래 `05`·`06`은 **Work IQ MCP**(단일 엔드포인트 + `fetch`/`search_paths`/`ask` 범용 도구)를
씁니다. 흐름은 같으므로 환경에 맞는 쪽을 고르면 됩니다.

5. `05_workiq_fetch_data.ipynb` — Work IQ MCP 범용 툴 직접 호출로 데이터 조회
6. `06_workiq_aggregate_to_md.ipynb` — Work IQ `ask`(기본) 또는 에이전트 루프로 취합 → Markdown

```bash
source .venv/bin/activate
python -m ipykernel install --user --name llmwiki-pipeline --display-name "Python (llmwiki-pipeline)"
jupyter lab        # 또는 VS Code에서 .venv 커널 선택
```

### 2) 웹앱으로 리뷰·커밋

`01`에서 로그인이 끝나 토큰 캐시가 생기면 실행:

```bash
cd app
uvicorn main:app --reload --port 8000     # http://localhost:8000
```

UI: **주제(자연어) + 날짜 범위 + 소스 선택 → 실행 → 초안 검토·수정 → 커밋.**
커밋 시 `app/wiki/{YYYY-MM-DD}-{slug}.md`로 저장되고 **그 파일만** 이 레포에 커밋됩니다.
엔드포인트: `GET /api/status`, `POST /api/run`, `POST /api/commit`, `GET /api/docs`, `GET /api/docs/{filename}`.

---

## 데일리 실행(자동화)

기본은 **수동 실행 + 날짜 범위 지정**입니다. 매일 자동화하려면 `04` 노트북 흐름을 스크립트로
감싸 스케줄러에 등록하세요(예: 매일 09:00, 최근 1일).

```cron
# crontab -e  (venv 파이썬 절대경로 사용)
0 9 * * *  cd /path/to/llmwiki-pipeline && \
  .venv/bin/python -c "import asyncio,sys; sys.path.insert(0,'app'); \
  from pipeline import pipeline, wiki; \
  r=asyncio.run(pipeline.run_pipeline('어제의 기술 노하우 요약')); \
  d=r['doc']; print(wiki.save_and_commit(d['markdown'], d['slug']) if d else ('no doc:', r))"
```

> 자동 커밋을 원치 않으면 `save_and_commit` 대신 `wiki.save_doc(...)`으로 초안만 남기고
> 사람이 검토 후 커밋하세요. (device-code 토큰 만료 시 무인 실행은 실패할 수 있음 → 재로그인 필요.)

---

## 안전 규칙

- **로컬 전용**: 위 보안 경고를 지키세요(loopback 밖 노출 금지).
- **소스별 토큰**: Mail/Teams는 같은 Agent Tools 리소스지만 서버별 위임 스코프가 달라 토큰을
  섞지 않고 소스별로 발급합니다(에이전트는 `mail__*` / `teams__*` 네임스페이스로만 라우팅).
- **날조 금지**: 시스템 프롬프트가 실제 ID/데이터만 쓰도록 지시합니다.
- **비밀정보**: `.env`, `.token_cache.json`은 gitignore 됨. 커밋 금지, `.token_cache.json`은
  자격증명처럼 취급(`chmod 600`).

---

## 참고

- 상세 설정·문제 해결: **[SETUP.md](./SETUP.md)**
- 포팅 원본(읽기 전용): `../samples/{mcp-web-sample, mail-mcp-web-sample, teams-mcp-web-sample}`
- 앱 런타임 커밋은 최종 사용자에게 귀속되도록 별도 co-author 트레일러를 강제하지 않습니다.
